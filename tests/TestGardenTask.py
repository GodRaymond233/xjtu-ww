import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ok import TaskDisabledException
from src.task.GardenTask import GardenTask
from src.task.WWOneTimeTask import WWOneTimeTask


class TestGardenTask(unittest.TestCase):
    def test_completion_requires_recognized_score(self):
        task = GardenTask.__new__(GardenTask)
        for texts, expected in [([], False), (['挑战结束'], False),
                                (['6000'], False), (['5800/6000'], False),
                                (['本周积分 6000 / 6000'], True),
                                (['6000', '／', '6000'], True),
                                (['累计积分', '6000', '6000'], True),
                                (['16000'], False)]:
            with self.subTest(texts=texts):
                boxes = [SimpleNamespace(name=text) for text in texts]
                self.assertEqual(task.is_garden_done(boxes), expected)

    def test_result_screen_restarts_unknown_but_exits_recognized_completion(self):
        for score, complete in [([], False), (['6000/6000'], True), (['4200/6000'], False)]:
            with self.subTest(score=score):
                task = GardenTask.__new__(GardenTask)
                task.tr = str
                for name in ('ensure_main', 'open_garden_weekly_page', 'sleep', 'log_info', 'back'):
                    setattr(task, name, Mock())
                task.is_weekly_garden_completed = Mock(return_value=False)
                task.find_best_garden_feature = Mock(return_value=None)
                restart, back = object(), object()
                task.find_one = lambda feature: restart if feature == 'a_garden_restart' else back
                task.ocr = Mock(return_value=score)
                task.wait_feature = Mock(return_value=False)
                task.wait_book = Mock(return_value=False)

                def click(target, *args, **kwargs):
                    if target is restart:
                        raise TaskDisabledException()

                task.click = Mock(side_effect=click)
                with patch.object(WWOneTimeTask, 'run'):
                    if complete:
                        task.run()
                    else:
                        with self.assertRaises(TaskDisabledException):
                            task.run()
                result_clicks = [entry.args[0] for entry in task.click.call_args_list
                                 if entry.args[0] is restart or entry.args[0] is back]
                self.assertEqual(result_clicks, [back if complete else restart])


if __name__ == '__main__':
    unittest.main()
