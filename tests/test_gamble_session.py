import tempfile
import sqlite3
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.coinflip import Coinflip
from utils import bot_control, gamble_session
from utils.gamble_pacing import GamblePacing
from website import website


class StreakTests(unittest.TestCase):
    def test_current_streak_is_restored_and_old_best_only_files_are_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"streaks.sqlite"
            conn=sqlite3.connect(path)
            with conn:
                conn.execute("CREATE TABLE streaks (account TEXT,game TEXT,best INTEGER,PRIMARY KEY(account,game))")
                conn.execute("INSERT INTO streaks VALUES ('42','coinflip',7)")
            conn.close()
            state=gamble_session.read_state("42",path)
            self.assertEqual(state["coinflip"],{"current":0,"best":7})
            tracker=gamble_session.Streaks({"coinflip":7})
            for _ in range(3):tracker.record("coinflip","loss")
            gamble_session.save_state("42",tracker.snapshot(),path)
            state=gamble_session.read_state("42",path)
            restored=gamble_session.Streaks({g:v["best"] for g,v in state.items()},{g:v["current"] for g,v in state.items()})
            self.assertEqual(restored.snapshot()["coinflip"],{"current":3,"best":7})
            restored.reset_current()
            gamble_session.save_state("42",restored.snapshot(),path)
            self.assertEqual(gamble_session.read_state("42",path)["coinflip"],{"current":0,"best":7})

    def test_streaks_are_per_game_and_reset_preserves_best(self):
        tracker=gamble_session.Streaks()
        for _ in range(3):tracker.record("coinflip","loss")
        tracker.record("coinflip","tie")
        self.assertEqual(tracker.current["coinflip"],3)
        tracker.record("slots","loss")
        tracker.record("coinflip","win")
        self.assertEqual(tracker.current["coinflip"],0)
        self.assertEqual(tracker.best["coinflip"],3)
        tracker.reset_current()
        self.assertEqual(tracker.best["slots"],1)
        self.assertTrue(all(value==0 for value in tracker.current.values()))

    def test_best_records_survive_restart_and_are_scoped_to_account(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"streaks.sqlite"
            gamble_session.save_best("42","blackjack",7,path)
            gamble_session.save_best("42","blackjack",2,path)
            self.assertEqual(gamble_session.read_best("42",path),{"blackjack":7})
            self.assertEqual(gamble_session.read_best("43",path),{})
            tracker=gamble_session.Streaks(gamble_session.read_best("42",path))
            self.assertEqual(tracker.snapshot()["blackjack"],{"current":0,"best":7})


class ResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_disk_failure_does_not_leave_a_partially_reset_session(self):
        tracker = gamble_session.Streaks({"slots": 4}, {"slots": 3})
        slots = NS(turns_lost=3, exceeded_max_amount=False, gamble_flags={"amount_exceeded": True})
        bot = NS(stats=NS(gain_or_lose=-5500), gamble_streaks=tracker, user=NS(id=42),
                 _persist_gamble_streaks=True, _gamble_loss_latch=5500, response_guard=NS(tick=Mock()),
                 get_cog=lambda name: slots if name == "Slots" else None, log=AsyncMock())
        with patch.object(gamble_session, "save_state", side_effect=sqlite3.OperationalError("disk full")):
            result = await gamble_session.reset_session(bot)
        self.assertEqual(result["streaks"]["slots"], {"current": 0, "best": 4})
        self.assertEqual(bot.stats.gain_or_lose, 0)
        self.assertEqual(slots.turns_lost, 0)
        self.assertFalse(slots.gamble_flags["amount_exceeded"])
        self.assertIsNone(bot._gamble_loss_latch)
        bot.log.assert_awaited_once()

    async def test_coinflip_rechecks_balance_after_cash_refresh_and_reset(self):
        config = {**bot_control.DEFAULTS, "coinflipEnabled": True, "coinflipBet": 450,
                  "coinflipDoubleOnLoss": True, "coinflipBonusOnLoss": True, "coinflipSide": "tails"}
        bot = NS(
            alias={"coinflip": {"normal": "cf"}},
            stats=NS(balance=8542, has_updated_balance=True, gain_or_lose=450),
            settings_dict=NS(gamble=NS(goals=NS(amount=30000), allottedAmount=20000),
                             cooldowns=NS(briefCooldown=[1, 2], moderateCooldown=[70, 200])),
            gamble_streaks=gamble_session.Streaks(), response_guard=NS(tick=Mock()),
            ch=NS(put_queue=AsyncMock()), sleep_till=AsyncMock(), log=AsyncMock(),
        )
        cog = Coinflip(bot)
        cog.turns_lost = 4
        bot.get_cog = lambda name: cog if name == "Coinflip" else None

        async def update_session(delay):
            self.assertEqual(delay, 0.5)
            bot.ch.put_queue.assert_not_awaited()
            if sleep.await_count == 1:
                bot.stats.balance = 8422  # The fresh balance still cannot cover the escalated bet.
            else:
                self.assertEqual(sleep.await_count, 2)
                await gamble_session.reset_session(bot)

        with patch.object(bot_control, "get_settings", return_value=config), \
                patch("core.cogs.coinflip.notify"), patch("asyncio.sleep", side_effect=update_session) as sleep:
            await cog.start_cf(startup=True)

        self.assertEqual(sleep.await_count, 2)
        self.assertEqual(cog.turns_lost, 0)
        bot.ch.put_queue.assert_awaited_once()
        self.assertEqual(bot.ch.put_queue.await_args.args[0]["cmd_arguments"], "450 tails")

    async def test_reset_clears_profit_and_doubling_but_keeps_balance_records_and_guards(self):
        old_running=bot_control.is_running()
        self.addCleanup(bot_control.set_running,old_running)
        bot_control.set_running(False)
        tracker=gamble_session.Streaks()
        for _ in range(3):tracker.record("blackjack","loss")
        cog=NS(turns_lost=3,exceeded_max_amount=False,gamble_flags={"goal_reached":True,"amount_exceeded":True})
        gate=GamblePacing(clock=lambda:100)
        gate.finish("blackjack",123)
        guard=NS(tick=Mock(),captcha=True)
        bot=NS(stats=NS(gain_or_lose=-10000,balance=55555),_gamble_loss_latch=10000,
               gamble_streaks=tracker,gamble_pacing=gate,response_guard=guard,
               get_cog=lambda name:cog if name=="Blackjack" else None)
        settings=bot_control.get_settings()
        result=await gamble_session.reset_session(bot)
        self.assertEqual(result["profit"],0)
        self.assertIsNone(bot._gamble_loss_latch)
        self.assertEqual(bot.stats.balance,55555)
        self.assertEqual(cog.turns_lost,0)
        self.assertEqual(result["streaks"]["blackjack"],{"current":0,"best":3})
        self.assertTrue(guard.captcha)
        self.assertFalse(bot_control.is_running())
        self.assertEqual(gate.remaining("blackjack"),10)
        self.assertFalse(gate.finish("blackjack",123))
        self.assertEqual(bot_control.get_settings(),settings)


class ResetApiTests(unittest.TestCase):
    def test_reset_requests_are_account_scoped_and_idempotent(self):
        future=Future();future.set_result({"profit":0})
        data={"accountId":"42","requestId":"test-reset-1234"}
        with patch.object(gamble_session,"_handlers",{"42":("loop",lambda:"operation")}),patch.object(gamble_session,"_requests",{}),patch("asyncio.run_coroutine_threadsafe",return_value=future) as run:
            self.assertEqual(gamble_session.submit_reset(data),{"profit":0})
            self.assertEqual(gamble_session.submit_reset(data),{"profit":0})
            run.assert_called_once_with("operation","loop")
            with self.assertRaises(ValueError):gamble_session.submit_reset({**data,"accountId":"43"})
            with self.assertRaises(ValueError):gamble_session.submit_reset({"accountId":"42"})

    def test_reset_api_requires_login_and_does_not_accept_arbitrary_actions(self):
        old=website.password;website.password="test"
        self.addCleanup(setattr,website,"password",old)
        client=website.app.test_client()
        with patch.object(gamble_session,"submit_reset",return_value={"profit":0,"streaks":{}}) as submit:
            self.assertEqual(client.post("/api/gamble/reset",json={}, environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code,403)
            submit.assert_not_called()
            response=client.post("/api/gamble/reset",json={"accountId":"42","requestId":"test-reset-1234"},headers={"password":"test"})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json["profit"],0)
