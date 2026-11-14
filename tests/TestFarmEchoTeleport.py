import unittest
from unittest.mock import Mock, call, patch
from ok import TaskDisabledException

from src.task.FarmEchoTask import FarmEchoTask
from src.task.WWOneTimeTask import WWOneTimeTask


def make_task(config, is_team):
    task = FarmEchoTask.__new__(FarmEchoTask)
    task.config = config
    task.info = {}
    task.total_weekly_number = 9
    task.total_boss_number = 20
    task.nightmare_structure = [5, 10]
    for name in ('ensure_main', 'info_set', 'openF2Book', 'open_boss_book', 'click', 'click_configured_boss_level',
                 'click_team_challenge', 'wait_click_travel', 'wait_in_team_and_world', 'sleep'):
        setattr(task, name, Mock())
    task.book_targets = []
    task.click_on_book_target = lambda serial, total, structure=None: task.book_targets.append(
        (serial, total, structure)) or is_team
    return task


class TestFarmEchoTeleport(unittest.TestCase):

    def test_special_nightmare_is_found_after_the_nightmare_nests(self):
        task = make_task({'Teleport to Boss': 'Special Nightmare', 'Which Special Nightmare to Teleport': 3},
                         is_team=True)

        self.assertTrue(task.teleport_to_configured_boss())

        task.open_boss_book.assert_called_once_with('mengyan')
        self.assertEqual([(8, 15, [5, 10])], task.book_targets)
        task.click_team_challenge.assert_called_once_with()
        task.click_configured_boss_level.assert_not_called()

    def test_boss_challenge_target_is_unchanged(self):
        task = make_task({'Teleport to Boss': 'Boss Challenge', 'Which Boss Challenge to Teleport': 3},
                         is_team=False)

        self.assertFalse(task.teleport_to_configured_boss())

        task.open_boss_book.assert_called_once_with('qiangdi')
        self.assertEqual([(3, 20, None)], task.book_targets)
        task.wait_click_travel.assert_called_once_with()

    # With too few waveplates (incl. reserve), a "no rewards, enter anyway?" popup shows after
    # solo challenge and before the team screen.
    def test_weekly_challenge_confirms_low_waveplate_popup_before_team_screen(self):
        task = make_task({'Teleport to Boss': 'Weekly Challenge', 'Which Weekly Boss to Teleport': 2},
                         is_team=True)
        task.wait_click_skip_dialog_confirm = Mock()
        steps = Mock()
        for name in ('click_configured_boss_level', 'click', 'wait_click_skip_dialog_confirm', 'click_team_challenge'):
            steps.attach_mock(getattr(task, name), name)

        self.assertTrue(task.teleport_to_configured_boss())

        self.assertEqual([call.click_configured_boss_level(), call.click(0.880, 0.911, after_sleep=2),
                          call.wait_click_skip_dialog_confirm(time_out=1), call.click_team_challenge()],
                         steps.mock_calls)

    def test_reentry_from_f_confirms_low_waveplate_popup_before_starting(self):
        task = make_task({}, is_team=True)
        task.wait_until = Mock(return_value=True)
        task.send_key = Mock()
        task.init_parameters = Mock()
        task.wait_click_skip_dialog_confirm = Mock()
        steps = Mock()
        for name in ('click', 'wait_click_skip_dialog_confirm', 'wait_in_team_and_world'):
            steps.attach_mock(getattr(task, name), name)

        task.enter_configured_boss_realm_from_f()

        self.assertEqual([call.click(0.880, 0.911, after_sleep=2), call.wait_click_skip_dialog_confirm(time_out=1),
                          call.click(0.908, 0.919, after_sleep=5), call.wait_in_team_and_world(time_out=120)],
                         steps.mock_calls)

    def test_popup_mistaken_for_claim_is_retried_at_most_three_times(self):
        task = make_task({}, is_team=True)
        task.do_run = Mock(side_effect=RuntimeError('Teleport to boss failed'))
        task.handle_claim_button = Mock(return_value=True)
        task.handle_monthly_card = Mock(return_value=False)

        with patch.object(WWOneTimeTask, 'run'), self.assertRaises(RuntimeError):
            task.run()

        self.assertEqual(4, task.do_run.call_count)

    def test_farm_continues_after_claim_popup_is_closed(self):
        task = make_task({}, is_team=True)
        task.do_run = Mock(side_effect=[RuntimeError('Teleport to boss failed'), None])
        task.handle_claim_button = Mock(return_value=True)
        task.handle_monthly_card = Mock(return_value=False)

        with patch.object(WWOneTimeTask, 'run'):
            task.run()

        self.assertEqual(2, task.do_run.call_count)

    def test_cancelled_run_is_propagated_without_claim_recovery(self):
        task = make_task({}, is_team=True)
        cancelled = TaskDisabledException()
        task.do_run = Mock(side_effect=cancelled)
        task.handle_claim_button = Mock()
        task.handle_monthly_card = Mock()
        with patch.object(WWOneTimeTask, 'run'), self.assertRaises(TaskDisabledException) as raised:
            task.run()
        self.assertIs(raised.exception, cancelled)
        task.handle_claim_button.assert_not_called()
        task.handle_monthly_card.assert_not_called()

    def test_teleport_and_walk_cancellation_are_not_wrapped(self):
        for stage in ('teleport_to_configured_boss', 'walk_after_boss_teleport'):
            with self.subTest(stage=stage):
                task = make_task({}, is_team=False)
                task.teleport_to_configured_boss = Mock(return_value=False)
                task.walk_after_boss_teleport = Mock(return_value='combat')
                cancelled = TaskDisabledException()
                getattr(task, stage).side_effect = cancelled
                with self.assertRaises(TaskDisabledException) as raised:
                    task.teleport_to_configured_boss_and_prepare()
                self.assertIs(raised.exception, cancelled)

    def test_regular_teleport_failure_still_has_context(self):
        task = make_task({}, is_team=False)
        failure = ValueError('unreadable destination')
        task.teleport_to_configured_boss = Mock(side_effect=failure)
        task.tr = str
        with self.assertRaises(RuntimeError) as raised:
            task.teleport_to_configured_boss_and_prepare()
        self.assertIs(raised.exception.__cause__, failure)

    def test_boss_identity_is_fresh_per_run_but_preserved_for_claim_retry(self):
        task = make_task({}, is_team=True)
        task.aim_boss = 'previous account boss'
        seen = []

        def farm():
            seen.append(task.aim_boss)
            task.aim_boss = 'current boss'
            if len(seen) == 1:
                raise RuntimeError('claim popup')

        task.do_run = Mock(side_effect=farm)
        task.handle_claim_button = Mock(return_value=True)
        task.handle_monthly_card = Mock(return_value=False)
        with patch.object(WWOneTimeTask, 'run'):
            task.run()
            task.run()
        self.assertEqual(seen, [None, 'current boss', None])

    def test_walk_cancellation_releases_both_inputs(self):
        task = make_task({}, is_team=False)
        task.wait_until = Mock(return_value=False)
        task.middle_click = Mock()
        task.send_key_down = Mock()
        task.send_key_up = Mock()
        task.mouse_down = Mock()
        task.mouse_up = Mock()
        task.in_combat = Mock(side_effect=TaskDisabledException())
        with self.assertRaises(TaskDisabledException):
            task.walk_until_f_or_combat()
        task.send_key_up.assert_called_once_with('w')
        task.mouse_up.assert_called_once_with(key='right')


if __name__ == '__main__':
    unittest.main()
