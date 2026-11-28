import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
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
        self.cache = Path(temp.name) / 'protected-cache'
        self.cache.mkdir()
        self.enterContext(patch.object(portable_update, '_cache_root', return_value=self.cache))
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

    def _install(self, staging, app_process_id=-1, health_check=None):
        portable_update.apply_update(self.root, staging, app_process_id,
                                     health_check=health_check or (lambda *_: None))

    def _assert_original(self):
        self.assertEqual(portable_update.installed_version(self.root), 'v1.3.0')
        self.assertEqual((self.root / 'xjtu-ww.exe').read_bytes(), b'old executable')
        self.assertEqual((self.root / 'obsolete.dll').read_bytes(), b'old runtime')
        self.assertEqual((self.root / 'configs/custom.json').read_bytes(), b'local config')

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
            self.assertFalse(list(self.cache.rglob('.xjtu-ww-update-*')))

    @unittest.skipUnless(os.name == 'nt', 'Uses the Windows process wait API')
    def test_update_keeps_original_directory_and_preserves_exit_saves(self):
        staging = self._download()
        file_id = self.root.stat().st_ino

        def healthy(root, stage, journal):
            self.assertEqual(root.stat().st_ino, file_id)
            self.assertEqual(portable_update.installed_version(root), 'v1.4.0')
            self.assertEqual((stage / 'backup/xjtu-ww.exe').read_bytes(), b'old executable')
            self.assertEqual(journal['state'], 'awaiting-health')

        writer = """from pathlib import Path
import time

time.sleep(1)
Path('ok_tasks').mkdir()
Path('ok_tasks/custom.py').write_bytes(b'local task saved on exit')
"""
        with subprocess.Popen([sys.executable, '-c', writer], cwd=self.root,
                              creationflags=subprocess.CREATE_NO_WINDOW) as app:
            self._install(staging, app.pid, healthy)
            self.assertEqual(app.wait(timeout=5), 0)
        self.assertEqual(portable_update.installed_version(self.root), 'v1.4.0')
        self.assertEqual((self.root / 'xjtu-ww.exe').read_bytes(), b'new executable')
        self.assertEqual((self.root / 'configs/custom.json').read_bytes(), b'local config')
        self.assertEqual((self.root / 'ok_tasks/custom.py').read_bytes(), b'local task saved on exit')
        self.assertFalse((self.root / 'obsolete.dll').exists())
        self.assertEqual(self.root.stat().st_ino, file_id)
        with patch('src.windows_runtime.repair_shortcuts'):
            portable_update.finish_startup(self.root)
        self.assertFalse(staging.exists())

    def test_install_preserves_original_on_local_file_conflict(self):
        staging = self._download()
        (self.root / 'local.txt').write_bytes(b'user file')
        (staging / 'xjtu-ww/local.txt').write_bytes(b'packaged file')
        (staging / 'xjtu-ww/build-info.json').write_text(inventory('v1.4.0', 'local.txt'), encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'conflicts with a local file'):
            self._install(staging)
        self._assert_original()
        self.assertEqual((self.root / 'local.txt').read_bytes(), b'user file')

    def test_failed_startup_restores_all_files_and_removes_new_files(self):
        staging = self._download()
        (staging / 'xjtu-ww/new.dll').write_bytes(b'new library')
        (staging / 'xjtu-ww/build-info.json').write_text(inventory('v1.4.0', 'new.dll'), encoding='ascii')

        def failed(*_):
            raise OSError('startup failed')

        with self.assertRaisesRegex(OSError, 'startup failed'):
            self._install(staging, health_check=failed)
        self.assertFalse((self.root / 'configs/.last-in-app-update.json').exists())
        self._assert_original()
        self.assertFalse((self.root / 'new.dll').exists())
        self.assertEqual(json.loads((staging / portable_update.JOURNAL).read_text())['state'], 'rolled-back')

    @unittest.skipUnless(os.name == 'nt', 'Uses native Windows file sharing')
    def test_locked_executable_rolls_back_earlier_replacements(self):
        import win32con
        import win32file

        staging = self._download()
        handle = win32file.CreateFile(str(self.root / 'xjtu-ww.exe'), win32con.GENERIC_READ,
                                      win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING, 0, None)
        try:
            with self.assertRaises(OSError):
                self._install(staging)
        finally:
            handle.Close()
        self._assert_original()

    def test_interrupted_update_recovers_using_durable_journal(self):
        staging = self._download()

        def interrupted(*_):
            # Simulate process termination, bypassing the normal exception rollback.
            raise SystemExit(1)

        with self.assertRaises(SystemExit):
            self._install(staging, health_check=interrupted)
        self.assertEqual(portable_update.installed_version(self.root), 'v1.4.0')
        with self.assertRaisesRegex(OSError, 'update is in progress'):
            portable_update.guard_pending_update(self.root)
        with patch.object(portable_update, '_process_active', return_value=False), \
                patch.object(subprocess, 'Popen') as recovery:
            with self.assertRaises(SystemExit):
                portable_update.guard_pending_update(self.root)
            self.assertIn('--recover-update', recovery.call_args.args[0])
        portable_update.recover_update(self.root, staging, -1)
        self._assert_original()

    def test_inventory_rejects_escape_duplicate_and_unlisted_payload(self):
        for filename in ('../outside', 'XJTU-WW.exe', 'unlisted.dll'):
            with self.subTest(filename=filename):
                staging = self._download()
                if filename == 'unlisted.dll':
                    (staging / 'xjtu-ww/unlisted.dll').write_bytes(b'extra')
                else:
                    (staging / 'xjtu-ww/build-info.json').write_text(inventory('v1.4.0', filename), encoding='ascii')
                with self.assertRaises(ValueError):
                    self._install(staging)
                self._assert_original()

    def test_healthy_app_survives_updater_exit_before_commit(self):
        import psutil

        staging = self._download()

        def interrupted(*_):
            raise SystemExit(1)

        with self.assertRaises(SystemExit):
            self._install(staging, health_check=interrupted)
        journal = json.loads((staging / portable_update.JOURNAL).read_text(encoding='utf-8'))
        journal.update(pid=0, created=0, health_pid=os.getpid(), health_created=psutil.Process().create_time())
        portable_update._save_journal(staging, journal)
        with self.assertRaisesRegex(OSError, 'Close XJTU-WW'):
            portable_update.guard_pending_update(self.root)
        (staging / 'health-ok').write_text(journal['id'], encoding='ascii')
        portable_update.guard_pending_update(self.root)
        self.assertEqual(json.loads((staging / portable_update.JOURNAL).read_text())['state'], 'committed')
        self.assertEqual(portable_update.installed_version(self.root), 'v1.4.0')
        self.assertEqual((self.root / 'configs/custom.json').read_bytes(), b'local config')

    def test_post_update_acknowledges_matching_main_window_only(self):
        staging = self._download()
        results = []
        threads = []

        def healthy(root, stage, journal):
            thread = threading.Thread(target=lambda: results.append(portable_update.finish_startup(root, stage)))
            threads.append(thread)
            thread.start()
            deadline = time.monotonic() + 5
            while not (stage / 'health-ok').exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertEqual((stage / 'health-ok').read_text(), journal['id'])
            self.assertFalse((root / 'configs/.last-in-app-update.json').exists())

        with patch('src.windows_runtime.repair_shortcuts'):
            self._install(staging, health_check=healthy)
            threads[0].join(5)
        self.assertEqual(results, [True])
        receipt = json.loads((self.root / 'configs/.last-in-app-update.json').read_text('utf-8'))
        self.assertEqual((receipt['from_version'], receipt['to_version']), ('v1.3.0','v1.4.0'))
        with patch('src.windows_runtime.repair_shortcuts'), self.assertRaises(ValueError):
            portable_update.finish_startup(self.root, staging)

    def test_only_private_staging_is_considered_for_recovery(self):
        sibling = self.root.parent / '.xjtu-ww-update-fixture'
        sibling.mkdir()
        with patch.object(subprocess, 'Popen') as spawn:
            portable_update.guard_pending_update(self.root)
            with self.assertRaises(ValueError):
                portable_update.start_installer(self.root, sibling, False)
            with self.assertRaises(ValueError):
                portable_update.recover_update(self.root, sibling, -1)
            spawn.assert_not_called()

    def test_recovery_rejects_damaged_backup_before_restoring_files(self):
        stage = self._download()
        def interrupted(*_):
            raise SystemExit
        with self.assertRaises(SystemExit):
            self._install(stage, health_check=interrupted)
        (stage / 'backup/obsolete.dll').write_bytes(b'damaged')
        with self.assertRaisesRegex(OSError, 'Damaged rollback backup'):
            portable_update.recover_update(self.root, stage, -1)
        self.assertEqual(portable_update.installed_version(self.root), 'v1.4.0')
        self.assertEqual((self.root / 'xjtu-ww.exe').read_bytes(), b'new executable')

    def test_post_update_argument_is_optional_but_needs_an_operand(self):
        for args in ([], ['--post-update'], ['--post-update', '--help']):
            self.assertIsNone(portable_update.parse_post_update_arg(args))
        self.assertEqual(portable_update.parse_post_update_arg(['app', '--post-update', str(self.root)]), self.root)
