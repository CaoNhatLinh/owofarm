import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from utils import bot_control
from utils import gambling_control as control
from website import website
from test_weapons_runtime import make_bot


class GamblingTests(unittest.IsolatedAsyncioTestCase):
    async def test_loss_boundary_and_next_bet_budget(self):
        bot=NS(stats=NS(gain_or_lose=-500))
        config={**bot_control.DEFAULTS,"gambleLossAmount":1000}
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertFalse(control.loss_blocked(bot,500))
            self.assertTrue(control.loss_blocked(bot,501))
            bot.stats.gain_or_lose=-1000
            self.assertTrue(control.loss_blocked(bot))

    async def test_loss_stop_stays_latched_until_user_changes_limit(self):
        bot=NS(stats=NS(gain_or_lose=-1000))
        config={**bot_control.DEFAULTS,"gambleLossAmount":1000}
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertTrue(control.loss_blocked(bot))
            bot.stats.gain_or_lose=100
            self.assertTrue(control.loss_blocked(bot))
            config["gambleLossAmount"]=2000
            self.assertFalse(control.loss_blocked(bot))
            bot.stats.gain_or_lose=-2000
            self.assertTrue(control.loss_blocked(bot))
            config["gambleLossEnabled"]=False
            self.assertFalse(control.loss_blocked(bot,100000))

    async def test_raising_loss_limit_releases_wait(self):
        class Cog(control.GamblingLifecycle): pass
        cog=Cog();cog.cmd={"id":"coinflip"};cog.turns_lost=0
        cog.bot=NS(stats=NS(gain_or_lose=-1000))
        config={**bot_control.DEFAULTS,"coinflipEnabled":True,"gambleLossAmount":1000}
        async def raise_limit(delay):config["gambleLossAmount"]=5000
        with patch.object(bot_control,"get_settings",return_value=config),patch("asyncio.sleep",side_effect=raise_limit) as sleep:
            await cog.wait_for_loss_limit()
            sleep.assert_awaited_once()

    async def test_loss_limit_blocks_all_games_but_keeps_farm_commands(self):
        gamble=NS(**{g:NS(enabled=True,startValue=200,multiplier=2) for g in control.GAMES})
        bot=NS(stats=NS(gain_or_lose=-1000),settings_dict=NS(prefix="o",gamble=gamble),alias={},get_cog=lambda _:None)
        config={**bot_control.DEFAULTS,"gambleLossAmount":1000}
        with patch.object(bot_control,"get_settings",return_value=config):
            for command in ("ocf 200","oslots 200","obj 200"):
                self.assertIsNone(control.refresh_message_bet(bot,command))
            self.assertEqual(control.refresh_message_bet(bot,"oh"),"oh")

    async def test_goal_uses_profit_and_stops_at_exact_target(self):
        bot=NS(stats=NS(gain_or_lose=30000,balance=100000))
        config={**bot_control.DEFAULTS}
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertTrue(control.goal_reached(bot))
            config["gambleGoalAmount"]=50000
            self.assertFalse(control.goal_reached(bot))
            config["gambleGoalAmount"]=1
            config["gambleGoalEnabled"]=False
            self.assertFalse(control.goal_reached(bot))

    async def test_changing_goal_releases_wait_without_restart(self):
        class Cog(control.GamblingLifecycle): pass
        cog=Cog();cog.cmd={"id":"blackjack"};cog.bot=NS(stats=NS(gain_or_lose=30000))
        config={**bot_control.DEFAULTS,"blackjackEnabled":True}
        async def raise_goal(delay):config["gambleGoalAmount"]=50000
        with patch.object(bot_control,"get_settings",return_value=config), patch("asyncio.sleep",side_effect=raise_goal) as sleep:
            await cog.wait_for_profit_goal()
            sleep.assert_awaited_once()
            self.assertFalse(cog.profit_goal_reached())

    async def test_blackjack_goal_profit_excludes_returned_stake(self):
        self.assertEqual(control.blackjack_profit("you bet **4,000** to play blackjack",8000,200),4000)
        self.assertEqual(control.blackjack_profit("you bet <:cowoncy:1234> **200** to play blackjack",400,100),200)
        self.assertEqual(control.blackjack_profit("",400,200),200)

    async def test_amounts_and_doubling_are_independent_for_each_game(self):
        config = {**bot_control.DEFAULTS, "coinflipBet":50, "slotsBet":75,
                  "slotsDoubleOnLoss":False, "blackjackBet":100}
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertEqual([control.bet_amount("coinflip", i) for i in range(3)], [50,100,200])
            self.assertEqual(control.bet_amount("slots", 10), 75)
            self.assertEqual(control.bet_amount("blackjack", 2), 400)
            self.assertEqual(control.bet_amount("coinflip", 0), 50)

    async def test_changed_bet_resets_streak_and_refreshes_dequeued_command(self):
        config = {**bot_control.DEFAULTS,"coinflipEnabled":True,"coinflipBet":50,"coinflipDoubleOnLoss":False}
        cog = NS(turns_lost=4, exceeded_max_amount=True)
        gamble = NS(**{g:NS(enabled=False,startValue=200,multiplier=2) for g in control.GAMES})
        bot = NS(stats=NS(gain_or_lose=0),settings_dict=NS(prefix="owo ",gamble=gamble),alias={},get_cog=lambda name:cog if name=="Coinflip" else None)
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertEqual(control.refresh_message_bet(bot,"owo cf 3200 t"),"owo cf 50 heads")
            self.assertEqual(cog.turns_lost,0)
            self.assertFalse(cog.exceeded_max_amount)
            self.assertEqual(gamble.coinflip.multiplier,1)
            cog.turns_lost = 3
            self.assertEqual(control.refresh_message_bet(bot,"owo cf 3200"),"owo cf 50 heads")
            config["coinflipDoubleOnLoss"] = True
            self.assertEqual(control.refresh_message_bet(bot,"owo cf 3200"),"owo cf 50 heads")
            cog.turns_lost = 2
            self.assertEqual(control.refresh_message_bet(bot,"owo cf 50"),"owo cf 200 heads")
            config["coinflipSide"] = "tails"
            self.assertEqual(control.refresh_message_bet(bot,"owo cf 50 heads"),"owo cf 200 tails")
            self.assertEqual(cog.turns_lost,2)
            self.assertEqual(control.refresh_message_bet(bot,"owo slots 50"),"owo slots 200")

    async def test_each_switch_loads_and_unloads_only_its_game(self):
        config = {**bot_control.DEFAULTS, "coinflipEnabled": True}
        bot = NS(settings_dict=NS(gamble=NS(**{g:NS(enabled=False) for g in control.GAMES})), extensions={})
        async def load(name): bot.extensions[name] = object()
        async def unload(name): bot.extensions.pop(name)
        bot.load_extension = AsyncMock(side_effect=load)
        bot.unload_extension = AsyncMock(side_effect=unload)
        with patch.object(bot_control, "get_settings", return_value=config):
            await control.sync(bot)
            await control.sync(bot)
            bot.load_extension.assert_awaited_once_with("core.cogs.coinflip")
            self.assertTrue(bot.settings_dict.gamble.coinflip.enabled)
            self.assertFalse(bot.settings_dict.gamble.slots.enabled)
            config["coinflipEnabled"] = False
            await control.sync(bot)
            bot.unload_extension.assert_awaited_once_with("core.cogs.coinflip")

    async def test_disable_cancels_startup_and_removes_only_game_queue(self):
        class Cog(control.GamblingLifecycle): pass
        cog = Cog(); cog.bot = make_bot(); cog.cmd = {"id":"coinflip"}
        cog.bot.ch.cmds_state["coinflip"] = {"in_queue":True}
        for index, game in enumerate(("hunt", "coinflip", "slots")):
            cog.bot.ch.queue.put_nowait((1,index,{"id":game}))
        cog.bot.ch.checks = [{"id":"coinflip"},{"id":"hunt"}]
        cog.start_gambling(asyncio.sleep(30))
        task = cog._gambling_task
        await cog.stop_gambling()
        self.assertTrue(task.cancelled())
        self.assertFalse(cog.gambling_enabled())
        self.assertEqual([cog.bot.ch.queue.get_nowait()[2]["id"] for _ in range(2)], ["hunt","slots"])
        self.assertEqual(cog.bot.ch.checks, [{"id":"hunt"}])

    async def test_command_guard_blocks_dequeued_game_after_switch_off(self):
        config = {**bot_control.DEFAULTS, "slotsEnabled":True}
        with patch.object(bot_control, "get_settings", return_value=config):
            self.assertFalse(control.command_allowed("ocf 200", "o", {}))
            self.assertFalse(control.command_allowed("owo bj 200", "owo ", {}))
            self.assertTrue(control.command_allowed("oslots 200", "o", {}))
            self.assertTrue(control.command_allowed("osell cw", "o", {}))


class GamblingWebTests(unittest.TestCase):
    def test_coinflip_history_window_validation_and_save(self):
        for size in (100,500):
            self.assertEqual(bot_control.validate_settings({"coinflipHistoryWindow":size}),{"coinflipHistoryWindow":size})
        for size in (50,0,101,100.0,"500",True,None):
            with self.assertRaises(ValueError):bot_control.validate_settings({"coinflipHistoryWindow":size})
        original=bot_control.get_settings()
        try:
            with tempfile.TemporaryDirectory() as folder, patch.object(bot_control,"SETTINGS_PATH",Path(folder)/"dashboard.json"):
                import json
                bot_control.update_settings({"coinflipHistoryWindow":100})
                saved=json.loads(bot_control.SETTINGS_PATH.read_text(encoding="utf-8"))
                self.assertEqual(bot_control.validate_settings(saved)["coinflipHistoryWindow"],100)
        finally:
            bot_control._settings.clear();bot_control._settings.update(original)

    def test_coinflip_side_validation_and_persistence(self):
        for side in ("heads", "tails", "auto", "probe", "probe_loss", "win_switch"):
            self.assertEqual(bot_control.validate_settings({"coinflipSide":side}),{"coinflipSide":side})
        for side in ("random", "h", "TAILS", "", None, True, []):
            with self.assertRaises(ValueError):bot_control.validate_settings({"coinflipSide":side})
        original=bot_control.get_settings()
        try:
            with tempfile.TemporaryDirectory() as folder, patch.object(bot_control,"SETTINGS_PATH",Path(folder)/"dashboard.json"):
                bot_control.update_settings({"coinflipSide":"tails"})
                import json
                saved=json.loads(bot_control.SETTINGS_PATH.read_text(encoding="utf-8"))
                self.assertEqual(saved["coinflipSide"],"tails")
                self.assertEqual(bot_control.validate_settings(saved)["coinflipSide"],"tails")
        finally:
            bot_control._settings.clear();bot_control._settings.update(original)

    def test_probe_target_is_validated_and_persisted(self):
        for side in ("heads","tails"):
            self.assertEqual(bot_control.validate_settings({"coinflipSwitchStart":side}),{"coinflipSwitchStart":side})
        for side in ("auto",True,None,"h"):
            with self.assertRaises(ValueError):bot_control.validate_settings({"coinflipSwitchStart":side})
        for side in ("heads","tails"):
            self.assertEqual(bot_control.validate_settings({"coinflipProbeTarget":side}),{"coinflipProbeTarget":side})
        for side in ("auto",True,None,"h"):
            with self.assertRaises(ValueError):bot_control.validate_settings({"coinflipProbeTarget":side})
        original=bot_control.get_settings()
        try:
            with tempfile.TemporaryDirectory() as folder,patch.object(bot_control,"SETTINGS_PATH",Path(folder)/"dashboard.json"):
                import json
                bot_control.update_settings({"coinflipProbeTarget":"tails"})
                self.assertEqual(json.loads(bot_control.SETTINGS_PATH.read_text())["coinflipProbeTarget"],"tails")
        finally:
            bot_control._settings.clear();bot_control._settings.update(original)

    def test_loss_limit_rejects_invalid_amounts(self):
        for amount in (0,-1,1.5,True,"1000",None,1000000000001):
            with self.assertRaises(ValueError):bot_control.validate_settings({"gambleLossAmount":amount})
        with self.assertRaises(ValueError):bot_control.validate_settings({"gambleLossEnabled":1})
    def test_goal_has_strict_validated_amount_and_switch(self):
        for amount in (0,-1,1.5,True,"30000",1000000000001):
            with self.assertRaises(ValueError):bot_control.validate_settings({"gambleGoalAmount":amount})
        self.assertEqual(bot_control.validate_settings({"gambleGoalAmount":50000,"gambleGoalEnabled":False}),
                         {"gambleGoalAmount":50000,"gambleGoalEnabled":False})

    def test_bet_validation_rejects_invalid_amounts_and_boolean_coercion(self):
        for game in control.GAMES:
            for value in (0,-1,250001,1.5,True,"200",None):
                with self.subTest(game=game,value=value), self.assertRaises(ValueError):
                    bot_control.validate_settings({game+"Bet":value})
            self.assertEqual(bot_control.validate_settings({game+"Bet":1}),{game+"Bet":1})
            with self.assertRaises(ValueError):
                bot_control.validate_settings({game+"DoubleOnLoss":1})

    def test_authenticated_switches_persist_with_strict_boolean_validation(self):
        old = website.password
        self.addCleanup(setattr, website, "password", old)
        website.password = "test"
        client = website.app.test_client()
        original = dict(bot_control._settings)
        self.addCleanup(bot_control._settings.update, original)
        with tempfile.TemporaryDirectory() as directory, patch.object(bot_control,"SETTINGS_PATH",Path(directory)/"dashboard.json"):
            data = {"coinflipEnabled":True,"slotsEnabled":False,"blackjackEnabled":True,
                    "coinflipBet":50,"slotsBet":100,"blackjackBet":75,
                    "coinflipDoubleOnLoss":False,"slotsDoubleOnLoss":True,"blackjackDoubleOnLoss":False,
                    "gambleGoalEnabled":True,"gambleGoalAmount":50000,
                    "gambleLossEnabled":True,"gambleLossAmount":5000}
            self.assertEqual(client.patch("/api/settings",json=data, environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code,403)
            response = client.patch("/api/settings",json=data,headers={"password":"test"})
            self.assertEqual(response.status_code,200)
            for key,value in data.items(): self.assertEqual(response.json["settings"][key],value)
            self.assertEqual(client.patch("/api/settings",json={"coinflipEnabled":1},headers={"password":"test"}).status_code,400)
            self.assertIn('"blackjackEnabled": true', bot_control.SETTINGS_PATH.read_text())
        html = client.get("/").data
        for game in control.GAMES:
            self.assertIn(f'id="{game}-enabled"'.encode(),html)
            self.assertIn(f'id="{game}-bet"'.encode(),html)
            self.assertIn(f'id="{game}-double"'.encode(),html)
