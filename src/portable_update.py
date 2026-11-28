import argparse
import ctypes
import filecmp
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
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
JOURNAL = 'update-journal.json'


def parse_post_update_arg(argv):
    for i, value in enumerate(argv[:-1]):
        if value == '--post-update' and argv[i + 1] and not argv[i + 1].startswith('-'):
            return Path(argv[i + 1])
    return None


def _cache_root(create=False):
    """The elevated helper, its DLLs and rollback records share an admin-only tree."""
    import pywintypes
    import win32file
    import win32security as security
    from win32com.shell import shell, shellcon

    base = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAM_FILES, 0, 0)) / 'XJTU-WW Update Cache'
    if create and not base.exists():
        attrs = pywintypes.SECURITY_ATTRIBUTES()
        attrs.SECURITY_DESCRIPTOR = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            'O:BAG:BAD:P(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;RC;;;OW)', 1)
        try:
            win32file.CreateDirectory(str(base), attrs)
        except pywintypes.error as error:
            if error.winerror != 183:
                raise
    if base.exists():
        sd = security.GetNamedSecurityInfo(str(base), security.SE_FILE_OBJECT,
                                          security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        acl = sd.GetSecurityDescriptorDacl()
        if (_is_link(base) or security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()) != 'S-1-5-32-544'
                or acl is None or not sd.GetSecurityDescriptorControl()[0] & 0x1000):
            raise PermissionError('Untrusted update cache.')
        entries = {(header, mask, security.ConvertSidToStringSid(sid))
                   for header, mask, sid in (acl.GetAce(i) for i in range(acl.GetAceCount()))}
        if entries != {((0, 3), 0x1f01ff, 'S-1-5-32-544'), ((0, 3), 0x1f01ff, 'S-1-5-18'),
                       ((0, 3), 0x20000, 'S-1-3-4')}:
            raise PermissionError('Untrusted update cache permissions.')
    return base


def _stage_parent(root, create=False):
    key = hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()
    parent = _safe_path(_cache_root(create), key)
    if create:
        parent.mkdir(exist_ok=True)
    return parent.resolve()


def _check_stage(root, staging):
    expected = _stage_parent(root) / staging.name
    if (not staging.is_absolute() or staging.resolve() != expected or _is_link(staging)
            or not re.fullmatch(r'\.xjtu-ww-update-[a-z0-9_]+', staging.name)):
        raise ValueError('Invalid or untrusted update directory.')
    return expected


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
    staging = _stage_parent(root, True) / ('.xjtu-ww-update-' + uuid.uuid4().hex)
    staging.mkdir()
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
    staging = _check_stage(root, staging)
    if (staging / JOURNAL).exists() or (staging / 'installer-ready').exists():
        raise OSError('This staging directory already has an update transaction.')
    command = [str(staging / 'xjtu-ww/xjtu-ww.exe'), '--apply-update',
               '--install-root', str(root), '--stage', str(staging), '--app-pid', str(os.getpid())]
    if chinese:
        command.append('--chinese')
    environment = os.environ.copy()
    environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    process = subprocess.Popen(command, cwd=staging, env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (staging / 'installer-ready').is_file():
            return
        if process.poll() is not None:
            raise OSError(f'The update installer exited before preparation completed. See {staging / "update.log"}')
        time.sleep(0.1)
    process.terminate()
    process.wait(timeout=5)
    raise OSError('The update installer did not become ready; XJTU-WW is still running.')


def _is_link(path):
    try:
        status = path.lstat()
        return stat.S_ISLNK(status.st_mode) or bool(getattr(status, 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def _safe_path(root, relative):
    if _is_link(root):
        raise ValueError(f'Cannot update a Windows link: {root}')
    if not isinstance(relative, str):
        raise ValueError('Invalid package inventory path.')
    parts = relative.split('/')
    if any(not part or part in ('.', '..') or part.endswith(('.', ' '))
           or re.search(r'[\\:<>"|?*\x00-\x1f]', part) or PureWindowsPath(part).is_reserved() for part in parts):
        raise ValueError(f'Invalid package inventory path: {relative}')
    path = root
    for part in parts:
        path = path / part
        if _is_link(path):
            raise ValueError(f'Cannot update a Windows link: {path}')
    return path


@contextmanager
def _update_lock(root):
    import win32api
    import win32event

    identity = hashlib.sha256(os.path.normcase(str(root.resolve())).encode('utf-8')).hexdigest()
    handle = win32event.CreateMutex(None, False, 'Local\\XJTU-WW-update-' + identity)
    try:
        if win32api.GetLastError() == 183:
            raise OSError('Another updater is already working on this installation.')
        yield
    finally:
        handle.Close()


def _inventory(root):
    metadata = json.loads((root / 'build-info.json').read_text(encoding='utf-8-sig'))
    files = metadata['package_files']
    if not isinstance(files, list) or not files:
        raise ValueError('The package inventory is missing.')
    keys = set()
    for relative in files:
        _safe_path(root, relative)
        key = relative.casefold()
        if key in keys:
            raise ValueError(f'Duplicate package inventory path: {relative}')
        keys.add(key)
    if not {'xjtu-ww.exe', 'build-info.json', 'version.txt'} <= keys:
        raise ValueError('The package inventory is incomplete.')
    return metadata


def _validate_install(root, staging):
    # Reject links before resolving, so elevated writes stay within the named trees.
    for path in (root, staging, staging / 'xjtu-ww'):
        if _is_link(path):
            raise ValueError('Installation and staging directories must not be Windows links.')
    root, staging = root.resolve(), staging.resolve()
    staging = _check_stage(root, staging)
    if root == root.parent:
        raise ValueError('Invalid installation or staging directory.')
    payload = staging / 'xjtu-ww'
    old, new = _inventory(root), _inventory(payload)
    if installed_version(root) != old['version'] or installed_version(payload) != new['version']:
        raise ValueError('Package version and inventory do not match.')
    old_keys = {relative.casefold() for relative in old['package_files']}
    new_keys = {relative.casefold() for relative in new['package_files']}
    actual = set()
    for path in payload.rglob('*'):
        relative = path.relative_to(payload).as_posix()
        _safe_path(payload, relative)
        if path.is_file():
            actual.add(relative.casefold())
    if actual != new_keys:
        raise ValueError('The update payload does not match its inventory.')
    for relative in new['package_files']:
        destination = _safe_path(root, relative)
        if destination.exists() and (relative.casefold() not in old_keys or not destination.is_file()):
            raise ValueError(f'The update conflicts with a local file: {relative}')
    return root, staging, old, new


def _save_journal(staging, journal):
    temporary = staging / (JOURNAL + '.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(journal, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, staging / JOURNAL)


def _retry(operation):
    for attempt in range(20):
        try:
            return operation()
        except OSError:
            if attempt == 19:
                raise
            time.sleep(0.1)


def _replace_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.xjtu-new-', dir=destination.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if destination.exists() and os.name == 'nt':
            replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
            replace.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
            replace.restype = ctypes.c_int

            def commit():
                if not replace(str(destination), str(temporary), None, 0, None, None):
                    raise ctypes.WinError(ctypes.get_last_error())
            _retry(commit)
        else:
            _retry(lambda: os.replace(temporary, destination))
    finally:
        temporary.unlink(missing_ok=True)


def _rollback(root, staging, journal):
    count_path = staging / 'progress'
    touched = journal['paths'][:int(count_path.read_text('ascii'))] if count_path.exists() else []
    # Validate every required backup before restoring the first file.
    for relative in touched:
        digest = journal['backup_hashes'].get(relative.casefold())
        if digest is not None:
            backup = _safe_path(staging / 'backup', relative)
            with backup.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                    raise OSError(f'Damaged rollback backup: {relative}')
    failures = []
    for relative in reversed(touched):
        try:
            destination = _safe_path(root, relative)
            backup = _safe_path(staging / 'backup', relative)
            if relative.casefold() in journal['backup_hashes']:
                if not backup.is_file():
                    raise OSError(f'The rollback backup is missing: {relative}')
                if not destination.is_file() or not filecmp.cmp(backup, destination, shallow=False):
                    _replace_file(backup, destination)
            else:
                _retry(lambda: destination.unlink(missing_ok=True))
        except (OSError, ValueError) as error:
            failures.append(str(error))
    journal['state'] = 'recovery-needed' if failures else 'rolled-back'
    _save_journal(staging, journal)
    if failures:
        raise OSError('Recovery is incomplete; backups were retained. ' + '; '.join(failures))


def _wait_for_app(pid, ready):
    if pid <= 0:
        ready()
        return
    import win32api
    import win32event

    try:
        process = win32api.OpenProcess(0x100000, False, pid)
    except win32api.error as error:
        if error.winerror != 87:  # A process that already exited needs no wait.
            raise
        ready()
        return
    try:
        ready()
        if win32event.WaitForSingleObject(process, 60000) != win32event.WAIT_OBJECT_0:
            raise TimeoutError('XJTU-WW did not exit in time.')
    finally:
        process.Close()


def _check_startup(root, staging, journal):
    import psutil

    environment = os.environ.copy()
    environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    process = subprocess.Popen([str(root / 'xjtu-ww.exe'), '--post-update', str(staging)],
                               cwd=root, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        journal['health_pid'] = process.pid
        journal['health_created'] = psutil.Process(process.pid).create_time()
        _save_journal(staging, journal)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            marker = staging / 'health-ok'
            if marker.is_file() and marker.read_text(encoding='ascii') == journal['id']:
                if process.poll() is not None:
                    raise OSError('The updated app exited during its startup check.')
                return
            if process.poll() is not None:
                raise OSError(f'The updated app exited during startup ({process.returncode}).')
            time.sleep(0.1)
        raise TimeoutError('The updated app did not display its main window in time.')
    except Exception:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        raise


def apply_update(root, staging, app_pid, *, health_check=_check_startup):
    import psutil

    root, staging = Path(root), Path(staging)
    staging = _check_stage(root, staging)
    if (staging / JOURNAL).exists():
        raise ValueError('This update has a journal; recover it before installing again.')
    _wait_for_app(app_pid, lambda: (staging / 'installer-ready').write_text('ready', encoding='ascii'))
    # Re-read after exit so last-minute saves cannot be overwritten as packaged files.
    root, staging, old, new = _validate_install(root, staging)
    old_paths = {name.casefold(): name for name in old['package_files']}
    new_paths = {name.casefold(): name for name in new['package_files']}
    paths = sorted(old_paths.keys() | new_paths.keys())
    # Runtime modules first, metadata and executable last. The install root stays present.
    tail = ['version.txt', 'build-info.json', 'xjtu-ww.exe']
    paths = [path for path in paths if path not in tail] + tail
    journal = {'id': uuid.uuid4().hex, 'root': str(root), 'version': new['version'], 'from_version': old['version'],
               'state': 'applying', 'paths': [new_paths.get(k, old_paths.get(k)) for k in paths], 'backup_hashes': {},
               'pid': os.getpid(), 'created': psutil.Process().create_time()}
    _save_journal(staging, journal)
    try:
        for key in paths:
            relative = old_paths.get(key, new_paths.get(key))
            source = _safe_path(root, relative)
            if source.is_file():
                backup = _safe_path(staging / 'backup', relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                with source.open('rb') as input_file, backup.open('wb') as output:
                    digest = hashlib.sha256()
                    while chunk := input_file.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                journal['backup_hashes'][key] = digest.hexdigest()
        _save_journal(staging, journal)
        for count, (key, relative) in enumerate(zip(paths, journal['paths']), 1):
            progress = staging / 'progress.tmp'
            with progress.open('w', encoding='ascii') as output:
                output.write(str(count))
                output.flush()
                os.fsync(output.fileno())
            os.replace(progress, staging / 'progress')
            destination = _safe_path(root, relative)
            if key in new_paths:
                _replace_file(staging / 'xjtu-ww' / relative, destination)
            else:
                _retry(lambda: destination.unlink(missing_ok=True))
        journal['state'] = 'awaiting-health'
        _save_journal(staging, journal)
        health_check(root, staging, journal)
    except Exception:
        _rollback(root, staging, journal)
        raise
    journal['state'] = 'committed'
    _save_journal(staging, journal)
    # The staged updater has loaded DLLs here; a subsequent normal launch cleans it up.


def recover_update(root, staging, app_pid):
    import psutil

    root, staging = Path(root).resolve(), Path(staging)
    staging = _check_stage(root, staging)
    journal = json.loads((staging / JOURNAL).read_text(encoding='utf-8'))
    if Path(journal['root']) != root or journal['state'] not in ('applying', 'awaiting-health', 'recovery-needed'):
        raise ValueError('This transaction cannot be recovered.')
    _wait_for_app(app_pid, lambda: None)
    executable = os.path.normcase(str(root / 'xjtu-ww.exe'))
    for process in psutil.process_iter(['exe']):
        if process.pid != os.getpid() and process.info['exe'] and os.path.normcase(process.info['exe']) == executable:
            raise OSError('Close the running XJTU-WW app before recovering this update.')
    _rollback(root, staging, journal)


def _process_active(pid, created):
    import psutil

    try:
        return bool(pid) and psutil.Process(pid).create_time() == created
    except psutil.NoSuchProcess:
        return False


def guard_pending_update(root, post_update=None):
    """Resume an interrupted transaction using the intact staged executable."""
    root = root.resolve()
    for staging in _stage_parent(root).glob('.xjtu-ww-update-*'):
        if _is_link(staging) or not (staging / JOURNAL).is_file():
            continue
        try:
            journal = json.loads((staging / JOURNAL).read_text(encoding='utf-8'))
            if Path(journal['root']) != root or journal['state'] in ('committed', 'rolled-back'):
                continue
        except (OSError, ValueError, KeyError):
            continue
        active = _process_active(journal['pid'], journal['created'])
        if active:
            if (post_update is not None and Path(post_update).resolve() == staging
                    and journal['state'] == 'awaiting-health'):
                return
            raise OSError('XJTU-WW 正在更新，请等待更新完成。 An update is in progress; please wait.')
        if _process_active(journal.get('health_pid'), journal.get('health_created')):
            marker = staging / 'health-ok'
            if (journal['state'] == 'awaiting-health' and marker.is_file()
                    and marker.read_text(encoding='ascii') == journal['id']
                    and installed_version(root) == journal['version']):
                journal['state'] = 'committed'
                _save_journal(staging, journal)
                continue
            raise OSError('新版 XJTU-WW 仍在运行，请关闭后重试更新恢复。 Close XJTU-WW before update recovery.')
        executable = staging / 'xjtu-ww/xjtu-ww.exe'
        if not executable.is_file():
            raise OSError(f'The recovery executable is missing. Backups: {staging / "backup"}')
        _check_stage(root, staging)
        environment = {**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'}
        subprocess.Popen([str(executable), '--recover-update', '--install-root', str(root),
                          '--stage', str(staging), '--app-pid', str(os.getpid())], cwd=staging,
                         env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise SystemExit(0)


def finish_startup(root, staging=None):
    from src.windows_runtime import repair_shortcuts
    from src.telemetry import write_update_receipt
    root = root.resolve()

    if staging is not None:
        staging = Path(staging)
        staging = _check_stage(root, staging)
        journal = json.loads((staging / JOURNAL).read_text(encoding='utf-8'))
        if (Path(journal['root']) != root or journal['state'] != 'awaiting-health'
                or journal['version'] != installed_version(root)):
            raise ValueError('The startup check does not match this installation.')
        (staging / 'health-ok').write_text(journal['id'], encoding='ascii')
        # The installer can still roll back after a main window has appeared.
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            journal = json.loads((staging / JOURNAL).read_text(encoding='utf-8'))
            if journal['state'] == 'committed':
                break
            if journal['state'] != 'awaiting-health' or not _process_active(journal['pid'], journal['created']):
                return False
            time.sleep(0.1)
        else:
            return False
    try:
        repair_shortcuts(root)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Could not repair Windows shortcuts.')
    for candidate in _stage_parent(root).glob('.xjtu-ww-update-*'):
        if _is_link(candidate):
            continue
        try:
            journal = json.loads((candidate / JOURNAL).read_text(encoding='utf-8'))
            if Path(journal['root']) == root and journal['state'] in ('committed', 'rolled-back'):
                if (journal['state'] == 'committed' and journal['version'] == installed_version(root)
                        and not (candidate / 'receipt-recorded').exists()):
                    write_update_receipt(root, journal)
                    (candidate / 'receipt-recorded').touch()
                if candidate != staging:
                    shutil.rmtree(candidate)
        except (OSError, ValueError, KeyError):
            pass
    return True


def installer_main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--apply-update', action='store_true')
    mode.add_argument('--recover-update', action='store_true')
    parser.add_argument('--install-root', type=Path, required=True)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--app-pid', type=int, required=True)
    parser.add_argument('--chinese', action='store_true')
    parser.add_argument('--xjtu-admin-requested', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.install_root = args.install_root.resolve()
    args.stage = _check_stage(args.install_root, args.stage)
    try:
        with _update_lock(args.install_root):
            if args.recover_update:
                recover_update(args.install_root, args.stage, args.app_pid)
                subprocess.Popen([str(args.install_root / 'xjtu-ww.exe')], cwd=args.install_root,
                                 env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})
            else:
                apply_update(args.install_root, args.stage, args.app_pid)
        return 0
    except Exception as error:
        import traceback

        try:
            (args.stage / 'update.log').write_text(traceback.format_exc(), encoding='utf-8')
        except OSError:
            pass
        message = ('更新未完成，请查看诊断记录：' if args.chinese
                   else 'Update did not complete. See diagnostic log: ')
        ctypes.windll.user32.MessageBoxW(None, message + str(args.stage / 'update.log') + '\n' + str(error),
                                        'XJTU-WW', 0x10)
        return 1
