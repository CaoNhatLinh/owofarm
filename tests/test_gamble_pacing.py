import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.blackjack import Blackjack
from utils import bot_control
from utils.gamble_pacing import GamblePacing
from test_weapons_runtime import make_bot


class PacingTests(unittest.TestCase):
    def test_restart_has_a_quiet_period_before_first_bet(self):
        now=[0.0]; gate=GamblePacing(clock=lambda:now[0],startup_delay=10)
        self.assertEqual(gate.remaining("blackjack"),10)
        now[0]=10
        self.assertEqual(gate.remaining("blackjack"),0)

    def test_waits_ten_seconds_after_send_and_after_result(self):
        now=[0.0]; gate=GamblePacing(clock=lambda:now[0])
        gate.sent("blackjack")
        now[0]=3
        self.assertEqual(gate.remaining("blackjack"),7)
        self.assertTrue(gate.finish("blackjack",123))
        now[0]=12
        self.assertEqual(gate.remaining("blackjack"),1)
        now[0]=13
        self.assertEqual(gate.remaining("blackjack"),0)
        self.assertEqual(gate.remaining("slots"),0)

    def test_duplicate_result_neither_recounts_nor_extends_cooldown(self):
        now=[0.0]; gate=GamblePacing(clock=lambda:now[0])
        self.assertTrue(gate.finish("coinflip",123))
        version=gate.version("coinflip")
        now[0]=5
        self.assertFalse(gate.finish("coinflip",123))
        self.assertEqual(gate.remaining("coinflip"),5)
        self.assertEqual(gate.version("coinflip"),version)


class BlackjackRoundTests(unittest.IsolatedAsyncioTestCase):
    async def test_instant_result_clears_retry_before_next_round_and_ignores_edits(self):
        bot=make_bot()
        bot.user=NS(name="player",id=42)
        bot.gamble_pacing=GamblePacing()
        bot.stats=NS(gain_or_lose=0)
        bot.update_cash=Mock()
        bot.db=NS(update_gamble_db=Mock())
        bot.ch.cmds_state["blackjack"]={"in_queue":True}
        bot.ch.checks=[{"id":"blackjack"},{"id":"hunt"}]
        bot.ch.queue.put_nowait((1,1,{"id":"blackjack"}))
        cog=Blackjack(bot)
        cog.send_blackjack=AsyncMock()
        message=NS(id=123,channel=NS(id=99),author=NS(id=408),embeds=[
            NS(author=NS(name="player's Blackjack"),footer=NS(text="🎲 ~ You lost 200 cowoncy!"))])
        config={**bot_control.DEFAULTS,"blackjackEnabled":True}
        with patch.object(bot_control,"get_settings",return_value=config):
            await cog.on_message(message)
            await cog.on_message_edit(message,message)
        self.assertEqual(cog.turns_lost,1)
        bot.update_cash.assert_called_once_with(200,reduce=True)
        cog.send_blackjack.assert_awaited_once()
        bot.db.update_gamble_db.assert_called_once_with("losses")
        self.assertTrue(bot.ch.queue.empty())
        self.assertEqual(bot.ch.checks,[{"id":"hunt"}])
        self.assertGreater(bot.gamble_pacing.remaining("blackjack"),9)
