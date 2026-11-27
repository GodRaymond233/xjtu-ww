import ast
import hashlib
import json
import tempfile
import time
import unittest
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

from ok.test.TaskTestCase import TaskTestCase
from ok.util.config import Config
from config import config
from src.char.CharFactory import apply_team_char_classes, char_dict
from src.char.CustomCharLoader import clear_team_char_cache, import_custom_team, inspect_team_archive
from src.task.AutoCombatTask import AutoCombatTask


class TestWorkshopBundle(TaskTestCase):
    task_class = AutoCombatTask
    config = config

    def test_bundled_teams_load_and_select_without_mixed_classes(self):
        root = Path(__file__).resolve().parents[1] / 'workshop_bundle'
        index = json.loads((root / 'teams.json').read_text(encoding='utf-8'))
        entries = [code for team in index['teams'] for code in team['codes']]
        self.assertEqual(len(entries), index['totalCodes'])
        self.assertEqual({code['filename'] for code in entries}, {p.name for p in (root / 'codes').glob('*.zip')})
        registry = {info['cls'].__name__: info for info in char_dict.values()}
        self.set_image('tests/images/in_combat.png')
        initial = self.task.__dict__.copy()
        with tempfile.TemporaryDirectory() as folder, patch.object(Config, 'config_folder', folder), \
                patch('threading.Thread.start'):
            for code in entries:
                with self.subTest(archive=code['filename']):
                    self.task.__dict__.clear()
                    self.task.__dict__.update(initial)
                    archive = root / 'codes' / code['filename']
                    self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), code['sha256'])
                    info = inspect_team_archive(archive)
                    for source in info['codes'].values():
                        for node in ast.walk(ast.parse(source)):
                            if isinstance(node, ast.Attribute) and node.attr in ('con_full_size', 'count_rings'):
                                self.assertTrue(hasattr(self.task, node.attr), node.attr)
                    import_custom_team(info)
                    self.task.chars = [
                        registry[name]['cls'](
                            self.task, pos, char_name=registry[name]['canonical_name'],
                            ring_index=registry[name].get('ring_index', -1),
                            char_type=registry[name]['char_type'], buff_time=registry[name]['buff_time'],
                        ) for pos, name in enumerate(info['team'])
                    ]
                    apply_team_char_classes(self.task, self.task.chars)
                    for char in self.task.chars:
                        self.assertTrue(type(char).__module__.startswith('xjtu_team_'))
                        char.reset_state()
                    for current, target in permutations(self.task.chars, 2):
                        for has_intro in (False, True):
                            target.last_full_con_switch_time = -1
                            priority = self.task._effective_switch_priority(target, current, has_intro)
                            self.assertIsInstance(priority, (int, float))
                            if target.is_healer:
                                target.last_full_con_switch_time = time.time()
                                locked_priority = self.task._effective_switch_priority(target, current, has_intro)
                                self.assertIsInstance(locked_priority, (int, float))
                                target.last_full_con_switch_time = -1
        clear_team_char_cache()
        self.task.__dict__.clear()
        self.task.__dict__.update(initial)


if __name__ == '__main__':
    unittest.main()
