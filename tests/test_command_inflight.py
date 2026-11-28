import asyncio
import random
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.commands import Commands
from core.command_handler import CommandHandler
from utils import bot_control


class InflightCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.object(bot_control, "get_settings", return_value=dict(bot_control.DEFAULTS)))
        bot_control.set_running(True)
        self.addCleanup(bot_control.set_running, True)
        self.now = 1000
        self.enterContext(patch("core.cogs.commands.time.time", side_effect=lambda: self.now))
        self.bot = NS(
            misc={"command_info": {"cash": {"log_color": "#fff"}}},
            random=random.Random(0),
            settings_dict=NS(
                prefix="o", useSlashCommands=False,
                cooldowns=NS(commandHandler=NS(betweenCommands=[0, 0], readdingToQueue=7)),
            ),
            response_guard=NS(
                wait_ready=AsyncMock(), tick=Mock(), cooling_down=False, pending=None,
            ),
            stats=NS(gain_or_lose=0), gamble_streaks=NS(snapshot=lambda: {}),
            apply_dashboard_resume=AsyncMock(return_value=False),
            apply_dashboard_settings=AsyncMock(), log=AsyncMock(),
            db=NS(update_cmd_db=Mock()), send=AsyncMock(return_value=True),
            get_cog=lambda _: None,
        )
        self.bot.ch = CommandHandler(self.bot)
        self.bot.ch.cmd_priorities = {"cash": 1}
        self.manager = Commands(self.bot)
        self.command = {"id": "cash", "cmd_name": "cash", "prefix": True, "checks": True}
        await self.bot.ch.put_queue(self.command)

    async def test_pacing_wait_does_not_enqueue_a_duplicate_retry(self):
        sending = asyncio.Event()
        release = asyncio.Event()

        async def send(*args, **kwargs):
            sending.set()
            await release.wait()
            return True

        self.bot.send.side_effect = send
        sender = asyncio.create_task(self.manager.send_commands.coro(self.manager))
        self.addAsyncCleanup(self.stop_sender, sender)
        await asyncio.wait_for(sending.wait(), 1)
        self.assertEqual(self.manager._inflight_command_id, "cash")
        self.assertFalse(self.bot.ch.cmds_state["cash"]["in_queue"])
        self.now += 10
        await self.manager.monitor_checks.coro(self.manager)
        self.assertTrue(self.bot.ch.queue.empty())
        self.assertEqual(self.bot.ch.checks, [self.command])

        release.set()
        await asyncio.wait_for(sender, 1)
        self.assertIsNone(self.manager._inflight_command_id)
        self.bot.db.update_cmd_db.assert_called_once_with("cash")
        await self.manager.monitor_checks.coro(self.manager)
        self.assertEqual(self.bot.ch.queue.qsize(), 1)
        self.assertEqual(self.bot.ch.queue.get_nowait()[2], self.command)

    async def test_send_failure_clears_marker_and_leaves_retry_available(self):
        self.bot.send.side_effect = OSError("network failure")
        self.manager.sleep_between_commands = AsyncMock()
        await self.manager.send_commands.coro(self.manager)
        self.assertIsNone(self.manager._inflight_command_id)
        self.now += 10
        await self.manager.monitor_checks.coro(self.manager)
        self.assertEqual(self.bot.ch.queue.qsize(), 1)
        self.bot.db.update_cmd_db.assert_not_called()

    async def test_cancellation_clears_marker(self):
        sending = asyncio.Event()

        async def send(*args, **kwargs):
            sending.set()
            await asyncio.Event().wait()

        self.bot.send.side_effect = send
        sender = asyncio.create_task(self.manager.send_commands.coro(self.manager))
        self.addAsyncCleanup(self.stop_sender, sender)
        await asyncio.wait_for(sending.wait(), 1)
        sender.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await sender
        self.assertIsNone(self.manager._inflight_command_id)

    async def test_response_can_queue_next_command_while_send_completes(self):
        async def send(*args, **kwargs):
            await self.bot.ch.remove_queue(id="cash")
            self.assertTrue(await self.bot.ch.put_queue(self.command))
            return True

        self.bot.send.side_effect = send
        await self.manager.send_commands.coro(self.manager)
        self.assertIsNone(self.manager._inflight_command_id)
        self.assertEqual(self.bot.ch.queue.qsize(), 1)
        self.assertTrue(self.bot.ch.cmds_state["cash"]["in_queue"])

    async def stop_sender(self, sender):
        if not sender.done():
            sender.cancel()
            try:
                await sender
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    unittest.main()
