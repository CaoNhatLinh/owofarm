import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import ANY, AsyncMock, Mock, patch

from core.cogs.weapons import Weapons
from utils import bot_control
from test_weapons_runtime import make_bot, message


class ManualSalesTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bot_control.set_running(False)
        self.addCleanup(bot_control.set_running,True)
        self.bot=make_bot()
        self.bot.response_guard=NS(cooling_down=False)
        self.bot.db=NS(update_cmd_db=Mock())
        self.cog=Weapons(self.bot)
        self.cog._manual_requests=True

    async def test_manual_sale_receives_scoped_reply_without_farm_queue(self):
        async def send(command,**kwargs):
            await self.cog.on_message(message(command,author=42,message_id=100))
            await self.cog.on_message(message("Player, You sold all your Common weapons!\n**| Sold:** <:cbow:123>",message_id=200))
            return True
        self.bot.send=AsyncMock(side_effect=send)
        result=await self.cog._request_response("weapon_rank_sell","sell","cw")
        self.assertIsNotNone(result)
        self.bot.send.assert_awaited_once_with(
            "owo sell cw", channel=self.bot.cm, expect_response=True, manual=True, automation_check=ANY,
        )
        self.bot.ch.put_queue.assert_not_awaited()
        self.bot.db.update_cmd_db.assert_called_once_with("sell")
        self.assertFalse(bot_control.is_running())

    async def test_timeout_does_not_retry_or_discard_queued_farm_commands(self):
        self.bot.send=AsyncMock(return_value=True)
        self.bot.ch.queue.put_nowait((1,1,{"id":"hunt"}))
        result=await self.cog._request_response("animal_sacrifice","sac","c u")
        self.assertIsNone(result)
        self.assertEqual(self.bot.send.await_count,1)
        self.bot.ch.put_queue.assert_not_awaited()
        self.assertEqual(self.bot.ch.queue.qsize(),1)
        self.assertFalse(bot_control.is_running())

    async def test_sale_ignores_a_previous_command_reply_and_a_similar_name(self):
        async def send(command, **kwargs):
            await self.cog.on_message(message(command, author=42, message_id=100))
            reply = message("Player, You sold all your Common weapons!", message_id=200)
            reply.reference = NS(message_id=98)
            await self.cog.on_message(reply)
            await self.cog.on_message(message("Player Two, You sold all your Common weapons!", message_id=201))
            self.assertFalse(self.cog._pending.future.done())
            await self.cog.on_message(message("Player, You sold all your Common weapons!", message_id=202))
            return True

        self.bot.send = AsyncMock(side_effect=send)
        result = await self.cog._request_response("weapon_rank_sell", "sell", "cw")
        self.assertEqual(result[0].id, 202)

    async def test_captcha_blocks_direct_manual_transport(self):
        self.bot.ch.command_handler_status.captcha=True
        self.bot.send=AsyncMock()
        self.assertIsNone(await self.cog._request_response("animal_sell","sell","c u"))
        self.bot.send.assert_not_awaited()
        self.assertTrue(self.bot.ch.command_handler_status.captcha)

    async def test_sacrifice_receives_reply_while_farm_remains_stopped(self):
        async def send(command,**kwargs):
            await self.cog.on_message(message(command,author=42,message_id=100))
            await self.cog.on_message(message("Player sacrificed **<:common:1>x3** for a total of **100 essence**",message_id=200))
            return True
        self.bot.send=AsyncMock(side_effect=send)
        self.assertIsNotNone(await self.cog._request_response("animal_sacrifice","sac","c u"))
        self.bot.send.assert_awaited_once_with(
            "owo sac c u", channel=self.bot.cm, expect_response=True, manual=True, automation_check=ANY,
        )
        self.bot.db.update_cmd_db.assert_called_once_with("sac")
        self.bot.ch.put_queue.assert_not_awaited()
        self.assertFalse(bot_control.is_running())

    async def test_channel_changed_while_waiting_to_send_cancels_sale(self):
        original_channel = self.bot.cm

        async def send(command, *, channel, automation_check, **kwargs):
            self.assertIs(channel, original_channel)
            self.assertTrue(automation_check())
            await asyncio.sleep(0)
            self.bot.cm = NS(id=original_channel.id + 1)
            self.assertFalse(automation_check())
            return False

        self.bot.send = AsyncMock(side_effect=send)
        self.assertIsNone(await self.cog._request_response("weapon_rank_sell", "sell", "cw"))
        self.bot.db.update_cmd_db.assert_not_called()

    async def test_saved_prefix_changed_before_runtime_applies_cancels_sale(self):
        self.bot._dashboard_account_id = "100000000000000001"
        self.bot._initial_channel_id = self.bot.cm.id
        settings = {**bot_control.DEFAULTS, "prefix": self.bot.settings_dict.prefix}

        async def send(command, *, automation_check, **kwargs):
            self.assertTrue(automation_check())
            await asyncio.sleep(0)
            settings["prefix"] = "o"
            self.assertFalse(automation_check())
            return False

        self.bot.send = AsyncMock(side_effect=send)
        with patch.object(bot_control, "settings_for", return_value=settings):
            self.assertIsNone(await self.cog._request_response("animal_sacrifice", "sac", "c u"))
        self.bot.db.update_cmd_db.assert_not_called()
