import ast
import asyncio
import os
import random
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.commands import Commands
from core.cogs.weapons import Weapons
from core.command_handler import CommandHandler
from test_weapons_runtime import make_bot
from utils import bot_control
from utils.response_guard import ResponseGuard


class QueuedRequestValidityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Compile the real transport methods without starting client UI threads.
        source = Path(__file__).resolve().parents[1] / "core" / "client.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        client = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MyClient")
        methods = [node for node in client.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name in {"send", "_send_unlocked"}]
        definition = ast.ClassDef(name="Sender", bases=[], keywords=[], body=methods, decorator_list=[])
        namespace = dict(asyncio=asyncio, bot_control=bot_control, os=os, traceback=traceback,
                         global_settings_dict=NS(silentMessage=False, typingIndicator=False))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])), str(source), "exec"), namespace)
        cls.Sender = namespace["Sender"]

    async def asyncSetUp(self):
        self.enterContext(patch.object(bot_control, "get_settings", return_value=dict(bot_control.DEFAULTS)))
        bot_control.set_running(True)
        self.addCleanup(bot_control.set_running, True)
        self.bot = make_bot()
        self.bot.settings_dict.autoWeapons.responseTimeout = 0.03
        self.bot.settings_dict.useSlashCommands = False
        self.bot.settings_dict.misspell = NS(enabled=False)
        self.bot.settings_dict.cooldowns = NS(commandHandler=NS(betweenCommands=[0, 0], readdingToQueue=7))
        self.bot.misc = {
            "command_info": {"weapons": {"log_color": "#fff"}},
            "console": {"disableCommandSendLog": True},
        }
        self.bot.alias = {}
        self.bot.random = random.Random(0)
        self.bot.db = NS(update_cmd_db=Mock())
        self.bot.get_cog = lambda _: None
        self.bot.response_guard = ResponseGuard("queued-validity", settings=lambda: dict(bot_control.DEFAULTS))
        self.bot.ch = CommandHandler(self.bot)
        self.bot.ch.cmd_priorities = {"weapons": 3}
        self.bot._outgoing_lock = asyncio.Lock()
        self.network_send = AsyncMock(return_value=NS(id=100))
        self.bot.cm.send = self.network_send
        self.bot._send_unlocked = lambda *args, **kwargs: self.Sender._send_unlocked(self.bot, *args, **kwargs)
        self.bot.send = lambda *args, **kwargs: self.Sender.send(self.bot, *args, **kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

        async def wait_for_slot(*args, **kwargs):
            self.entered.set()
            await self.release.wait()
            return True

        self.bot._wait_for_send_slot = wait_for_slot
        self.cog = Weapons(self.bot)
        self.manager = Commands(self.bot)

    async def start_waiting_request(self):
        requester = asyncio.create_task(self.cog._request_response("equip", "weapon", "A1 1"))
        sender = asyncio.create_task(self.manager.send_commands.coro(self.manager))
        self.addAsyncCleanup(self.stop_task, requester)
        self.addAsyncCleanup(self.stop_task, sender)
        await asyncio.wait_for(self.entered.wait(), 1)
        self.assertTrue(self.bot.ch.queue.empty())  # Already dequeued, awaiting pacing.
        self.assertIsNotNone(self.cog._pending)
        return requester, sender

    async def test_timed_out_dequeued_request_cannot_send_after_pacing_wait(self):
        requester, sender = await self.start_waiting_request()
        self.assertIsNone(await asyncio.wait_for(requester, 1))
        self.assertIsNone(self.cog._pending)
        self.release.set()
        await asyncio.wait_for(sender, 1)
        self.network_send.assert_not_awaited()
        self.bot.db.update_cmd_db.assert_not_called()

    async def test_cancelled_dequeued_request_cannot_send_after_pacing_wait(self):
        requester, sender = await self.start_waiting_request()
        requester.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await requester
        self.release.set()
        await asyncio.wait_for(sender, 1)
        self.network_send.assert_not_awaited()
        self.bot.db.update_cmd_db.assert_not_called()

    async def test_changed_channel_invalidates_request_already_waiting_to_send(self):
        requester, sender = await self.start_waiting_request()
        self.bot.cm = NS(id=100, guild=NS(id=88), send=self.network_send)
        self.release.set()
        await asyncio.wait_for(sender, 1)
        self.network_send.assert_not_awaited()
        await self.stop_task(requester)

    async def test_changed_prefix_invalidates_request_already_waiting_to_send(self):
        requester, sender = await self.start_waiting_request()
        self.bot.settings_dict.prefix = "o"
        self.release.set()
        await asyncio.wait_for(sender, 1)
        self.network_send.assert_not_awaited()
        await self.stop_task(requester)

    async def test_completed_request_cannot_send_a_second_time(self):
        requester, sender = await self.start_waiting_request()
        self.cog._pending.future.set_result((None, "already completed"))
        self.assertEqual(await requester, (None, "already completed"))
        self.release.set()
        await asyncio.wait_for(sender, 1)
        self.network_send.assert_not_awaited()

    async def test_request_and_economy_checks_are_combined_for_text_and_slash(self):
        for slash in (False, True):
            with self.subTest(slash=slash):
                active = {"request": True, "economy": True}
                seller = NS(
                    allows_queued_command=Mock(side_effect=lambda _: active["economy"]),
                    economy_command_sent=Mock(),
                )
                self.bot.get_cog = lambda _: seller
                self.bot.settings_dict.useSlashCommands = slash

                async def transport(*args, automation_check, **kwargs):
                    self.assertTrue(automation_check())
                    active["request"] = False
                    self.assertFalse(automation_check())
                    active["request"] = True
                    active["economy"] = False
                    self.assertFalse(automation_check())
                    return False

                self.bot.send = AsyncMock(side_effect=transport)
                self.bot.slashCommandSender = AsyncMock(side_effect=transport)
                await self.bot.ch.put_queue({
                    "id": "weapons", "cmd_name": "weapon", "prefix": True, "checks": False,
                    "slash_cmd_name": "weapon", "economy_action": "test",
                    "automation_check": lambda: active["request"],
                })
                await self.manager.send_commands.coro(self.manager)
                selected = self.bot.slashCommandSender if slash else self.bot.send
                selected.assert_awaited_once()
                seller.economy_command_sent.assert_not_called()
                self.bot.db.update_cmd_db.assert_not_called()

    async def test_already_invalid_request_never_enters_transport(self):
        self.bot.send = AsyncMock()
        await self.bot.ch.put_queue({
            "id": "weapons", "cmd_name": "weapon", "prefix": True, "checks": False,
            "automation_check": lambda: False,
        })
        await self.manager.send_commands.coro(self.manager)
        self.bot.send.assert_not_awaited()
        self.assertFalse(self.bot.ch.cmds_state["weapons"]["in_queue"])

    async def stop_task(self, task):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    unittest.main()
