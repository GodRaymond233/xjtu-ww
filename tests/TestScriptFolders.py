import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from ok.core import script_packager
from src.identity import _migrate_script_folders


class TestScriptFolderMigration(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.original_cwd = Path.cwd()
        os.chdir(self.directory.name)
        self.addCleanup(os.chdir, self.original_cwd)

    def test_migrated_tasks_and_assets_can_be_exported_together(self):
        legacy = Path('xjtu_scripts')
        (legacy / 'assets').mkdir(parents=True)
        (legacy / 'Example.py').write_text('class Example:\n    marker = 42\n', encoding='utf-8')
        (legacy / 'assets' / 'fixture.bin').write_bytes(b'feature-data')
        imported = Path('xjtu_import') / 'example'
        imported.mkdir(parents=True)
        (imported / 'manifest.json').write_text('{"file_name":"example"}', encoding='utf-8')
        _migrate_script_folders()
        _migrate_script_folders()
        success, message, archive = script_packager.export_script(
            ['Example.py'], 'review', 'Review', '1', output_folder=str(Path.cwd() / 'exports'))
        self.assertTrue(success, message)
        with zipfile.ZipFile(archive) as bundle:
            namespace = {}
            exec(compile(bundle.read('Example.py'), 'Example.py', 'exec'), namespace)
            self.assertEqual(namespace['Example'].marker, 42)
            self.assertEqual(bundle.read('assets/fixture.bin'), b'feature-data')
        self.assertEqual(json.loads((Path(script_packager.get_ok_import_folder()) / 'example' / 'manifest.json')
                                    .read_text(encoding='utf-8'))['file_name'], 'example')
        self.assertFalse(legacy.exists())
        self.assertFalse(Path('xjtu_import').exists())

    def test_merge_keeps_existing_files_and_removes_identical_duplicates(self):
        for folder in ('xjtu_scripts', 'ok_tasks'):
            Path(folder).mkdir()
            (Path(folder) / 'shared.py').write_text('same', encoding='utf-8')
        Path('xjtu_scripts/new.py').write_text('new', encoding='utf-8')
        Path('ok_tasks/current.py').write_text('current', encoding='utf-8')
        _migrate_script_folders()
        self.assertEqual({p.name: p.read_text(encoding='utf-8') for p in Path('ok_tasks').iterdir()},
                         {'shared.py': 'same', 'new.py': 'new', 'current.py': 'current'})
        self.assertFalse(Path('xjtu_scripts').exists())

    def test_conflict_in_plugins_preserves_both_trees_before_any_move(self):
        Path('xjtu_scripts').mkdir()
        Path('xjtu_scripts/task.py').write_text('task', encoding='utf-8')
        for folder, content in (('xjtu_import/example', 'legacy'), ('ok_import/example', 'current')):
            Path(folder).mkdir(parents=True)
            (Path(folder) / 'task.py').write_text(content, encoding='utf-8')
        with self.assertRaises(FileExistsError):
            _migrate_script_folders()
        self.assertEqual(Path('xjtu_scripts/task.py').read_text(encoding='utf-8'), 'task')
        self.assertFalse(Path('ok_tasks').exists())
        self.assertEqual(Path('xjtu_import/example/task.py').read_text(encoding='utf-8'), 'legacy')
        self.assertEqual(Path('ok_import/example/task.py').read_text(encoding='utf-8'), 'current')


if __name__ == '__main__':
    unittest.main()
