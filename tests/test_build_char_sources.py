import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/build_char_sources.py'
spec = importlib.util.spec_from_file_location('build_char_sources', SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class TestBuildCharacterSources(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'src' / 'char'
        self.source.mkdir(parents=True)
        self.destination = self.root / 'build' / 'char_sources'
        (self.source / 'BaseChar.py').write_text('class BaseChar: pass\n', encoding='utf-8')
        (self.source / 'CharFactory.py').write_text(
            'from src.char.BaseChar import BaseChar\n'
            'from src.char.Lily import Lily\n'
            '_char_dict_raw = {"lily": {"cls": Lily}}\n', encoding='utf-8')
        (self.source / 'Lily.py').write_text('class Lily:\n    revision = 1\n', encoding='utf-8')

    def load_snapshot(self):
        namespace = {}
        exec(compile((self.destination / 'Lily.py').read_bytes(), 'Lily.py', 'exec'), namespace)
        return namespace['Lily']

    def test_rebuild_uses_current_registered_source_and_removes_retired_snapshots(self):
        builder.build_character_sources(self.root, self.destination)
        self.assertEqual(self.load_snapshot().revision, 1)
        (self.destination / 'Retired.py').write_text('class Retired: pass\n', encoding='utf-8')
        (self.source / 'Lily.py').write_text('class Lily:\n    revision = 2\n', encoding='utf-8')
        builder.build_character_sources(self.root, self.destination)
        self.assertEqual(self.load_snapshot().revision, 2)
        self.assertFalse((self.destination / 'Retired.py').exists())

    def test_missing_registered_source_fails_without_destroying_last_snapshot(self):
        builder.build_character_sources(self.root, self.destination)
        (self.source / 'Lily.py').unlink()
        with self.assertRaises(FileNotFoundError):
            builder.build_character_sources(self.root, self.destination)
        self.assertEqual(self.load_snapshot().revision, 1)


if __name__ == '__main__':
    unittest.main()
