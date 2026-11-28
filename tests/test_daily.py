import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from core.cogs.daily import Daily


class DailyTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_reward_is_credited_immediately_once(self):
        bot = NS(
            cm=NS(id=99), owo_bot_id=408, get_nick=lambda _: "Player",
            db=NS(update_cmd_lastran_time=Mock()), update_cash=Mock(),
            ch=NS(remove_queue=AsyncMock()), global_settings_dict=NS(webhook=NS(enabled=False)),
        )
        cog = Daily(bot)
        cog.schedule_daily = Mock()
        claim = NS(id=123, author=NS(id=408), channel=NS(id=99),
                   content="Player! Here is your daily **<:cowoncy:416043450337853441> 1,500**!")
        await cog.on_message(claim)
        await cog.on_message(claim)
        bot.update_cash.assert_called_once_with(1500)
        bot.db.update_cmd_lastran_time.assert_called_once_with("daily")
        bot.ch.remove_queue.assert_awaited_once_with(id="daily")
        cog.schedule_daily.assert_called_once_with(after_reply=True)

    async def test_existing_schedule_is_reused(self):
        cog = Daily(NS())
        cog.start_daily = AsyncMock()
        cog.schedule_daily()
        scheduled = cog._next_daily
        cog.schedule_daily()
        self.assertIs(scheduled, cog._next_daily)
        await scheduled
        cog.start_daily.assert_awaited_once_with(after_reply=False)
