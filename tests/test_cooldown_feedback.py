import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock

from utils import bot_control
from utils.command_pacing import CommandPacing
from utils.cooldown_feedback import CooldownFeedback, parse_cooldown
from utils.response_guard import ResponseGuard


DAILY_WAIT = "**⏱ |** Nu! **Player**! You need to wait **5H 30M 11S**"


def reply(text, *, author=408, channel=99, message_id=200, reference=None):
    return NS(content=text, author=NS(id=author), channel=NS(id=channel), id=message_id,
              reference=NS(message_id=reference) if reference is not None else None,
              embeds=[], components=[])


class CooldownParsingTests(unittest.TestCase):
    def test_explicit_waiting_notices_parse_seconds_minutes_and_hours(self):
        for text, expected in (
            ("Player, please wait **3.5 seconds** before hunting again!", 3.5),
            ("Player, Slow down! Please wait 5 seconds.", 5),
            ("Player, this command is on cooldown for 1 minute and 30 seconds.", 90),
            ("Player, try again in 2 hours, 3 minutes and 4 secs.", 7384),
            ("<@42>, wait for another 2 more seconds to try again.", 2),
            ("Player, cooldown: 5s", 5),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_cooldown(text).seconds, expected)

    def test_success_amounts_and_unrelated_durations_are_ignored(self):
        for text in (
            "Player, you won 100 cowoncy!",
            "Player, your huntbot will return in 2 hours!",
            "Player, You caught 5 pets in 3 seconds.",
            "Player, the wait is over after 3 seconds.",
            "Player, cooldown reduced by 5 seconds!",
            "Player, please wait for your huntbot to return.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_cooldown(text))

    def test_only_adjacent_duration_parts_are_summed(self):
        notice = parse_cooldown("Player, wait 2 seconds. You earned 3 coins in 10 seconds.")
        self.assertEqual(notice.seconds, 2)

    def test_durationless_explicit_cues_have_a_backoff_fallback(self):
        self.assertIsNone(parse_cooldown("Player, slow down!").seconds)
        self.assertIsNone(parse_cooldown("Player, this command is on cooldown.").seconds)

    def test_explicit_server_duration_is_not_shortened_to_twenty_four_hours(self):
        self.assertEqual(parse_cooldown("Player, try again in 48 hours.").seconds, 172800)
        self.assertIsNone(parse_cooldown("Player, wait " + "9" * 400 + " hours."))

    def test_backoff_is_bounded_deduplicated_and_reset_by_success(self):
        feedback = CooldownFeedback()
        pacing = Mock()
        for message_id in range(10):
            feedback.apply(message_id, "Player, slow down!", "hunt", pacing)
        self.assertEqual([call.args[1] for call in pacing.defer.call_args_list], [2, 4, 8, 16, 32, 60, 60, 60, 60, 60])
        feedback.apply(9, "Player, slow down!", "hunt", pacing)
        self.assertEqual(pacing.defer.call_count, 10)
        feedback.apply(100, "Player, caught a pet!", "hunt", pacing)
        feedback.apply(101, "Player, slow down!", "hunt", pacing)
        pacing.defer.assert_called_with(None, 2)

    def test_deduplication_memory_is_bounded(self):
        feedback = CooldownFeedback()
        for message_id in range(300):
            feedback.apply(message_id, "Player, slow down!", "hunt", Mock())
        self.assertEqual(len(feedback._seen_notices), 128)

    def test_uncertain_waiting_text_leaves_backoff_unchanged(self):
        feedback = CooldownFeedback()
        feedback.apply(1, "Player, slow down!", "hunt", Mock())
        feedback.apply(2, "Player, wait until the huntbot comes back.", "hunt", Mock())
        self.assertEqual(feedback.backoff_count, 1)


class GuardCooldownFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.config = dict(bot_control.DEFAULTS)
        self.guard = ResponseGuard("feedback-tests", clock=lambda: self.now,
                                   settings=lambda: self.config, channel_id=99)
        self.rng = Mock()
        self.rng.randint.return_value = 9
        self.rng.uniform.return_value = 0
        self.rng.random.return_value = 1
        self.guard.send_pacing = CommandPacing(clock=lambda: self.now, rng=self.rng)
        bot_control.set_running(True)
        self.addCleanup(bot_control.set_running, True)

    def sent(self, command="hunt", message_id=100, *, manual=False):
        self.guard.expect(99, min_id=message_id, manual=manual, command=command)
        self.guard.sent(NS(id=message_id), command=command, channel_id=99)

    def observe(self, message):
        return self.guard.observe(message, 42, {"Player"}, 408)

    def test_specific_cooldown_only_defers_matched_command_and_clears_pending(self):
        self.sent()
        self.assertTrue(self.observe(reply("<@42>, please wait 8 seconds before hunting again!")))
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 8.5)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="battle"), 0)
        self.assertIsNone(self.guard.pending)
        self.assertEqual(self.guard.misses, 0)

    def test_wrong_author_channel_user_reference_and_old_messages_are_rejected(self):
        for kwargs in ({"author": 9}, {"channel": 9}, {"reference": 50}, {"message_id": 50}):
            self.sent()
            self.assertFalse(self.observe(reply("Player, wait 8 seconds!", **kwargs)))
            self.assertNotIn("hunt", self.guard.send_pacing.deferred_until)
        self.assertFalse(self.observe(reply("<@7> Player, wait 8 seconds!")))
        self.assertNotIn("hunt", self.guard.send_pacing.deferred_until)

    def test_stale_recent_feedback_is_rejected_even_when_rest_is_disabled(self):
        self.config["restEnabled"] = False
        self.sent()
        self.now += self.config["responseTimeout"]
        self.assertFalse(self.observe(reply("Player, wait 8 seconds!")))
        self.assertNotIn("hunt", self.guard.send_pacing.deferred_until)

    def test_feedback_works_when_failure_rest_tracking_is_disabled(self):
        self.config["restEnabled"] = False
        self.sent()
        self.assertIsNone(self.guard.pending)
        self.assertTrue(self.observe(reply("Player, wait 8 seconds!")))
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 8.5)
        self.assertEqual(self.guard.misses, 0)

    def test_duplicate_native_raw_and_edit_notices_do_not_extend_deadline(self):
        self.sent()
        self.assertTrue(self.observe(reply("Player, wait 8 seconds!")))
        self.now += 3
        duplicate = reply("")
        duplicate.components = [{"type": 10, "content": "Player, wait 8 seconds!"}]
        self.assertTrue(self.observe(duplicate))
        duplicate.components = []
        duplicate.embeds = [NS(title="Player, wait 8 seconds!", description="", author=None, fields=[], footer=None)]
        self.assertTrue(self.observe(duplicate))
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 5.5)

    def test_generic_slowdown_applies_to_every_command(self):
        self.sent()
        self.assertTrue(self.observe(reply("Player, slow down!")))
        self.assertEqual(self.guard.send_pacing.remaining(0, command="battle"), 2)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 2)

    def test_slowdown_with_explicit_duration_applies_to_every_command(self):
        self.sent()
        self.assertTrue(self.observe(reply("Player, slow down! Please wait 8 seconds.")))
        self.assertEqual(self.guard.send_pacing.remaining(0, command="battle"), 8.5)
        self.assertNotIn("hunt", self.guard.send_pacing.deferred_until)

    def test_ambiguous_unreferenced_recent_requests_defer_the_account(self):
        self.config["restEnabled"] = False
        self.sent("hunt", 100)
        self.sent("battle", 150)
        self.assertTrue(self.observe(reply("Player, please wait 8 seconds.")))
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 8.5)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="battle"), 8.5)
        self.assertEqual(set(self.guard.send_pacing.deferred_until), {None})

    def test_daily_wait_is_scoped_even_with_ambiguous_recent_farm_commands(self):
        self.config["restEnabled"] = False
        self.sent("hunt", 100)
        self.sent("battle", 150)

        self.assertTrue(self.observe(reply(DAILY_WAIT)))

        self.assertEqual(self.guard.send_pacing.remaining(0, command="daily"), 19811.5)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 0)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="battle"), 0)
        self.assertNotIn(None, self.guard.send_pacing.deferred_until)

    def test_daily_wait_does_not_acknowledge_unrelated_pending_request(self):
        self.sent("hunt", 100)
        self.sent("battle", 150)
        pending = self.guard.pending

        self.assertTrue(self.observe(reply(DAILY_WAIT)))

        self.assertIs(self.guard.pending, pending)
        self.assertEqual(set(self.guard.send_pacing.deferred_until), {"daily"})
        self.assertEqual(self.guard.send_pacing.remaining(0, command="daily"), 19811.5)

    def test_daily_wait_acknowledges_pending_daily_request(self):
        self.sent("daily")

        self.assertTrue(self.observe(reply(DAILY_WAIT)))

        self.assertIsNone(self.guard.pending)
        self.assertEqual(set(self.guard.send_pacing.deferred_until), {"daily"})

    def test_daily_wait_ignores_another_user_or_channel(self):
        self.sent("hunt")

        self.assertFalse(self.observe(reply(DAILY_WAIT.replace("Player", "Other"))))
        self.assertFalse(self.observe(reply(DAILY_WAIT, channel=80)))
        self.assertEqual(self.guard.send_pacing.deferred_until, {})
        self.assertEqual(self.guard.pending["command"], "hunt")

    def test_ambiguous_long_wait_does_not_freeze_all_commands_for_hours(self):
        self.config["restEnabled"] = False
        self.sent("hunt", 100)
        self.sent("battle", 150)

        self.assertTrue(self.observe(reply("Player, please wait 5 hours.")))

        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 60)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="battle"), 60)

    def test_explicit_account_wide_long_wait_retains_server_duration(self):
        self.sent("hunt")

        self.assertTrue(self.observe(reply("Player, slow down! Please wait 5 hours.")))

        self.assertEqual(self.guard.send_pacing.remaining(0, command="battle"), 18000.5)
        self.assertEqual(set(self.guard.send_pacing.deferred_until), {None})

    def test_new_owned_success_resets_backoff_without_changing_existing_deadline(self):
        self.sent()
        self.observe(reply("Player, slow down!"))
        self.assertEqual(self.guard.cooldown_feedback.backoff_count, 1)
        self.observe(reply("Player, caught a pet!", message_id=201))
        self.assertEqual(self.guard.cooldown_feedback.backoff_count, 0)
        self.assertEqual(self.guard.send_pacing.deferred_until[None], self.now + 2)

    def test_reference_selects_original_command_when_another_request_is_pending(self):
        self.sent("hunt", 100)
        self.sent("battle", 150)
        self.assertTrue(self.observe(reply("wait 8 seconds!", reference=100)))
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 8.5)
        self.assertEqual(self.guard.pending["command"], "battle")
        self.assertNotIn("battle", self.guard.send_pacing.deferred_until)

    def test_early_referenced_reply_is_validated_after_send_returns_id(self):
        self.guard.expect(99, min_id=100, command="hunt")
        self.assertFalse(self.observe(reply("wait 8 seconds!", reference=101)))
        self.assertNotIn("hunt", self.guard.send_pacing.deferred_until)
        self.guard.sent(NS(id=101), command="hunt", channel_id=99)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 8.5)
        self.assertIsNone(self.guard.pending)

    def test_cancelled_request_does_not_accept_queued_early_feedback(self):
        self.guard.expect(99, min_id=100, command="hunt")
        self.observe(reply("wait 8 seconds!", reference=101))
        self.guard.cancel()
        self.assertFalse(self.observe(reply("wait 8 seconds!", reference=101)))
        self.assertNotIn("hunt", self.guard.send_pacing.deferred_until)

    def test_early_unreferenced_feedback_with_rest_disabled_waits_for_successful_send(self):
        self.config["restEnabled"] = False
        self.guard.expect(99, min_id=100, command="hunt")
        self.assertFalse(self.observe(reply("Player, wait 8 seconds!")))
        self.assertNotIn("hunt", self.guard.send_pacing.deferred_until)
        self.guard.sent(NS(id=101), command="hunt", channel_id=99)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="hunt"), 8.5)

    def test_manual_notice_changes_pacing_without_creating_a_retry(self):
        self.sent("sell", manual=True)
        self.assertTrue(self.observe(reply("Player, this command is on cooldown for 2 minutes.")))
        self.assertIsNone(self.guard.pending)
        self.assertEqual(self.guard.send_pacing.remaining(0, command="sell"), 120.5)
        self.assertEqual(len(self.guard._recent_requests), 1)


if __name__ == "__main__":
    unittest.main()
