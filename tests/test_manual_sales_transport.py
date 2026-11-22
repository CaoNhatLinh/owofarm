import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

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
        self.bot.send.assert_awaited_once_with("owo sell cw",expect_response=True,manual=True)
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
        self.bot.send.assert_awaited_once_with("owo sac c u",expect_response=True,manual=True)
        self.bot.db.update_cmd_db.assert_called_once_with("sac")
        self.bot.ch.put_queue.assert_not_awaited()
        self.assertFalse(bot_control.is_running())
