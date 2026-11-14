import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from ok import CannotFindException, TaskDisabledException
from src.task.BaseWWTask import BaseWWTask


def movement_task():
    task = BaseWWTask.__new__(BaseWWTask)
    for name in ('send_key_down', 'send_key_up', 'mouse_down', 'mouse_up', 'sleep',
                 'middle_click', 'next_frame', 'log_debug', 'log_info'):
        setattr(task, name, Mock())
    task.tr = str
    return task


class TestBaseWWTaskMovement(unittest.TestCase):
    def invoke(self, task, method, **kwargs):
        if method == 'run_until':
            return task.run_until(task.condition, 'w', 2, running=True, **kwargs)
        task.wait_until = Mock(side_effect=lambda *args, **kw: task.condition())
        return task.send_key_and_wait_f('w', kwargs.get('raise_if_not_found', False), 2, running=True)

    def test_success_and_missing_target_release_inputs(self):
        for method in ('run_until', 'send_key_and_wait_f'):
            with self.subTest(method=method):
                task = movement_task()
                task.condition = Mock(return_value=True)
                self.assertTrue(self.invoke(task, method))
                task.send_key_up.assert_called_once_with('w')
                task.mouse_up.assert_called_once_with(key='right')
        task = movement_task()
        task.wait_until = Mock(return_value=False)
        with self.assertRaises(CannotFindException):
            task.send_key_and_wait_f('w', True, 2, running=True)
        task.send_key_up.assert_called_once_with('w')
        task.mouse_up.assert_called_once_with(key='right')

    def test_cancel_or_failure_releases_every_attempted_input(self):
        for method in ('run_until', 'send_key_and_wait_f'):
            for stage in ('send_key_down', 'sleep', 'mouse_down', 'condition'):
                for error_type in (TaskDisabledException, RuntimeError):
                    with self.subTest(method=method, stage=stage, error=error_type):
                        task = movement_task()
                        task.condition = Mock(return_value=True)
                        error = error_type()
                        getattr(task, stage).side_effect = error
                        with self.assertRaises(error_type) as raised:
                            self.invoke(task, method)
                        self.assertIs(raised.exception, error)
                        task.send_key_up.assert_called_once_with('w')
                        if stage in ('mouse_down', 'condition'):
                            task.mouse_up.assert_called_once_with(key='right')
                        else:
                            task.mouse_up.assert_not_called()

    def test_cleanup_has_no_cancellable_wait_and_releases_mouse_even_if_key_up_fails(self):
        task = movement_task()
        task.condition = Mock(return_value=True)
        steps = Mock()
        for name in ('send_key_up', 'mouse_up', 'sleep'):
            steps.attach_mock(getattr(task, name), name)
        task.send_key_up.side_effect = RuntimeError('backend release failed')
        with self.assertRaises(RuntimeError):
            self.invoke(task, 'run_until')
        self.assertEqual(steps.mock_calls[-2:], [call.send_key_up('w'), call.mouse_up(key='right')])

    def test_post_walk_cancellation_releases_inputs(self):
        task = movement_task()
        task.sleep.side_effect = [None, TaskDisabledException()]
        with self.assertRaises(TaskDisabledException):
            task.run_until(lambda: True, 'w', 2, running=True, post_walk=1)
        task.mouse_up.assert_called_once_with(key='right')
        task.send_key_up.assert_called_once_with('w')

    def test_yolo_pickup_cancellation_stops_movement(self):
        task = movement_task()
        task.pick_f = Mock(return_value=False)
        task.in_combat = Mock(return_value=False)
        task.find_echos = Mock(return_value=[])
        with self.assertRaises(TaskDisabledException):
            task.walk_to_yolo_echo(update_function=Mock(side_effect=TaskDisabledException()))
        task.send_key_up.assert_called_once_with('w')

    def test_box_navigation_releases_right_mouse_on_wall_cancellation(self):
        task = movement_task()
        task.wait_until = Mock()
        task.width_of_screen = lambda n: n * 1000
        task.height_of_screen = lambda n: n * 1000
        task.find_one = Mock(return_value=True)
        task.sleep.side_effect = TaskDisabledException()
        target = SimpleNamespace(center=lambda: (500, 300))
        with self.assertRaises(TaskDisabledException):
            task.do_walk_to_box(lambda: target)
        task.send_key_up.assert_called_once_with('w')
        task.mouse_up.assert_called_once_with(key='right')

    def test_alt_menu_input_is_released_on_cancel(self):
        task = movement_task()
        task.click_relative = Mock(side_effect=TaskDisabledException())
        with self.assertRaises(TaskDisabledException):
            task.open_esc_menu()
        task.send_key_up.assert_called_once_with('alt')

    def test_confirm_forwards_requested_timeout(self):
        task = movement_task()
        task.wait_click_feature = Mock()
        task.click_confirm(timeout=10)
        self.assertEqual(task.wait_click_feature.call_args.kwargs['time_out'], 10)
        task.click_confirm()
        self.assertEqual(task.wait_click_feature.call_args.kwargs['time_out'], 1)


if __name__ == '__main__':
    unittest.main()
