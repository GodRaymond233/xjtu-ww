import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch


SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/install_dependencies.py'
spec = importlib.util.spec_from_file_location('install_dependencies', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class TestInstallDependencies(unittest.TestCase):
    def test_uses_cache_first_and_bypasses_it_for_transient_index_failures(self):
        with patch.object(installer.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0),
        ]) as run, patch.object(installer.time, 'sleep') as sleep:
            self.assertEqual(0, installer.pip_install(['ok-script==3.0.0'], attempts=3))
        command = [sys.executable, '-m', 'pip', 'install']
        self.assertEqual([
            call([*command, 'ok-script==3.0.0']),
            call([*command, '--no-cache-dir', 'ok-script==3.0.0']),
        ], run.call_args_list)
        sleep.assert_called_once_with(30)

    def test_returns_failure_after_bounded_attempts(self):
        with patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)) as run, \
                patch.object(installer.time, 'sleep') as sleep:
            self.assertEqual(7, installer.pip_install(['missing-package'], attempts=3))
        self.assertEqual(3, run.call_count)
        self.assertEqual(2, sleep.call_count)

    def test_installs_extras_together_with_runtime_pins_and_preserves_failure(self):
        for arguments, extras in (([], 'dev'), (['--bundle'], 'dev,bundle')):
            with self.subTest(arguments=arguments), patch.object(installer, 'pip_install', return_value=2) as install:
                self.assertEqual(2, installer.main(arguments))
            install.assert_called_once_with(['-r', 'requirements.txt', f'.[{extras}]'])


if __name__ == '__main__':
    unittest.main()
