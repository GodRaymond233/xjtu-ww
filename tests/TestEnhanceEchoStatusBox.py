import unittest
from unittest.mock import Mock, patch

from ok.feature.Box import Box
from src.task.EnhanceEchoTask import EnhanceEchoTask


class FakeEnhanceTask:
    """Drives the drop/lock status checks with scripted feature boxes.

    find_best_match_in_box records every call it receives, so a test can
    assert the search box covers both sibling templates: a sibling template
    larger than the search area crashes cv2.matchTemplate (#1238, #1291).
    """

    tr = staticmethod(str)

    def __init__(self, boxes, match_name):
        self.boxes = boxes
        self.match_name = match_name
        self.search_calls = []
        self.fail_reason = ''
        self.config = {}
        self.counters = {}

    def get_box_by_name(self, name):
        return self.boxes[name]

    def find_best_match_in_box(self, box, names, threshold=0):
        self.search_calls.append((box, names, threshold))
        return Box(0, 0, 1, 1, name=self.match_name)

    def info_incr(self, name):
        self.counters[name] = self.counters.get(name, 0) + 1

    def info_get(self, name):
        return self.counters.get(name, 0)

    def send_key(self, key, after_sleep=0):
        """No-op: key presses do not affect the search-box geometry."""

    def log_info(self, *args, **kwargs):
        """No-op: logging is irrelevant to the assertions."""

    def screenshot_echo(self, name):
        """No-op: screenshots are irrelevant to the assertions."""

    def esc(self):
        """No-op: leaving the screen is irrelevant to the assertions."""

    def wait_ocr(self, *args, **kwargs):
        return None


class FakeSelectTask:
    """Scripts the +0 check after each click on the bag grid.

    3.7 keeps the just-enhanced echo selected (and scrolled into view) when
    returning to the bag, so the task must pick a +0 echo itself.
    """

    targets = {(0.13, 0.21): 'first card', (0.35, 0.917): 'sort order'}

    def __init__(self, zero_level_results):
        self.zero_level_results = list(zero_level_results)
        self.clicks = []

    def click(self, x, y, after_sleep=0):
        self.clicks.append(self.targets[(x, y)])

    def is_0_level(self):
        return self.zero_level_results.pop(0)


class TestEnhanceEchoStatusBox(unittest.TestCase):
    # Sibling templates deliberately differ in size, with the sibling BIGGER
    # than the anchor box: the geometry that crashed the lock pair in
    # #1238/#1291.

    def assertCovers(self, search, template_box):
        self.assertLessEqual(search.x, template_box.x)
        self.assertLessEqual(search.y, template_box.y)
        self.assertGreaterEqual(search.x + search.width,
                                template_box.x + template_box.width)
        self.assertGreaterEqual(search.y + search.height,
                                template_box.y + template_box.height)

    def test_drop_search_box_covers_both_drop_templates(self):
        dropped = Box(534, 152, 28, 26, name='echo_dropped')
        not_dropped = Box(534, 151, 28, 29, name='echo_not_dropped')
        task = FakeEnhanceTask({'echo_dropped': dropped,
                                'echo_not_dropped': not_dropped},
                               match_name='echo_dropped')

        EnhanceEchoTask.trash_and_esc(task)

        [(search, names, threshold)] = task.search_calls
        self.assertEqual(names, ['echo_dropped', 'echo_not_dropped'])
        self.assertEqual(threshold, 0.7)
        self.assertCovers(search, dropped)
        self.assertCovers(search, not_dropped)

    def test_lock_search_box_covers_both_lock_templates(self):
        locked = Box(631, 152, 23, 26, name='echo_locked')
        not_locked = Box(631, 151, 24, 29, name='echo_not_locked')
        task = FakeEnhanceTask({'echo_locked': locked,
                                'echo_not_locked': not_locked},
                               match_name='echo_locked')

        EnhanceEchoTask.lock_and_esc(task)

        [(search, names, threshold)] = task.search_calls
        self.assertEqual(names, ['echo_locked', 'echo_not_locked'])
        self.assertEqual(threshold, 0.7)
        self.assertCovers(search, locked)
        self.assertCovers(search, not_locked)

    def test_first_card_is_used_when_it_is_0_level(self):
        task = FakeSelectTask([True])

        self.assertTrue(EnhanceEchoTask.select_0_level_echo(task))

        self.assertEqual(['first card'], task.clicks)

    def test_list_returns_to_top_when_first_visible_card_is_enhanced(self):
        task = FakeSelectTask([False, True])

        self.assertTrue(EnhanceEchoTask.select_0_level_echo(task))

        self.assertEqual(['first card', 'sort order', 'sort order', 'first card'], task.clicks)

    def test_no_0_level_echo_left(self):
        task = FakeSelectTask([False, False])

        self.assertFalse(EnhanceEchoTask.select_0_level_echo(task))

        self.assertEqual(['first card', 'sort order', 'sort order', 'first card'], task.clicks)


class TestEnhanceEchoRecognition(unittest.TestCase):
    def make_task(self):
        task = EnhanceEchoTask.__new__(EnhanceEchoTask)
        task.config = {'有效词条': ['暴击', '暴击伤害', '攻击百分比'],
                       '首条双爆>=': 6.9, '双爆总计>=': 13.8, '有效词条>=': 3,
                       '第一条必须为有效词条': True, '必须有双爆': True,
                       '双爆出现之前必须全有效词条': True}
        task.tr = str
        for name in ('log_info', 'log_debug', 'info_set', 'sleep', 'next_frame', 'click',
                     'trash_and_esc', 'lock_and_esc'):
            setattr(task, name, Mock())
        return task

    def boxes(self, names, offset=0):
        return [Box(100 + offset, 100 + index * 30, 60, 20, name=name)
                for index, name in enumerate(names)]

    def test_valid_stats_pair_by_row_not_ocr_order(self):
        task = self.make_task()
        properties = self.boxes(['暴击', '暴击伤害', '攻击'])
        values = self.boxes(['6.9%', '13.8％', '8.6%'], offset=150)
        self.assertTrue(task.check_echo_stats(properties, list(reversed(values))))

    def test_recognized_low_roll_is_rejected_normally(self):
        task = self.make_task()
        self.assertFalse(task.check_echo_stats(self.boxes(['暴击']), self.boxes(['6.3%'])))

    def test_crit_damage_is_not_crit_rate(self):
        task = self.make_task()
        task.config['有效词条'] = ['暴击']
        self.assertFalse(task.check_echo_stats(self.boxes(['暴击伤害']), self.boxes(['21%'])))

    def test_incomplete_ambiguous_or_unparseable_stats_stop_before_discard(self):
        cases = [([], []), (['暴击'], []), (['暴击'], ['6.9%', '8.6%']),
                 (['暴击'], ['6..9%']), (['暴击'], ['%']), (['暴击'], ['NaN']),
                 (['未知词条'], ['6.9%']), (['防御', '暴击'], ['40', 'bad'])]
        for property_names, value_names in cases:
            with self.subTest(properties=property_names, values=value_names):
                task = self.make_task()
                with self.assertRaises(ValueError):
                    task.check_echo_stats(self.boxes(property_names), self.boxes(value_names))
                task.trash_and_esc.assert_not_called()
        for value_y in (150, 100):
            task = self.make_task()
            properties = self.boxes(['暴击', '暴击伤害'])
            values = self.boxes(['6.9%', '13.8%'])
            values[1].y = value_y
            with self.assertRaises(ValueError):
                task.check_echo_stats(properties, values)

    def test_run_does_not_trash_or_lock_echo_with_missing_value(self):
        task = self.make_task()
        task.find_echo_enhance = Mock(side_effect=[object(), None])
        task.select_0_level_echo = Mock(return_value=True)
        task.find_add_mat = Mock(side_effect=[object(), None])
        task.wait_click_ocr = Mock(return_value=True)
        task.wait_ocr = Mock(return_value=[])
        task.ocr = Mock(return_value=self.boxes(['暴击']))
        task.find_boxes = lambda texts, match: [box for box in texts if match.search(box.name)]
        with patch('src.task.EnhanceEchoTask.clear_folder'), self.assertRaises(ValueError):
            task.run()
        task.trash_and_esc.assert_not_called()
        task.lock_and_esc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
