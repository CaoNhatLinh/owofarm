import ast
import asyncio
import os
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from utils import bot_control
from utils.command_pacing import CommandPacing
from utils.gamble_pacing import GamblePacing
from utils.response_guard import ResponseGuard


class PacingTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.rng = Mock()
        self.rng.randint.return_value = 6
        self.rng.uniform.side_effect = lambda low, high: high
        self.rng.random.return_value = 1.0
        self.pacing = CommandPacing(clock=lambda: self.now, rng=self.rng)

    def test_first_send_is_immediate_and_idle_does_not_accumulate_waits(self):
        self.assertEqual(self.pacing.remaining(10), 0)
        self.pacing.sent()
        self.now += 60
        self.assertEqual(self.pacing.remaining(10), 0)

    def test_jitter_changes_between_sends_and_stays_fixed_while_waiting(self):
        self.rng.uniform.side_effect = [1.0, 2.0]
        self.pacing.sent()
        self.assertEqual(self.pacing.remaining(10), 11)
        self.now += 3
        self.assertEqual(self.pacing.remaining(10), 8)
        self.assertEqual(self.pacing.remaining(10), 8)
        self.now += 8
        self.pacing.sent()
        self.assertEqual(self.pacing.remaining(10), 12)
        self.assertEqual(self.rng.uniform.call_count, 2)

    def test_sustained_burst_opens_one_short_rest(self):
        for _ in range(6):
            self.pacing.sent()
            self.now += 4
        self.assertEqual(self.pacing.remaining(4), 16)
        self.now += 16
        self.assertEqual(self.pacing.remaining(4), 0)
        self.pacing.sent()
        self.assertEqual(self.pacing.remaining(4), 6)

    def test_slow_traffic_does_not_trigger_a_burst_rest(self):
        for _ in range(30):
            self.pacing.sent()
            self.now += 12
        self.assertEqual(self.pacing.rest_until, 0)

    def test_occasional_pause_also_occurs_without_fast_traffic(self):
        self.rng.random.return_value = 0.0
        self.pacing.sent()
        self.assertEqual(self.pacing.remaining(4), 20)
        self.now += 10
        self.assertEqual(self.pacing.remaining(4), 10)
        self.now += 10
        self.assertEqual(self.pacing.remaining(4), 0)

    def test_new_minimum_and_slowmode_are_never_shortened_by_rest(self):
        self.rng.random.return_value = 0.0
        self.pacing.sent()
        self.assertEqual(self.pacing.remaining(30), 32)
        self.assertEqual(self.pacing.remaining(4), 20)

    def test_accounts_have_independent_activity_and_rest(self):
        other = CommandPacing(clock=lambda: self.now, rng=self.rng)
        self.rng.random.return_value = 0.0
        self.pacing.sent()
        self.assertEqual(self.pacing.remaining(4), 20)
        self.assertEqual(other.remaining(4), 0)

    def test_same_command_deadline_is_sampled_once_and_other_commands_can_run(self):
        self.pacing.sent(command="hunt", cooldown=15)
        samples = self.rng.uniform.call_count
        self.now += 10
        self.assertEqual(self.pacing.remaining(4, "hunt", 15), 15.5)
        self.assertEqual(self.pacing.remaining(4, "battle", 15), 0)
        self.assertEqual(self.pacing.remaining(4, "hunt", 15), 15.5)
        self.assertEqual(self.rng.uniform.call_count, samples)

    def test_config_edits_cannot_shorten_a_sampled_deadline(self):
        self.pacing.sent(command="hunt", cooldown=15)
        self.assertEqual(self.pacing.remaining(4, "hunt", 10), 25.5)
        self.assertEqual(self.pacing.remaining(4, "hunt", 30), 40.5)

    def test_server_deadlines_extend_only_the_affected_scope(self):
        self.pacing.defer("hunt", 12)
        self.pacing.defer("hunt", 3)
        self.assertEqual(self.pacing.remaining(4, "hunt"), 12)
        self.assertEqual(self.pacing.remaining(4, "battle"), 0)
        self.pacing.defer(None, 20)
        self.assertEqual(self.pacing.remaining(4, "hunt"), 20)
        self.assertEqual(self.pacing.remaining(4, "battle"), 20)
        self.now += 20
        self.assertEqual(self.pacing.remaining(4, "hunt"), 0)


class TransportPacingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tree = ast.parse(Path("core/client.py").read_text(encoding="utf-8"))
        client = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MyClient")
        methods = [node for node in client.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name in {"send", "_send_unlocked", "_wait_for_send_slot", "slashCommandSender"}]
        definition = ast.ClassDef(name="Sender", bases=[], keywords=[], body=methods, decorator_list=[])
        namespace = dict(asyncio=asyncio, bot_control=bot_control, os=os, traceback=traceback,
                         suppress_and_log=lambda label: lambda method: method,
                         misspell_word=lambda value: value + "x",
                         global_settings_dict=NS(silentMessage=False, typingIndicator=False))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])),
                     "core/client.py", "exec"), namespace)
        self.Client = namespace["Sender"]
        self.now = 100.0
        self.config = {**bot_control.DEFAULTS, "restEnabled": False, "blackjackEnabled": True}
        self.enterContext(patch.object(bot_control, "get_settings", return_value=self.config))
        bot_control.set_running(True)
        self.addCleanup(bot_control.set_running, True)
        self.guard = ResponseGuard("command-pacing-test", clock=lambda: self.now, settings=lambda: self.config)
        rng = Mock()
        rng.randint.return_value = 6
        rng.uniform.side_effect = lambda low, high: high
        rng.random.return_value = 1.0
        self.guard.send_pacing = CommandPacing(clock=lambda: self.now, rng=rng)
        self.channel = NS(id=99, send=AsyncMock(return_value=NS(id=200)))
        self.bot = NS(
            _outgoing_lock=asyncio.Lock(), response_guard=self.guard, cm=self.channel, cm_slowmode_cd=0,
            ch=NS(command_handler_status=NS(captcha=False, sleep=False), set_stat=AsyncMock()),
            settings_dict=NS(prefix="o", misspell=NS(enabled=False)), alias={},
            misc={"console": {"disableCommandSendLog": True}}, wait_until_ready=AsyncMock(), log=AsyncMock(),
            gamble_pacing=GamblePacing(clock=lambda: self.now),
        )
        for name in ("_wait_for_send_slot", "_send_unlocked"):
            method = getattr(self.Client, name)
            setattr(self.bot, name, lambda *args, _method=method, **kwargs: _method(self.bot, *args, **kwargs))

    async def advance(self, delay):
        self.now += delay

    async def test_normal_sends_share_spacing_with_slash_commands(self):
        self.assertTrue(await self.Client.send(self.bot, "ocash"))
        first_send = self.now
        command = AsyncMock()
        command.name = "cash"
        self.bot.slash_commands = {"99": [command]}
        with patch("asyncio.sleep", side_effect=self.advance):
            self.assertTrue(await self.Client.slashCommandSender(self.bot, "cash", None, self.channel))
        self.assertGreaterEqual(self.now - first_send, 6)
        command.assert_awaited_once()
        self.assertEqual(len(self.guard.send_pacing.recent_sends), 2)

    async def test_slowmode_and_game_cooldown_still_hold_during_random_rest(self):
        self.guard.send_pacing.random.random.return_value = 0.0
        self.guard.sent(None)
        self.bot.cm_slowmode_cd = 30
        self.bot.gamble_pacing.sent("blackjack")
        with patch("asyncio.sleep", side_effect=self.advance):
            self.assertTrue(await self.Client._wait_for_send_slot(self.bot, game="blackjack"))
        self.assertGreaterEqual(self.now, 132)

    async def test_pause_or_captcha_during_rest_stops_before_network(self):
        for reason in ("pause", "captcha"):
            with self.subTest(reason=reason):
                bot_control.set_running(True)
                self.bot.ch.command_handler_status.captcha = False
                self.guard.send_pacing.random.random.return_value = 0.0
                self.guard.sent(None)

                async def interrupt(delay):
                    self.now += delay
                    if reason == "pause":
                        bot_control.set_running(False)
                    else:
                        self.bot.ch.command_handler_status.captcha = True

                with patch("asyncio.sleep", side_effect=interrupt):
                    self.assertFalse(await self.Client.send(self.bot, "ocash"))
                self.channel.send.assert_not_awaited()

    async def test_failed_network_send_does_not_count_as_activity(self):
        self.channel.send.side_effect = RuntimeError("offline")
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await self.Client.send(self.bot, "ocash")
        self.assertEqual(self.guard.send_pacing.remaining(4), 0)
        self.assertEqual(len(self.guard.send_pacing.recent_sends), 0)

    async def test_typo_correction_also_records_activity_and_waits(self):
        self.bot.settings_dict.misspell = NS(enabled=True, should_misspell=lambda: True)
        self.bot.calculate_correction_time = lambda value: 0
        with patch("asyncio.sleep", side_effect=self.advance):
            self.assertTrue(await self.Client.send(self.bot, "ocash"))
        self.assertEqual([call.args[0] for call in self.channel.send.await_args_list], ["ocashx", "ocash"])
        self.assertGreaterEqual(self.now, 106)
        self.assertEqual(len(self.guard.send_pacing.recent_sends), 2)

    async def test_concurrent_alias_sends_obey_one_actual_send_deadline(self):
        self.bot.misc["command_info"] = {"cash": {"basecd": 10}}
        self.bot.alias = {"cash": {"normal": "cash", "alias": ["money", "balance"]}}
        send_times = []

        async def send(message, **kwargs):
            send_times.append(self.now)
            return NS(id=200 + len(send_times))

        self.channel.send.side_effect = send
        with patch("asyncio.sleep", side_effect=self.advance):
            results = await asyncio.gather(
                self.Client.send(self.bot, "ocash"), self.Client.send(self.bot, "omoney"),
            )
        self.assertEqual(results, [True, True])
        self.assertGreaterEqual(send_times[1] - send_times[0], 20.5)

    async def test_configuration_raised_during_wait_extends_command_floor(self):
        self.bot.misc["command_info"] = {"cash": {"basecd": 10}}
        self.assertTrue(await self.Client.send(self.bot, "ocash"))

        async def raise_minimum(delay):
            self.bot.misc["command_info"]["cash"]["basecd"] = 30
            self.now += delay

        with patch("asyncio.sleep", side_effect=raise_minimum):
            self.assertTrue(await self.Client.send(self.bot, "ocash"))
        self.assertGreaterEqual(self.now, 140.5)

    async def test_custom_channel_slowmode_is_used(self):
        self.guard.sent(None)
        channel = NS(id=98, slowmode_delay=25)
        with patch("asyncio.sleep", side_effect=self.advance):
            self.assertTrue(await self.Client._wait_for_send_slot(self.bot, channel=channel))
        self.assertGreaterEqual(self.now, 127)

    async def test_scheduled_sleep_starting_during_wait_blocks_automated_send(self):
        self.guard.sent(None)

        async def sleep_starts(delay):
            self.now += delay
            self.bot.ch.command_handler_status.sleep = True

        with patch("asyncio.sleep", side_effect=sleep_starts):
            self.assertFalse(await self.Client.send(self.bot, "ocash"))
        self.channel.send.assert_not_awaited()

    async def test_expired_operation_interrupts_native_and_slash_pacing_wait(self):
        for use_slash in (False, True):
            with self.subTest(slash=use_slash):
                self.guard.sent(None)
                self.guard.send_pacing.defer(None, 60)
                valid = [True]
                command = AsyncMock()
                command.name = "cash"
                self.bot.slash_commands = {"99": [command]}

                async def expire(delay):
                    self.now += delay
                    valid[0] = False

                started = self.now
                with patch("asyncio.sleep", side_effect=expire):
                    if use_slash:
                        sent = await self.Client.slashCommandSender(
                            self.bot, "cash", None, self.channel, automation_check=lambda: valid[0],
                        )
                    else:
                        sent = await self.Client.send(self.bot, "ocash", automation_check=lambda: valid[0])
                self.assertFalse(sent)
                self.assertLess(self.now - started, 1)
                self.channel.send.assert_not_awaited()
                command.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
