import ctypes
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import windows_runtime as runtime


@unittest.skipUnless(os.name == 'nt', 'Windows shell and window APIs')
class TestWindowsRuntime(unittest.TestCase):
    def test_elevation_quotes_frozen_and_source_arguments(self):
        for frozen in (True, False):
            with self.subTest(frozen=frozen), patch.object(sys, 'frozen', frozen, create=True), \
                    patch.object(sys, 'argv', [r'C:\中文 路径\main.py', '--stage', r'D:\更新 [目录]']), \
                    patch.object(ctypes.windll.shell32, 'IsUserAnAdmin', return_value=0), \
                    patch.object(ctypes.windll.shell32, 'ShellExecuteW', return_value=33) as launch:
                with self.assertRaises(SystemExit):
                    runtime.restart_as_admin()
                expected = [*sys.argv[1:], '--xjtu-admin-requested'] if frozen else [*sys.argv, '--xjtu-admin-requested']
                self.assertEqual(launch.call_args.args[3], subprocess.list2cmdline(expected))
                self.assertEqual(launch.call_args.args[5], 1)
        with patch.object(ctypes.windll.shell32, 'IsUserAnAdmin', return_value=0), \
                patch.object(ctypes.windll.shell32, 'ShellExecuteW', return_value=5):
            with self.assertRaises(OSError):
                runtime.restart_as_admin()

    def test_shortcut_preserves_admin_arguments_and_does_not_rewrite_matching_link(self):
        import pythoncom
        from win32com.shell import shell

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / '中文 [安装]'
            root.mkdir()
            target = root / 'xjtu-ww.exe'
            target.write_bytes(b'test executable, never launched')
            shortcut = root / '自定义快捷方式.lnk'
            self.assertTrue(runtime.write_shortcut(shortcut, str(target), '--custom "a b"', str(root), 'Custom', '', True))
            before, timestamp = shortcut.read_bytes(), shortcut.stat().st_mtime_ns
            alias = root / '..' / root.name / target.name
            self.assertFalse(runtime.write_shortcut(shortcut, str(alias), '', str(root), 'XJTU-WW', '', False))
            self.assertEqual(shortcut.read_bytes(), before)
            self.assertEqual(shortcut.stat().st_mtime_ns, timestamp)
            self.assertTrue(runtime._link_flags(shortcut) & runtime.RUNAS_USER)

            self.assertTrue(runtime._link_flags(shortcut) & runtime.FORCE_NO_LINKTRACK)

            legacy = root.parent / '.xjtu-ww-update-fixture/previous/xjtu-ww.exe'
            runtime.write_shortcut(shortcut, str(legacy), '', str(root), '', '', False)
            self.assertEqual(runtime.repair_shortcuts(root, [root]), [str(shortcut)])
            pythoncom.CoInitialize()
            try:
                link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                                  shell.IID_IShellLink)
                link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(shortcut))
                self.assertEqual(Path(link.GetPath(shell.SLGP_RAWPATH)[0]).resolve(), target.resolve())
                self.assertEqual(link.GetArguments(), '--custom "a b"')
            finally:
                pythoncom.CoUninitialize()
            self.assertTrue(runtime._link_flags(shortcut) & runtime.RUNAS_USER)

    def test_frozen_shortcut_uses_app_without_update_arguments(self):
        import ok
        import pyappify.shortcut as shortcut
        from ok.util import process
        from contextlib import ExitStack

        with ExitStack() as stack:
            for owner, name in [(ok, '_xjtu_windows_applied'), (ok, 'restart_as_admin'),
                                (process, 'restart_as_admin'), (shortcut, '_write_shortcut'),
                                (shortcut, '_app_command')]:
                stack.enter_context(patch.object(owner, name, getattr(owner, name, None), create=True))
            if 'ok.ui.qt.MainWindow' in sys.modules:
                stack.enter_context(patch.object(sys.modules['ok.ui.qt.MainWindow'], 'restart_as_admin'))
            ok._xjtu_windows_applied = False
            runtime.apply()
            with patch.object(sys, 'frozen', True, create=True):
                self.assertEqual(shortcut._app_command('', {}, ['app', '--post-update', 'stage']), (sys.executable, []))
