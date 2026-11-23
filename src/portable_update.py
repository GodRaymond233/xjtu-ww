import base64
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path, PureWindowsPath
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zipfile import ZipFile


RELEASES = 'https://github.com/GodRaymond233/xjtu-ww/releases'
CNB_REPO = 'https://cnb.cool/GodRaymond233/xjtu-ww-update'
CNB_MANIFEST = f'{CNB_REPO}/-/git/raw/main/latest.json'
STABLE_VERSION = re.compile(r'v(\d+)\.(\d+)\.(\d+)')
HEADERS = {'User-Agent': 'XJTU-WW portable updater'}
INSTALL_SCRIPT = Path(__file__).with_name('install_update.ps1')


@dataclass(frozen=True)
class Release:
    version: str
    sha256: str = ''
    size: int = 0


def _version_parts(version):
    match = STABLE_VERSION.fullmatch(version)
    if match is None:
        raise ValueError('Invalid XJTU-WW release version.')
    return tuple(map(int, match.groups()))


def installed_version(root):
    try:
        version = (root / 'version.txt').read_text(encoding='utf-8').strip()
        metadata = json.loads((root / 'build-info.json').read_text(encoding='utf-8-sig'))
        files = metadata['package_files']
        if (STABLE_VERSION.fullmatch(version) and metadata['version'] == version and isinstance(files, list)
                and 'xjtu-ww.exe' in files and 'build-info.json' in files):
            return version
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None


class LatestRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def latest_version(current):
    request = Request(f'{RELEASES}/latest', headers=HEADERS, method='HEAD')
    try:
        with build_opener(LatestRedirect()).open(request, timeout=8):
            raise ValueError('GitHub did not redirect to a release tag.')
    except HTTPError as error:
        with error:
            if error.code not in (301, 302, 303, 307, 308):
                raise
            location = error.headers.get('Location', '')

    prefix = f'{RELEASES}/tag/'
    latest = STABLE_VERSION.fullmatch(location.removeprefix(prefix))
    if not location.startswith(prefix) or latest is None:
        raise ValueError('GitHub did not return a stable XJTU-WW release tag.')
    if _version_parts(latest.group()) > _version_parts(current):
        return latest.group()
    return None


def find_update(current):
    try:
        with urlopen(Request(CNB_MANIFEST, headers=HEADERS), timeout=5) as response:
            manifest = json.loads(response.read(4096))
        version, sha256, size = manifest['version'], manifest['sha256'], manifest['size']
        if (type(size) is not int or size <= 0 or not re.fullmatch(r'[0-9a-f]{64}', sha256)):
            raise ValueError('Invalid CNB release manifest.')
        if _version_parts(version) > _version_parts(current):
            return Release(version, sha256, size)
        mirror_checked = True
    except (OSError, HTTPException, KeyError, TypeError, ValueError):
        mirror_checked = False

    try:
        version = latest_version(current)
    except (OSError, HTTPException, ValueError):
        if mirror_checked:
            return None
        raise
    return Release(version) if version else None


def _extract_archive(archive, staging):
    with ZipFile(archive) as package:
        paths = set()
        for entry in package.infolist():
            parts = entry.filename.rstrip('/').split('/')
            if parts[0] != 'xjtu-ww' or (len(parts) == 1 and not entry.is_dir()):
                raise ValueError(f'Unexpected archive path: {entry.filename}')
            for part in parts:
                if (not part or part.endswith(('.', ' ')) or re.search(r'[\\:<>"|?*\x00-\x1f]', part)
                        or PureWindowsPath(part).is_reserved()):
                    raise ValueError(f'Invalid archive path: {entry.filename}')
            key = '/'.join(parts).casefold()
            if key in paths:
                raise ValueError(f'Duplicate archive path: {entry.filename}')
            paths.add(key)
        package.extractall(staging)


def _download_file(url, archive, expected_size, progress, cancelled):
    offset = archive.stat().st_size if archive.exists() else 0
    headers = {**HEADERS, 'Accept-Encoding': 'identity'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    with urlopen(Request(url, headers=headers), timeout=25) as response:
        if getattr(response, 'status', 200) == 206:
            if not offset or response.headers.get('Content-Range') != f'bytes {offset}-{expected_size - 1}/{expected_size}':
                raise ValueError('The server returned an invalid continuation range.')
        else:
            offset = 0
        size = expected_size or int(response.headers.get('Content-Length') or 0)
        with archive.open('ab' if offset else 'wb') as output:
            last_percent = -1
            checked_at, checked_size = time.monotonic(), offset
            read = getattr(response, 'read1', response.read)
            while chunk := read(128 * 1024):
                if cancelled():
                    raise InterruptedError('Update download cancelled.')
                output.write(chunk)
                written = output.tell()
                if size and written > size:
                    raise ValueError('The update exceeded the expected download size.')
                elapsed = time.monotonic() - checked_at
                if elapsed >= 60:
                    if (written - checked_size) / elapsed < 20 * 1024:
                        raise TimeoutError('The update download is too slow.')
                    checked_at, checked_size = time.monotonic(), written
                if size:
                    percent = written * 100 // size
                    if percent != last_percent:
                        progress(percent)
                        last_percent = percent
            if size and output.tell() != size:
                raise OSError('The update download ended early.')


def _download_release(release, archive, progress, cancelled):
    path = f'download/{release.version}/{archive.name}'
    github_url = f'{RELEASES}/{path}'
    urls = [github_url]
    checksum = release.sha256
    if checksum:
        urls.insert(0, f'{CNB_REPO}/-/releases/{path}')
    else:
        with urlopen(Request(f'{github_url}.sha256', headers=HEADERS), timeout=15) as response:
            parts = response.read(512).decode('ascii').split()
        if (len(parts) != 2 or parts[1] != archive.name or not re.fullmatch(r'[0-9a-fA-F]{64}', parts[0])):
            raise ValueError('The release checksum file is invalid.')
        checksum = parts[0].lower()

    errors = []
    for url in urls:
        # A mirror can resume another mirror's prefix because both serve the same immutable ZIP.
        attempts = 2 if archive.exists() else 1
        for _ in range(attempts):
            if cancelled():
                raise InterruptedError('Update download cancelled.')
            try:
                _download_file(url, archive, release.size, progress, cancelled)
                with archive.open('rb') as file:
                    if hashlib.file_digest(file, 'sha256').hexdigest() != checksum:
                        raise ValueError('The downloaded ZIP failed SHA-256 verification.')
                return
            except InterruptedError:
                raise
            except ValueError as error:
                archive.unlink(missing_ok=True)
                errors.append(str(error))
            except (OSError, HTTPException) as error:
                errors.append(str(error))
                break
    raise ValueError('All update download sources failed: ' + '; '.join(errors))


def stage_update(root, release, progress, cancelled):
    version = release.version
    _version_parts(version)
    if root == root.parent:
        raise ValueError('The portable app must be in its own installation folder.')
    staging = Path(tempfile.mkdtemp(prefix='.xjtu-ww-update-', dir=root.parent))
    try:
        archive = staging / f'xjtu-ww-{version}-windows-x64.zip'
        _download_release(release, archive, progress, cancelled)
        _extract_archive(archive, staging)
        payload = staging / 'xjtu-ww'
        if installed_version(payload) != version or not (payload / 'xjtu-ww.exe').is_file():
            raise ValueError('The downloaded package version or executable is missing.')
        archive.unlink()
        if cancelled():
            raise InterruptedError('Update preparation cancelled.')
        return staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def start_installer(root, staging, chinese):
    script = INSTALL_SCRIPT.read_text(encoding='utf-8')
    command = f'''& {{
{script}
}} -InstallRoot $env:XJTU_UPDATE_ROOT -Stage $env:XJTU_UPDATE_STAGE `
   -AppProcessId $env:XJTU_UPDATE_PID -Chinese:($env:XJTU_UPDATE_LANGUAGE -eq 'zh')'''
    encoded = base64.b64encode(command.encode('utf-16-le')).decode('ascii')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    environment = os.environ.copy()
    environment.update(XJTU_UPDATE_ROOT=str(root), XJTU_UPDATE_STAGE=str(staging),
                       XJTU_UPDATE_PID=str(os.getpid()), XJTU_UPDATE_LANGUAGE='zh' if chinese else 'en')
    # PyInstaller's DLL directory is inherited by child processes, including system PowerShell.
    kernel = ctypes.windll.kernel32
    dll_directory = ctypes.create_unicode_buffer(32768)
    kernel.GetDllDirectoryW(len(dll_directory), dll_directory)
    kernel.SetDllDirectoryW(None)
    try:
        subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                         cwd=staging.parent, env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        kernel.SetDllDirectoryW(dll_directory.value if dll_directory.value else None)
