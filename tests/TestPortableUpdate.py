import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from zipfile import ZipFile

from src import portable_update


def inventory(version, *files):
    return json.dumps({'version': version, 'package_files': ['build-info.json', 'version.txt', 'xjtu-ww.exe', *files]})


class TestPortableUpdate(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / '我的 [XJTU-WW]'
        self.root.mkdir()
        (self.root / 'xjtu-ww.exe').write_bytes(b'old executable')
        (self.root / 'version.txt').write_text('v1.3.0', encoding='ascii')
        (self.root / 'build-info.json').write_text(inventory('v1.3.0', 'obsolete.dll'), encoding='ascii')
        (self.root / 'obsolete.dll').write_bytes(b'old runtime')
        (self.root / 'configs').mkdir()
        (self.root / 'configs/custom.json').write_bytes(b'local config')

    def _download(self, *, corrupt=False, unsafe=False):
        data = io.BytesIO()
        with ZipFile(data, 'w') as archive:
            archive.writestr('xjtu-ww/xjtu-ww.exe', b'new executable')
            archive.writestr('xjtu-ww/version.txt', 'v1.4.0')
            archive.writestr('xjtu-ww/build-info.json', inventory('v1.4.0'))
            if unsafe:
                archive.writestr('xjtu-ww/../../outside', b'must not be extracted')
        filename = 'xjtu-ww-v1.4.0-windows-x64.zip'
        digest = '0' * 64 if corrupt else hashlib.sha256(data.getvalue()).hexdigest()

        def serve(request, **_):
            if request.full_url.endswith('.sha256'):
                return io.BytesIO(f'{digest}  {filename}\n'.encode('ascii'))
            response = io.BytesIO(data.getvalue())
            response.headers = {'Content-Length': str(len(data.getvalue()))}
            return response

        with patch.object(portable_update, 'urlopen', side_effect=serve):
            return portable_update.stage_update(self.root, portable_update.Release('v1.4.0'),
                                                lambda _: None, lambda: False)

    def _install(self, staging, app_process_id=-1):
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        script = portable_update.INSTALL_SCRIPT.read_text(encoding='utf-8')
        command = (f'& {{\n{script}\n}} -InstallRoot $env:XJTU_ROOT -Stage $env:XJTU_STAGE '
                   f'-AppProcessId {app_process_id} -Quiet')
        encoded = base64.b64encode(command.encode('utf-16-le')).decode('ascii')
        return subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                              env={**os.environ, 'XJTU_ROOT': str(self.root), 'XJTU_STAGE': str(staging)},
                              cwd=self.root.parent, capture_output=True, timeout=30,
                              creationflags=subprocess.CREATE_NO_WINDOW)

    def test_compares_stable_tags_numerically(self):
        with patch.object(portable_update, 'build_opener') as opener:
            for tag, expected in [('v1.10.0', 'v1.10.0'), ('v1.3.0', None), ('v1.2.9', None)]:
                redirect = f'{portable_update.RELEASES}/tag/{tag}'
                opener.return_value.open.side_effect = HTTPError(redirect, 302, 'Found', {'Location': redirect}, None)
                self.assertEqual(portable_update.latest_version('v1.3.0'), expected)

    def test_valid_cnb_manifest_does_not_require_github(self):
        mirror = {'version': 'v1.4.0', 'sha256': 'a' * 64, 'size': 300}
        with patch.object(portable_update, 'urlopen', return_value=io.BytesIO(json.dumps(mirror).encode())), \
                patch.object(portable_update, 'latest_version') as github:
            self.assertEqual(portable_update.find_update('v1.3.0'), portable_update.Release(**mirror))
            github.assert_not_called()

    def test_old_or_unavailable_manifest_can_fall_back_to_github(self):
        old = {'version': 'v1.3.0', 'sha256': 'a' * 64, 'size': 300}
        for mirror in (io.BytesIO(json.dumps(old).encode()), OSError('CNB unavailable')):
            with self.subTest(mirror=mirror), patch.object(portable_update, 'urlopen', side_effect=[mirror]), \
                    patch.object(portable_update, 'latest_version', return_value='v1.4.0'):
                self.assertEqual(portable_update.find_update('v1.3.0'), portable_update.Release('v1.4.0'))

    def test_partial_cnb_download_resumes_on_github(self):
        content = b'an immutable portable ZIP fixture'
        split = 12
        release = portable_update.Release('v1.4.0', hashlib.sha256(content).hexdigest(), len(content))
        archive = self.root.parent / 'xjtu-ww-v1.4.0-windows-x64.zip'
        partial = io.BytesIO(content[:split])
        partial.status = 200
        partial.headers = {'Content-Length': str(len(content))}
        remainder = io.BytesIO(content[split:])
        remainder.status = 206
        remainder.headers = {'Content-Range': f'bytes {split}-{len(content) - 1}/{len(content)}'}
        with patch.object(portable_update, 'urlopen', side_effect=[partial, remainder]) as get:
            portable_update._download_release(release, archive, lambda _: None, lambda: False)
        primary, fallback = [call.args[0] for call in get.call_args_list]
        self.assertTrue(primary.full_url.startswith(portable_update.CNB_REPO))
        self.assertTrue(fallback.full_url.startswith(portable_update.RELEASES))
        self.assertEqual(fallback.get_header('Range'), f'bytes={split}-')
        self.assertEqual(archive.read_bytes(), content)

    def test_invalid_download_never_changes_installation(self):
        for options in ({'corrupt': True}, {'unsafe': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self._download(**options)
            self.assertEqual(portable_update.installed_version(self.root), 'v1.3.0')
            self.assertEqual(list(self.root.parent.iterdir()), [self.root])

    @unittest.skipUnless(os.name == 'nt', 'Uses the Windows PowerShell installer')
    def test_validated_update_replaces_original_folder_and_preserves_user_files(self):
        staging = self._download()
        writer = """from pathlib import Path
import time

time.sleep(1)
Path('ok_tasks').mkdir()
Path('ok_tasks/custom.py').write_bytes(b'local task saved on exit')
"""
        with subprocess.Popen([sys.executable, '-c', writer], cwd=self.root,
                              creationflags=subprocess.CREATE_NO_WINDOW) as app:
            result = self._install(staging, app.pid)
            self.assertEqual(app.wait(timeout=5), 0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(portable_update.installed_version(self.root), 'v1.4.0')
        self.assertEqual((self.root / 'xjtu-ww.exe').read_bytes(), b'new executable')
        self.assertEqual((self.root / 'configs/custom.json').read_bytes(), b'local config')
        self.assertEqual((self.root / 'ok_tasks/custom.py').read_bytes(), b'local task saved on exit')
        self.assertFalse((self.root / 'obsolete.dll').exists())
        self.assertFalse(staging.exists())

    @unittest.skipUnless(os.name == 'nt', 'Uses the Windows PowerShell installer')
    def test_install_preserves_original_on_local_file_conflict(self):
        staging = self._download()
        (self.root / 'local.txt').write_bytes(b'user file')
        (staging / 'xjtu-ww/local.txt').write_bytes(b'packaged file')
        result = self._install(staging)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(portable_update.installed_version(self.root), 'v1.3.0')
        self.assertEqual((self.root / 'local.txt').read_bytes(), b'user file')
