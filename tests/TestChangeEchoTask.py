import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.ChangeEchoTask import ChangeEchoTask


def make_task(current='暴击伤害', target='暴击'):
    info = {}
    task = SimpleNamespace(config={'目标属性': target}, debug=False, tr=str)
    task.find_echo_enhance = Mock(side_effect=[object(), None, object()])
    task.is_0_level = Mock(side_effect=[True, False])
    task.info_set = lambda key, value: info.__setitem__(key, value)
    task.info_get = info.get
    task.info_incr = lambda key: info.__setitem__(key, info.get(key, 0) + 1)
    for name in ('sleep', 'click', 'wait_click_ocr', 'esc', 'log_info', 'log_error'):
        setattr(task, name, Mock())
    choices = [SimpleNamespace(name='主属性 暴击伤害'), SimpleNamespace(name='主属性： 暴 击')]

    def ocr(*args, match=None, **kwargs):
        if isinstance(match, re.Pattern):
            return [box for box in choices if match.search(box.name)]
        if match is None:
            return [SimpleNamespace(name=current)]
        return [SimpleNamespace(name=match)]

    task.wait_ocr = Mock(side_effect=ocr)
    return task, info, choices


class TestChangeEchoTask(unittest.TestCase):
    def test_empty_filtered_list_finishes_with_only_success_counter(self):
        task, info, _ = make_task()
        task.is_0_level.return_value = False
        task.is_0_level.side_effect = None
        ChangeEchoTask.run(task)
        self.assertEqual(info, {'成功声骸数量': 0})
        task.wait_click_ocr.assert_not_called()

    def test_crit_rate_target_does_not_match_damage_and_completion_counts_success(self):
        task, info, choices = make_task()
        with patch('src.task.ChangeEchoTask.os.startfile'):
            ChangeEchoTask.run(task)
        self.assertEqual(info, {'成功声骸数量': 1})
        selections = [entry.args[0] for entry in task.click.call_args_list
                      if entry.args and isinstance(entry.args[0], list)]
        self.assertEqual(selections, [[choices[1]]])
        task.esc.assert_called_once_with()

    def test_equal_stat_with_ui_prefix_and_spaces_stops_before_reconstruction(self):
        task, _, _ = make_task(current=' 主属性： 暴 击 ')
        with self.assertRaises(Exception):
            ChangeEchoTask.run(task)
        task.wait_click_ocr.assert_not_called()
        task.esc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
