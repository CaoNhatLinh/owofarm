import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from utils import bot_control
from utils.coinflip_history import History, chosen_side, load, save, select_side
from utils.gambling_control import refresh_message_bet, GamblingLifecycle


class HistoryTests(unittest.TestCase):
    def test_sampling_then_smoothed_rate_and_tie(self):
        history=History()
        self.assertEqual(history.snapshot()["side"],"heads")
        history.record(1,"heads","win")
        self.assertEqual(history.snapshot()["side"],"tails")
        for i in range(2,6): history.record(i,"heads","loss")
        for i in range(6,11): history.record(i,"tails","loss" if i==6 else "win")
        result=history.snapshot()
        self.assertEqual(result["reason"],"history")
        self.assertEqual(result["side"],"tails")
        self.assertEqual(result["sides"]["heads"],dict(wins=1,losses=4,samples=5))
        tied=History([(str(i),side,"win") for i,side in enumerate(["heads","tails"]*5)])
        self.assertEqual(tied.snapshot()["side"],"heads")

    def test_duplicate_unknown_and_rolling_window(self):
        history=History()
        self.assertTrue(history.record(1,"heads","loss"))
        self.assertFalse(history.record(1,"heads","loss"))
        self.assertFalse(history.record(2,None,"win"))
        self.assertFalse(history.record(2,"tails","tie"))
        for i in range(2,512): history.record(i,"tails","win")
        self.assertEqual(history.snapshot()["total"],500)
        self.assertEqual(history.snapshot()["window"],500)
        self.assertEqual(history.snapshot()["sides"]["heads"]["samples"],0)
        self.assertEqual(history.snapshot()["side"],"heads")

    def test_actual_chosen_side_not_landed_face_or_current_setting(self):
        self.assertEqual(chosen_side("**Me** chose **tails** and the coin landed on **heads**"),"tails")
        self.assertEqual(chosen_side("Me chose **<:heads:12345> Heads**!"),"heads")
        self.assertEqual(chosen_side("Me chose `tail`"),"tails")
        self.assertIsNone(chosen_side("Coin landed on heads. You won!"))

    def test_landed_frequency_counts_opposite_side_on_loss(self):
        history=History()
        for i,side,outcome in [(1,"heads","win"),(2,"heads","loss"),(3,"tails","win"),(4,"tails","loss"),(5,"heads","loss")]:
            history.record(i,side,outcome)
        result=history.snapshot()
        self.assertEqual(result["appearances"],{"heads":2,"tails":3})
        self.assertEqual(result["mostCommon"],"tails")
        self.assertEqual(result["total"],5)
        self.assertIsNone(History().snapshot()["mostCommon"])
        history.record(6,"tails","loss")
        self.assertIsNone(history.snapshot()["mostCommon"])

    def test_recent_hundred_differs_from_five_hundred_and_rolls(self):
        history=History([(str(i),"heads" if i<400 else "tails","win") for i in range(500)])
        windows=history.snapshot()["windows"]
        self.assertEqual(windows["100"],dict(total=100,window=100,appearances={"heads":0,"tails":100},mostCommon="tails"))
        self.assertEqual(windows["500"],dict(total=500,window=500,appearances={"heads":400,"tails":100},mostCommon="heads"))
        history.record(500,"heads","win")
        windows=history.snapshot()["windows"]
        self.assertEqual(windows["100"]["appearances"],{"heads":1,"tails":99})
        self.assertEqual(windows["500"]["appearances"],{"heads":400,"tails":100})
        short=History([("1","tails","loss")]).snapshot()["windows"]
        self.assertEqual(short["100"]["total"],1)
        self.assertEqual(short["500"]["appearances"],short["100"]["appearances"])

    def test_selected_window_changes_decision_but_keeps_lock(self):
        rows=[(str(i),"heads" if i%2==0 else "tails", "win" if i%2==0 else "loss") for i in range(400)]
        rows += [(str(i),"heads" if i%2==0 else "tails", "loss" if i%2==0 else "win") for i in range(400,500)]
        history=History(rows);bot=NS(coinflip_history=history)
        config={**bot_control.DEFAULTS,"coinflipHistoryWindow":500}
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertEqual(select_side(bot,"auto"),"heads")
            config["coinflipHistoryWindow"]=100
            self.assertEqual(select_side(bot,"auto"),"tails")
            self.assertEqual(history.snapshot(100)["total"],100)
            self.assertEqual(history.snapshot(100)["window"],100)
            self.assertEqual(history.snapshot()["choices"]["100"]["side"],"tails")
            history.record(501,"heads","loss")
            for size in (100,500):
                config["coinflipHistoryWindow"]=size
                self.assertEqual(select_side(bot,"auto"),"heads")
                self.assertEqual(history.snapshot(size)["reason"],"locked")

    def test_disk_reload_isolation_dedup_and_last_five_hundred(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"history.sqlite"
            for i in range(510):save("a",i,"heads","win",path)
            save("a",509,"tails","loss",path)
            save("b",509,"tails","loss",path)
            a=load("a",path).snapshot();b=load("b",path).snapshot()
            self.assertEqual(a["total"],500)
            self.assertEqual(a["sides"]["heads"]["wins"],500)
            self.assertEqual(b["total"],1)
            self.assertEqual(b["sides"]["tails"]["losses"],1)

    def test_auto_resolves_queued_side_without_resetting_stake(self):
        cog=NS(turns_lost=2,exceeded_max_amount=False)
        bot=NS(stats=NS(gain_or_lose=0),alias={},settings_dict=NS(prefix="o",gamble=NS(**{
            game:NS(startValue=200,multiplier=2) for game in ("coinflip","slots","blackjack")})),get_cog=lambda _:cog)
        config={**bot_control.DEFAULTS,"coinflipSide":"auto"}
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertEqual(refresh_message_bet(bot,"ocf 200 tails"),"ocf 800 heads")
            bot.coinflip_history.record(1,"heads","loss")
            self.assertEqual(refresh_message_bet(bot,"ocf 200 tails"),"ocf 800 heads")
            self.assertEqual(bot.coinflip_history.snapshot()["reason"],"locked")
            bot.coinflip_history.record(2,"heads","win")
            self.assertEqual(refresh_message_bet(bot,"ocf 200 heads"),"ocf 800 tails")
            self.assertEqual(cog.turns_lost,2)
            self.assertEqual(select_side(bot,"heads"),"heads")

    def test_lock_restores_from_history_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"history.sqlite"
            save("a",1,"tails","loss",path)
            history=load("a",path)
            self.assertEqual(history.snapshot()["side"],"tails")
            self.assertEqual(history.snapshot()["reason"],"locked")
            for i in range(2,8):history.record(i,"tails","loss")
            self.assertEqual(history.snapshot()["side"],"tails")
            history.record(8,"tails","win")
            self.assertEqual(history.snapshot()["side"],"heads")
            self.assertEqual(history.snapshot()["reason"],"sampling")


class RecordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_records_actual_side_even_when_mode_changed(self):
        class Cog(GamblingLifecycle):pass
        cog=Cog();cog.cmd={"id":"coinflip"};cog.bot=NS()
        message=NS(id=123,content="Me chose **tails** and you won")
        await cog.record_gambling_result("win",message)
        result=cog.bot.coinflip_history.snapshot()
        self.assertEqual(result["sides"]["tails"]["wins"],1)
        self.assertEqual(result["sides"]["heads"]["samples"],0)
        self.assertEqual(cog.bot.gamble_streaks.current["coinflip"],0)
