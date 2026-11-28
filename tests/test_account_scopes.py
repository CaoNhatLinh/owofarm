import ast
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.prayer import Prayer
from core.command_handler import CommandHandler
from utils import bot_control, gambling_control
from utils.gamble_pacing import GamblePacing
from utils.response_guard import ResponseGuard


ACCOUNT_A = "100000000000000001"
ACCOUNT_B = "100000000000000002"
CHANNEL_A = "100000000000000003"
CHANNEL_B = "100000000000000004"


class AccountScopesTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Importing core.client would start the platform popup thread.
        path = Path(__file__).resolve().parents[1] / "core" / "client.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        client = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MyClient")
        selected = {"_wait_for_send_slot", "_configured_dashboard_channel", "_wait_for_dashboard_channel"}
        methods = [node for node in client.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name in selected]
        namespace = dict(asyncio=asyncio, bot_control=bot_control)
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
        cls.wait_for_send_slot = staticmethod(namespace["_wait_for_send_slot"])
        cls.configured_dashboard_channel = staticmethod(namespace["_configured_dashboard_channel"])
        cls.wait_for_dashboard_channel = staticmethod(namespace["_wait_for_dashboard_channel"])

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.settings_path = Path(directory) / "dashboard.json"
        self.enterContext(patch.multiple(
            bot_control, SETTINGS_PATH=self.settings_path,
            _settings=dict(bot_control.DEFAULTS), _account_settings={},
            _running=Event(), _paused_accounts=set(), _resume_generation=0,
            _account_resume_generations={}, _runtimes={}, _channel_checkers={},
        ))
        bot_control.set_running(True)

    def test_scoped_settings_persist_and_inherit_future_shared_changes(self):
        self.settings_path.write_text('{"prefix":"owo ","coinflipBet":200}', encoding="utf-8")
        bot_control._load_settings()
        bot_control.update_settings({"coinflipBet": 300, "channelId": CHANNEL_A}, ACCOUNT_A)
        bot_control.update_settings({"channelId": CHANNEL_B}, ACCOUNT_B)
        bot_control.update_settings({"coinflipBet": 500})

        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["accounts"][ACCOUNT_A], {"coinflipBet": 300, "channelId": CHANNEL_A})
        bot_control._account_settings.clear()
        bot_control._load_settings()
        self.assertEqual(bot_control.get_settings(ACCOUNT_A)["coinflipBet"], 300)
        self.assertEqual(bot_control.get_settings(ACCOUNT_B)["coinflipBet"], 500)
        self.assertEqual(bot_control.get_settings(ACCOUNT_B)["prefix"], "owo ")

        bot_control.clear_account_settings(ACCOUNT_A)
        self.assertEqual(bot_control.get_settings(ACCOUNT_A)["coinflipBet"], 500)
        self.assertEqual(bot_control.get_account_overrides(ACCOUNT_A), {})
        self.assertEqual(bot_control.get_account_overrides(ACCOUNT_B), {"channelId": CHANNEL_B})

    def test_cookie_recipients_load_independently_for_each_account(self):
        bot_control.update_settings({"cookieRecipientId": ACCOUNT_B}, ACCOUNT_A)
        bot_control.update_settings({"cookieRecipientId": ACCOUNT_A}, ACCOUNT_B)
        bot_control._account_settings.clear()
        bot_control._load_settings()
        self.assertEqual(bot_control.get_settings(ACCOUNT_A)["cookieRecipientId"], ACCOUNT_B)
        self.assertEqual(bot_control.get_settings(ACCOUNT_B)["cookieRecipientId"], ACCOUNT_A)
        self.assertEqual(bot_control.get_settings()["cookieRecipientId"], "")

    async def test_prayers_use_scoped_recipients_timing_and_live_switches(self):
        for sender, recipient in ((ACCOUNT_A, ""), (ACCOUNT_B, ACCOUNT_A)):
            bot_control.update_settings({"prayEnabled": True, "prayRecipientId": recipient}, sender)
        bot_control._account_settings.clear()
        bot_control._load_settings()
        first, second = (self.make_client(account) for account in (ACCOUNT_A, ACCOUNT_B))
        for bot in (first, second):
            bot.user = NS(id=int(bot._dashboard_account_id))
            bot.cm = NS(id=int(CHANNEL_A))
            bot._configured_dashboard_channel = lambda: int(CHANNEL_A)
            bot.is_ready = lambda: True
            bot.settings_dict = NS(prefix="o")
            bot.send = AsyncMock(return_value=True)
            bot.db = NS(update_cmd_db=Mock())

        self_prayer = Prayer(first)
        other_prayer = Prayer(second)
        with patch("core.cogs.prayer.time", NS(monotonic=lambda: 10)):
            await self_prayer.send_prayer.coro(self_prayer)
            await other_prayer.send_prayer.coro(other_prayer)
            await self_prayer.send_prayer.coro(self_prayer)
        first.send.assert_awaited_once()
        self.assertEqual(first.send.call_args.args, ("opray",))
        self.assertEqual(second.send.call_args.args, (f"opray <@{ACCOUNT_A}>",))
        self.assertEqual(self_prayer.next_prayer, 310)
        self.assertEqual(other_prayer.next_prayer, 310)
        self.assertTrue(first.send.call_args.kwargs["automation_check"]())
        self.assertTrue(second.send.call_args.kwargs["automation_check"]())

        bot_control.update_settings({"prayEnabled": False}, ACCOUNT_B)
        self.assertFalse(second.send.call_args.kwargs["automation_check"]())
        self.assertTrue(bot_control.manages_prayer(second))
        self.assertEqual(bot_control.get_settings(ACCOUNT_B)["prayRecipientId"], ACCOUNT_A)
        with patch("core.cogs.prayer.time", NS(monotonic=lambda: 310)):
            await self_prayer.send_prayer.coro(self_prayer)
            await other_prayer.send_prayer.coro(other_prayer)
        self.assertEqual(first.send.await_count, 2)
        second.send.assert_awaited_once()

    async def test_runtime_switches_and_pacing_are_account_scoped(self):
        bot_control.update_settings({"coinflipEnabled": True, "coinflipBet": 1000})
        bot_control.update_settings({"huntEnabled": False, "gemsEnabled": False,
                                     "coinflipEnabled": False, "coinflipBet": 300}, ACCOUNT_A)
        account_a = self.make_client(ACCOUNT_A)
        account_b = self.make_client(ACCOUNT_B)
        gambling_control.confirm_wallet(account_a, 1, 1000)
        gambling_control.confirm_wallet(account_b, 1, 1000)

        for command in ("oh", "ouse 55", "ocf 1000"):
            self.assertFalse(gambling_control.command_allowed(command, "o", {}, account_a))
            self.assertTrue(gambling_control.command_allowed(command, "o", {}, account_b))
        self.assertEqual(gambling_control.bet_amount("coinflip", 2, account_a), 1200)
        self.assertEqual(gambling_control.bet_amount("coinflip", 2, account_b), 4000)
        self.assertFalse(await account_a.ch.put_queue({"id": "hunt"}, wait=False))
        self.assertTrue(await account_b.ch.put_queue({"id": "hunt"}, wait=False))
        self.assertFalse(await self.wait_for_send_slot(account_a, game="coinflip"))
        self.assertTrue(await self.wait_for_send_slot(account_b, game="coinflip"))

    async def test_individual_and_global_pause_preserve_other_accounts_and_manual_actions(self):
        account_a = self.make_client(ACCOUNT_A)
        account_b = self.make_client(ACCOUNT_B)
        starting_generation = bot_control.get_resume_generation()
        bot_control.set_running(False, ACCOUNT_A)

        account_a.response_guard.expect(int(CHANNEL_A))
        account_b.response_guard.expect(int(CHANNEL_A))
        account_a.response_guard.tick()
        account_b.response_guard.tick()
        self.assertIsNone(account_a.response_guard.pending)
        self.assertIsNotNone(account_b.response_guard.pending)
        self.assertTrue(account_a.ch.should_not_send)
        self.assertFalse(account_b.ch.should_not_send)
        self.assertFalse(await self.wait_for_send_slot(account_a))
        self.assertTrue(await self.wait_for_send_slot(account_a, manual=True))
        self.assertTrue(await self.wait_for_send_slot(account_b))

        bot_control.set_running(False)
        self.assertFalse(await self.wait_for_send_slot(account_b))
        bot_control.set_running(True)
        self.assertFalse(bot_control.is_running(ACCOUNT_A))
        self.assertTrue(bot_control.is_running(ACCOUNT_B))
        bot_control.set_running(True, ACCOUNT_A)
        self.assertEqual(bot_control.get_resume_generation(ACCOUNT_A), starting_generation + 2)
        self.assertEqual(bot_control.get_resume_generation(ACCOUNT_B), starting_generation + 1)
        runtimes = {view["accountId"]: view for view in bot_control.get_runtimes()}
        self.assertEqual(runtimes[ACCOUNT_A]["channelId"], CHANNEL_A)
        self.assertEqual(runtimes[ACCOUNT_B]["channelId"], CHANNEL_A)

    async def test_channel_validation_targets_only_the_selected_connection(self):
        loop = asyncio.get_running_loop()
        check_a = AsyncMock()
        check_b = AsyncMock()
        bot_control.register_channel_checker(ACCOUNT_A, loop, check_a)
        bot_control.register_channel_checker(ACCOUNT_B, loop, check_b)

        self.assertTrue(bot_control.has_channel_checker(ACCOUNT_B))
        self.assertFalse(bot_control.has_channel_checker("100000000000000005"))
        await asyncio.to_thread(bot_control.validate_channel, CHANNEL_B, ACCOUNT_B)
        check_a.assert_not_awaited()
        check_b.assert_awaited_once_with(CHANNEL_B)

    async def test_scoped_channel_change_resumes_startup_after_initial_failure(self):
        account = NS(_dashboard_account_id=ACCOUNT_A, _initial_channel_id=int(CHANNEL_A),
                     wait_until_ready=AsyncMock(), is_closed=lambda: False,
                     _connect_dashboard_channel=AsyncMock(return_value=True),
                     _finish_dashboard_startup=AsyncMock())
        account._configured_dashboard_channel = lambda: self.configured_dashboard_channel(account)
        bot_control.update_settings({"channelId": CHANNEL_B}, ACCOUNT_A)

        await asyncio.wait_for(self.wait_for_dashboard_channel(account, int(CHANNEL_A)), 1)
        account._connect_dashboard_channel.assert_awaited_once_with(int(CHANNEL_B))
        account._finish_dashboard_startup.assert_awaited_once()

    def make_client(self, account_id):
        bot = NS(_dashboard_account_id=account_id, misc={"command_info": {"hunt": {}}},
                 gamble_pacing=GamblePacing())
        bot.response_guard = ResponseGuard(account_id, settings=lambda: bot_control.settings_for(bot),
                                           channel_id=CHANNEL_A)
        bot.response_guard.account_id = account_id
        bot.response_guard.tick()
        bot.ch = CommandHandler(bot)
        bot.ch.cmd_priorities = {"hunt": 1}
        return bot
