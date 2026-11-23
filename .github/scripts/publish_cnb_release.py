"""Mirror the Windows ZIP to CNB and advance the public manifest after verification."""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


CNB_REPO = 'https://cnb.cool/GodRaymond233/xjtu-ww-update'
CNB_GIT = f'{CNB_REPO}.git'
CNB_API = 'https://api.cnb.cool/GodRaymond233/xjtu-ww-update/-/releases'
CNB_DOWNLOADS = f'{CNB_REPO}/-/releases/download'
STABLE = re.compile(r'v(\d+)\.(\d+)\.(\d+)')


def version_parts(version):
    match = STABLE.fullmatch(version)
    if match is None:
        raise ValueError('CNB publishing requires a stable vX.Y.Z tag.')
    return tuple(map(int, match.groups()))


def api(url, token, data=None, *, missing=False):
    headers = {'Accept': 'application/vnd.cnb.api+json', 'Content-Type': 'application/json',
               'User-Agent': 'xjtu-ww-release'}
    request = Request(url, headers=headers, data=json.dumps(data).encode() if data is not None else None)
    request.add_unredirected_header('Authorization', f'Bearer {token}')
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read()
            return json.loads(body) if body else None
    except HTTPError as error:
        if missing and error.code == 404:
            return None
        raise RuntimeError(f'CNB release API returned HTTP {error.code}.') from None


def publish_asset(archive, version, token):
    endpoint = f'{CNB_API}/tags/{version}'
    release = api(endpoint, token, missing=True)
    if release is None:
        release = api(CNB_API, token, {'tag_name': version, 'target_commitish': version,
                                     'name': version, 'prerelease': False})
    assets = {asset['name'] for asset in release.get('assets') or []}
    if archive.name in assets:
        return

    upload = api(f'{CNB_API}/{release["id"]}/asset-upload-url', token,
                 {'asset_name': archive.name, 'size': archive.stat().st_size, 'overwrite': False, 'ttl': 0})
    verify_url = urljoin(CNB_API, upload['verify_url'])
    if not verify_url.startswith(f'{CNB_API}/{release["id"]}/asset-upload-confirmation/'):
        raise ValueError('Unexpected CNB upload confirmation URL.')
    upload_url = urlsplit(upload['upload_url'])
    if upload_url.scheme != 'https' or not upload_url.hostname:
        raise ValueError('CNB storage upload requires HTTPS.')
    try:
        with archive.open('rb') as stream:
            request = Request(upload['upload_url'], data=stream, method='PUT',
                              headers={'Content-Length': str(archive.stat().st_size)})
            with urlopen(request, timeout=300):
                pass
    except OSError:
        raise RuntimeError('CNB storage upload failed.') from None
    api(verify_url, token, {})


def verify_asset(download, sha256):
    for attempt in range(3):
        try:
            with urlopen(download, timeout=30) as response:
                if hashlib.file_digest(response, 'sha256').hexdigest() != sha256:
                    raise ValueError('Public CNB asset SHA-256 differs from the GitHub build.')
                return
        except OSError:
            if attempt == 2:
                raise
            time.sleep(3)


def publish(archive, version, token):
    version_parts(version)
    if archive.name != f'xjtu-ww-{version}-windows-x64.zip':
        raise ValueError('The Windows ZIP filename must match the release tag.')
    with archive.open('rb') as stream:
        sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'version': version, 'size': archive.stat().st_size, 'sha256': sha256}

    authorization = base64.b64encode(f'cnb:{token}'.encode()).decode()
    environment = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '1',
                   'GIT_CONFIG_KEY_0': 'http.https://cnb.cool/.extraHeader',
                   'GIT_CONFIG_VALUE_0': f'Authorization: Basic {authorization}'}
    with tempfile.TemporaryDirectory(prefix='xjtu-ww-cnb-') as temp:
        def git(*args, check=True):
            return subprocess.run(['git', *args], cwd=temp, env=environment, check=check, text=True,
                                  stdout=subprocess.PIPE)

        git('clone', '--quiet', '--branch', 'main', '--depth', '1', CNB_GIT, '.')
        manifest_file = Path(temp) / 'latest.json'
        if manifest_file.is_file():
            current = json.loads(manifest_file.read_text(encoding='utf-8'))
            if version_parts(current['version']) > version_parts(version):
                print(f'CNB already advertises {current["version"]}; keep it as the latest version.')
                return
            if current['version'] == version and current != manifest:
                raise ValueError('That CNB version already points to different bytes. Publish a new version tag.')

        ref = f'refs/tags/{version}'
        tag = git('ls-remote', '--exit-code', 'origin', ref, check=False)
        if tag.returncode == 2:
            git('push', 'origin', f'HEAD:{ref}')
        else:
            tag.check_returncode()

        publish_asset(archive, version, token)
        verify_asset(f'{CNB_DOWNLOADS}/{version}/{archive.name}', sha256)
        text = json.dumps(manifest, indent=2) + '\n'
        if manifest_file.is_file() and manifest_file.read_text(encoding='utf-8') == text:
            print(f'CNB {version} is already published and verified.')
            return
        manifest_file.write_text(text, encoding='utf-8')
        git('add', 'latest.json')
        git('-c', 'user.name=xjtu-ww release', '-c', 'user.email=actions@users.noreply.github.com',
            'commit', '-m', f'Publish {version}')
        git('push', 'origin', 'HEAD:refs/heads/main')
        print(f'Published and verified {version} on CNB.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    publish(args.archive, args.tag, os.environ['CNB_GH'])
