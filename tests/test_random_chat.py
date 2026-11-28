import ast
import asyncio
import json
import os
import tempfile
import traceback
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.chat import Chat
from utils import bot_control
from utils.command_pacing import CommandPacing
from utils.random_chat import PHRASES, RandomChat
from utils.response_guard import ResponseGuard


ACCOUNT_A = "100000000000000001"
ACCOUNT_B = "100000000000000002"


class RandomChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.multiple(
            bot_control, _settings=dict(bot_control.DEFAULTS), _account_settings={},
            _running=Event(), _paused_accounts=set(), _runtimes={},
            _resume_generation=0, _account_resume_generations={},
        ))
        bot_control.set_running(True)
        self.config = bot_control._settings
        self.config["randomChatEnabled"] = True
        self.now = 100.0
        self.channel = NS(id=99, slowmode_delay=0, send=AsyncMock(return_value=NS(id=200)))
        self.manager = NS(_inflight_command_id=None)
        self.bot = NS(
            _outgoing_lock=asyncio.Lock(), cm=self.channel, cm_slowmode_cd=0,
            ch=NS(command_handler_status=NS(state=True, hold_handler=False, sleep=False, captcha=False),
                  queue=asyncio.PriorityQueue(), checks=[]),
            settings_dict=NS(prefix="o", misspell=NS(enabled=True)), alias={},
            global_settings_dict=NS(textCommands=NS(
                prefix=".", stopCommand="stop", startCommand="start", sleepCommand="sleep",
                restartCommand="restart_captcha", switchChannelCommand="switch_channel",
            )),
            get_cog=lambda name: self.manager if name == "Commands" else None,
            send=AsyncMock(return_value=True),
            misc={"console": {"disableCommandSendLog": True}},
            wait_until_ready=AsyncMock(), log=AsyncMock(),
        )
        self.guard = ResponseGuard("random-chat-test", clock=lambda: self.now,
                                   settings=lambda: bot_control.settings_for(self.bot), channel_id=99)
        rng = Mock()
        rng.randint.return_value = 9
        rng.uniform.return_value = 0.0
        rng.random.return_value = 1.0
        self.guard.send_pacing = CommandPacing(clock=lambda: self.now, rng=rng)
        self.bot.response_guard = self.guard
        self.rng = Mock()
        self.rng.uniform.side_effect = lambda low, high: low
        self.rng.choice.side_effect = lambda choices: choices[0]
        self.chat = RandomChat(self.bot, clock=lambda: self.now, rng=self.rng)

    def due(self):
        self.chat.next_at = self.now

    async def test_default_off_and_enabling_waits_for_first_random_interval(self):
        self.assertFalse(bot_control.DEFAULTS["randomChatEnabled"])
        self.config["randomChatEnabled"] = False
        self.assertFalse(await self.chat.tick())
        self.assertIsNone(self.chat.next_at)
        self.config["randomChatEnabled"] = True
        self.assertFalse(await self.chat.tick())
        self.assertEqual(self.chat.next_at, self.now + 120)
        self.rng.uniform.assert_called_once_with(120, 360)
        self.now += 119
        self.assertFalse(await self.chat.tick())
        self.bot.send.assert_not_awaited()
        self.now += 1
        self.assertTrue(await self.chat.tick())

    async def test_idle_send_uses_normal_transport_without_response_or_typing(self):
        self.due()
        self.assertTrue(await self.chat.tick())
        call = self.bot.send.await_args
        self.assertIn(call.args[0], PHRASES)
        self.assertIs(call.kwargs["channel"], self.channel)
        self.assertFalse(call.kwargs["expect_response"])
        self.assertFalse(call.kwargs["typingIndicator"])
        self.assertTrue(call.kwargs["automation_check"]())
        self.assertIsNone(self.guard.pending)
        self.assertTrue(self.bot.ch.queue.empty())
        self.assertEqual(self.bot.ch.checks, [])

    async def test_last_three_successful_phrases_are_not_repeated(self):
        messages = []
        for _ in range(8):
            self.due()
            self.assertTrue(await self.chat.tick())
            phrase = self.bot.send.await_args.args[0]
            self.assertNotIn(phrase, messages[-3:])
            messages.append(phrase)
            self.now += 120
        self.assertEqual(len(self.chat.recent_phrases), 3)

    async def test_pending_reply_and_failure_rest_block_chat(self):
        self.due()
        self.guard.expect(99, min_id=100)
        self.assertFalse(await self.chat.tick())
        self.guard.cancel()
        self.guard.rest_until = self.now + 60
        self.assertFalse(await self.chat.tick())
        self.bot.send.assert_not_awaited()

    async def test_all_handler_pauses_block_chat(self):
        self.due()
        status = self.bot.ch.command_handler_status
        for field, value in (("state", False), ("hold_handler", True), ("sleep", True), ("captcha", True)):
            with self.subTest(field=field), patch.object(status, field, value):
                self.assertFalse(await self.chat.tick())
        self.bot.send.assert_not_awaited()

    async def test_global_and_per_account_pauses_block_only_affected_account(self):
        self.due()
        self.bot._dashboard_account_id = ACCOUNT_A
        bot_control.set_running(False, ACCOUNT_B)
        self.assertTrue(self.chat.can_send(self.channel, "o"))
        bot_control.set_running(False, ACCOUNT_A)
        self.assertFalse(await self.chat.tick())
        bot_control.set_running(True, ACCOUNT_A)
        bot_control.set_running(False)
        self.assertFalse(await self.chat.tick())
        self.bot.send.assert_not_awaited()

    async def test_queue_inflight_and_outgoing_lock_preempt_chat(self):
        self.due()
        self.bot.ch.queue.put_nowait((1, 1, {"id": "hunt"}))
        self.assertFalse(await self.chat.tick())
        self.bot.ch.queue.get_nowait()
        self.manager._inflight_command_id = "hunt"
        self.assertFalse(await self.chat.tick())
        self.manager._inflight_command_id = None
        async with self.bot._outgoing_lock:
            self.assertFalse(await self.chat.tick())
        self.bot.send.assert_not_awaited()

    async def test_checks_without_an_inflight_command_do_not_starve_idle_chat(self):
        self.due()
        self.bot.ch.checks.append({"id": "hunt"})
        self.assertTrue(await self.chat.tick())

    async def test_account_spacing_server_rest_and_channel_slowmode_block_chat(self):
        self.due()
        self.guard.last_sent = self.now - 3
        self.assertFalse(await self.chat.tick())
        self.guard.last_sent = float("-inf")
        self.guard.send_pacing.defer(None, 8)
        self.assertFalse(await self.chat.tick())
        self.now += 8
        self.channel.slowmode_delay = 10
        self.guard.last_sent = self.now - 6
        self.assertFalse(await self.chat.tick())
        self.bot.send.assert_not_awaited()

    async def test_disabled_chat_drops_due_time_and_reenable_starts_new_interval(self):
        self.due()
        self.config["randomChatEnabled"] = False
        self.assertFalse(await self.chat.tick())
        self.assertIsNone(self.chat.next_at)
        self.config["randomChatEnabled"] = True
        self.assertFalse(await self.chat.tick())
        self.assertEqual(self.chat.next_at, self.now + 120)
        self.bot.send.assert_not_awaited()

    async def test_failed_or_raising_send_does_not_retry_in_a_tight_loop(self):
        for failure in (False, RuntimeError("offline")):
            with self.subTest(failure=failure):
                self.due()
                self.bot.send.reset_mock()
                self.bot.send.side_effect = failure if isinstance(failure, Exception) else None
                self.bot.send.return_value = False
                if isinstance(failure, Exception):
                    with self.assertRaisesRegex(RuntimeError, "offline"):
                        await self.chat.tick()
                else:
                    self.assertFalse(await self.chat.tick())
                self.assertEqual(self.chat.next_at, self.now + 120)
                self.assertFalse(await self.chat.tick())
                self.assertEqual(self.bot.send.await_count, 1)
                self.assertEqual(list(self.chat.recent_phrases), [])

    async def test_unsafe_phrase_pool_is_skipped_and_rescheduled(self):
        self.bot.settings_dict.prefix = "h"
        self.config["prefix"] = "h"
        self.due()
        with patch("utils.random_chat.PHRASES", ("hmm", "hello")):
            self.assertFalse(await self.chat.tick())
        self.assertEqual(self.chat.next_at, self.now + 120)
        self.bot.send.assert_not_awaited()

    def test_game_prefixes_builtin_commands_and_custom_exact_commands_are_rejected(self):
        for phrase in ("oh", "owo hunt", "uwu battle", "owo", "uwu"):
            with self.subTest(phrase=phrase):
                self.assertFalse(self.chat.phrase_allowed(phrase))
        self.bot.settings_dict.prefix = "h"
        self.assertFalse(self.chat.phrase_allowed("hmm"))
        self.bot.settings_dict.prefix = "o"
        self.bot.settings_dict.customCommands = NS(enabled=True, commands=[
            NS(enabled=True, command="hmm", cooldown=10),
        ])
        self.assertFalse(self.chat.phrase_allowed("hmm"))

    def test_text_command_triggers_are_rejected_with_empty_or_short_prefixes(self):
        settings = self.bot.global_settings_dict.textCommands
        for prefix, command, phrase in (("", "hm", "hmm"), ("h", "m", "hmm"), (".", "stop", ".STOP now")):
            for field in ("stopCommand", "startCommand", "sleepCommand", "restartCommand", "switchChannelCommand"):
                with self.subTest(prefix=prefix, field=field), patch.object(settings, "prefix", prefix), patch.object(settings, field, command):
                    self.assertFalse(self.chat.phrase_allowed(phrase))
        self.assertTrue(self.chat.phrase_allowed("ờ để xem"))

    def test_empty_control_command_and_prefix_fail_closed(self):
        settings = self.bot.global_settings_dict.textCommands
        for field in ("stopCommand", "startCommand", "sleepCommand", "restartCommand", "switchChannelCommand"):
            with self.subTest(field=field), patch.object(settings, "prefix", ""), patch.object(settings, field, ""):
                self.assertFalse(self.chat.phrase_allowed("hmm"))
                self.assertFalse(self.chat.phrase_allowed("ờ để xem"))

    async def test_real_transport_owns_lock_and_rechecks_racing_changes_before_network(self):
        self.attach_real_transport()
        self.due()

        async def ready():
            self.assertTrue(self.bot._outgoing_lock.locked())
            self.assertTrue(self.chat.can_send(self.channel, "o", "hmm"))

        self.bot.wait_until_ready.side_effect = ready
        self.assertTrue(await self.chat.tick())
        self.channel.send.assert_awaited_once_with("hmm", silent=False)
        self.assertFalse(self.bot._outgoing_lock.locked())

    async def test_real_transport_aborts_on_toggle_channel_prefix_or_queue_race(self):
        self.attach_real_transport()
        mutations = (
            lambda: self.config.update(randomChatEnabled=False),
            lambda: setattr(self.bot, "cm", NS(id=98)),
            lambda: setattr(self.bot.settings_dict, "prefix", "x"),
            lambda: self.config.update(prefix="x"),
            lambda: self.config.update(channelId="100000000000000003"),
            lambda: self.bot.ch.queue.put_nowait((1, 1, {"id": "hunt"})),
            lambda: setattr(self.manager, "_inflight_command_id", "hunt"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.config.update(randomChatEnabled=True, prefix="o", channelId="")
                self.bot.cm = self.channel
                self.bot.settings_dict.prefix = "o"
                self.manager._inflight_command_id = None
                while not self.bot.ch.queue.empty():
                    self.bot.ch.queue.get_nowait()
                self.due()

                async def change_before_network():
                    self.assertTrue(self.bot._outgoing_lock.locked())
                    mutate()

                self.bot.wait_until_ready.side_effect = change_before_network
                self.assertFalse(await self.chat.tick())
                self.channel.send.assert_not_awaited()
                self.assertFalse(self.bot._outgoing_lock.locked())

    def attach_real_transport(self):
        # Importing core.client would start platform UI; execute its actual methods.
        path = Path(__file__).resolve().parents[1] / "core" / "client.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        client = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MyClient")
        methods = [node for node in client.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name in {"send", "_send_unlocked", "_wait_for_send_slot"}]
        definition = ast.ClassDef(name="Sender", bases=[], keywords=[], body=methods, decorator_list=[])
        namespace = dict(asyncio=asyncio, bot_control=bot_control, os=os, traceback=traceback,
                         global_settings_dict=NS(silentMessage=False, typingIndicator=False))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])), str(path), "exec"), namespace)
        for name in ("send", "_send_unlocked", "_wait_for_send_slot"):
            method = getattr(namespace["Sender"], name)
            setattr(self.bot, name, lambda *args, _method=method, **kwargs: _method(self.bot, *args, **kwargs))

    async def test_cog_unload_cancels_random_loop_and_existing_timed_sleep(self):
        cog = Chat(self.bot)
        entered = asyncio.Event()

        async def tick():
            entered.set()
            await asyncio.Event().wait()

        cog.random_chat.tick = AsyncMock(side_effect=tick)
        cog.timed_task = asyncio.create_task(asyncio.Event().wait())
        await cog.cog_load()
        loop_task = cog.random_chat_loop.get_task()
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await cog.cog_unload()
            results = await asyncio.gather(loop_task, cog.timed_task, return_exceptions=True)
            self.assertTrue(all(isinstance(result, asyncio.CancelledError) for result in results))
            self.assertFalse(cog.random_chat_loop.is_running())
        finally:
            for task in (loop_task, cog.timed_task):
                if task is not None and not task.done():
                    task.cancel()


class RandomChatSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.settings_path = Path(directory) / "dashboard.json"
        self.enterContext(patch.multiple(
            bot_control, SETTINGS_PATH=self.settings_path,
            _settings=dict(bot_control.DEFAULTS), _account_settings={},
        ))

    def test_toggle_is_strictly_boolean(self):
        for value in (False, True):
            self.assertEqual(bot_control.validate_settings({"randomChatEnabled": value}), {"randomChatEnabled": value})
        for value in (0, 1, "true", None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bot_control.validate_settings({"randomChatEnabled": value})

    def test_toggle_persists_and_is_account_scoped(self):
        bot_control.update_settings({"randomChatEnabled": True}, ACCOUNT_A)
        self.assertTrue(bot_control.settings_for(NS(_dashboard_account_id=ACCOUNT_A))["randomChatEnabled"])
        self.assertFalse(bot_control.settings_for(NS(_dashboard_account_id=ACCOUNT_B))["randomChatEnabled"])
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["accounts"][ACCOUNT_A], {"randomChatEnabled": True})
        bot_control._account_settings.clear()
        bot_control._load_settings()
        self.assertTrue(bot_control.get_settings(ACCOUNT_A)["randomChatEnabled"])
        self.assertFalse(bot_control.get_settings(ACCOUNT_B)["randomChatEnabled"])

    def test_flask_api_saves_toggle_for_only_selected_account(self):
        from website import website

        with patch.object(website, "password", "test"), patch("utils.account_setup.list_accounts", return_value=[
            {"accountId": ACCOUNT_A}, {"accountId": ACCOUNT_B},
        ]):
            client = website.app.test_client()
            response = client.patch("/api/settings?accountId=" + ACCOUNT_A,
                                    headers={"password": "test"}, json={"randomChatEnabled": True})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["settings"]["randomChatEnabled"])
            self.assertFalse(client.get("/api/settings?accountId=" + ACCOUNT_B).json["settings"]["randomChatEnabled"])
            self.assertEqual(client.patch("/api/settings?accountId=" + ACCOUNT_A,
                                         headers={"password": "test"}, json={"randomChatEnabled": 1}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
