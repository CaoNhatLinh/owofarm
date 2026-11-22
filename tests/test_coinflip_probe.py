import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, AsyncMock, Mock

from utils import bot_control
from utils.coinflip_probe import ProbePlan, matching_pending, complete_result, is_probe_result
from utils.gambling_control import refresh_message_bet
from utils.gamble_pacing import GamblePacing
from core.cogs.coinflip import Coinflip
from test_weapons_runtime import make_bot


class ProbeTests(unittest.TestCase):
    def test_same_face_trials_stay_one_until_loss_then_use_main_stake(self):
        cog=NS(turns_lost=1,exceeded_max_amount=False)
        gamble=NS(**{g:NS(startValue=200,multiplier=2) for g in ("coinflip","slots","blackjack")})
        bot=NS(settings_dict=NS(prefix="o",gamble=gamble),stats=NS(gain_or_lose=0),alias={},get_cog=lambda _:cog)
        config={**bot_control.DEFAULTS,"coinflipSide":"probe_loss","coinflipProbeTarget":"heads"}
        trial="Player spent **<:cowoncy:123> 1** and chose **heads**"
        with patch.object(bot_control,"get_settings",return_value=config):
            for _ in range(3):
                self.assertEqual(refresh_message_bet(bot,"ocf 400 heads"),"ocf 1 heads")
                bot._coinflip_pending=bot._coinflip_prepared
                complete_result(bot,trial,"win")
            self.assertEqual(refresh_message_bet(bot,"ocf 400 heads"),"ocf 1 heads")
            bot._coinflip_pending=bot._coinflip_prepared
            complete_result(bot,trial,"loss")
            self.assertEqual(refresh_message_bet(bot,"ocf 1 heads"),"ocf 400 heads")
            self.assertFalse(bot._coinflip_prepared["probe"])
            bot._coinflip_pending=bot._coinflip_prepared
            complete_result(bot,trial.replace(' 1**',' 400**'),"loss")
            cog.turns_lost=2
            self.assertEqual(refresh_message_bet(bot,"ocf 800 heads"),"ocf 1 heads")

    def test_win_switch_loss_stays_for_both_starting_sides(self):
        for start,other in (("heads","tails"),("tails","heads")):
            p=ProbePlan("win_switch",start)
            p.complete(False)
            self.assertEqual(p.snapshot(),dict(phase="wager",side=start))
            p.complete(True)
            self.assertEqual(p.side,other)
            p.complete(False)
            self.assertEqual(p.side,other)
            p.complete(True)
            self.assertEqual(p.side,start)

    def test_switch_mode_uses_main_stake_and_updates_only_matched_result(self):
        cog=NS(turns_lost=0,exceeded_max_amount=False)
        gamble=NS(**{g:NS(startValue=200,multiplier=2) for g in ("coinflip","slots","blackjack")})
        bot=NS(settings_dict=NS(prefix="o",gamble=gamble),stats=NS(gain_or_lose=0),alias={},get_cog=lambda _:cog)
        config={**bot_control.DEFAULTS,"coinflipSide":"win_switch","coinflipSwitchStart":"heads"}
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertEqual(refresh_message_bet(bot,"ocf 1 tails"),"ocf 200 heads")
            self.assertFalse(bot._coinflip_prepared["probe"])
            bot._coinflip_pending=bot._coinflip_prepared
            complete_result(bot,"Player spent **<:cowoncy:123> 200** and chose **heads** and you won","win")
            self.assertEqual(refresh_message_bet(bot,"ocf 200 heads"),"ocf 200 tails")
            bot._coinflip_pending=bot._coinflip_prepared
            complete_result(bot,"Player spent **<:cowoncy:123> 200** and chose **tails** and you lost it all... :c","loss")
            cog.turns_lost=1
            self.assertEqual(refresh_message_bet(bot,"ocf 200 heads"),"ocf 400 tails")

    def test_until_loss_keeps_probing_then_main_and_returns_to_probe(self):
        for target,trial in (("heads","heads"),("tails","tails")):
            p=ProbePlan("until_loss",target)
            for _ in range(4):
                p.complete(True)
                self.assertEqual(p.snapshot(),dict(phase="probe",side=trial))
            p.complete(False)
            self.assertEqual(p.snapshot(),dict(phase="wager",side=target))
            p.complete(False)
            self.assertEqual(p.snapshot(),dict(phase="probe",side=trial))

    def test_target_change_cannot_finish_old_probe_into_new_plan(self):
        cog=NS(turns_lost=0,exceeded_max_amount=False)
        gamble=NS(**{g:NS(startValue=200,multiplier=2) for g in ("coinflip","slots","blackjack")})
        bot=NS(settings_dict=NS(prefix="o",gamble=gamble),stats=NS(gain_or_lose=0),alias={},get_cog=lambda _:cog)
        config={**bot_control.DEFAULTS,"coinflipSide":"probe_loss","coinflipProbeTarget":"heads"}
        with patch.object(bot_control,"get_settings",return_value=config):
            self.assertEqual(refresh_message_bet(bot,"ocf 200 heads"),"ocf 1 heads")
            bot._coinflip_pending=bot._coinflip_prepared
            config["coinflipProbeTarget"]="tails"
            self.assertEqual(refresh_message_bet(bot,"ocf 200 tails"),"ocf 1 tails")
            complete_result(bot,"Player spent **<:cowoncy:123> 1** and chose **heads** and you lost it all... :c","loss")
            self.assertEqual(bot.coinflip_probe.snapshot(),dict(phase="probe",side="tails"))

    def test_win_inverts_random_choice_loss_keeps_it_then_main_resets(self):
        p=ProbePlan();p.complete(True,choose=lambda:"heads")
        self.assertEqual(p.snapshot(),dict(phase="wager",side="tails"))
        p.complete(False)
        self.assertEqual(p.phase,"probe")
        p.complete(False,choose=lambda:"heads")
        self.assertEqual(p.side,"heads")

    def test_send_plan_retries_and_late_mode_change(self):
        cog=NS(turns_lost=2,exceeded_max_amount=False)
        gamble=NS(**{g:NS(startValue=200,multiplier=2) for g in ("coinflip","slots","blackjack")})
        bot=NS(settings_dict=NS(prefix="o",gamble=gamble),stats=NS(gain_or_lose=0),alias={},get_cog=lambda _:cog)
        config={**bot_control.DEFAULTS,"coinflipSide":"probe"}
        content="Player spent **<:cowoncy:123> 1** and chose **heads** and you lost it all... :c"
        with patch.object(bot_control,"get_settings",return_value=config),patch("utils.coinflip_probe.secrets.choice",return_value="tails"):
            self.assertEqual(refresh_message_bet(bot,"ocf 800 tails"),"ocf 1 heads")
            bot._coinflip_pending=bot._coinflip_prepared
            self.assertTrue(is_probe_result(bot,content))
            self.assertFalse(matching_pending(bot,content.replace(' 1**',' 2**')))
            complete_result(bot,content,"loss")
            self.assertEqual(refresh_message_bet(bot,"ocf 1 heads"),"ocf 800 tails")
            self.assertEqual(cog.turns_lost,2)
            config["coinflipSide"]="heads"
            self.assertEqual(refresh_message_bet(bot,"ocf 800 tails"),"ocf 800 heads")
            self.assertEqual(bot.coinflip_probe.phase,"probe")


class ProbeRoundTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_loss_costs_one_but_does_not_raise_main_stake(self):
        bot=make_bot();bot.user=NS(id=42,name="player")
        bot.channel_id=99;bot.get_nick=lambda _:"player"
        bot.alias={"coinflip":{"normal":"cf"}}
        bot.gamble_pacing=GamblePacing();bot.update_cash=Mock();bot.log=AsyncMock()
        bot.stats=NS(gain_or_lose=0);bot.db=NS(update_gamble_db=Mock())
        bot._coinflip_active_mode="probe";bot._coinflip_pending=dict(mode="probe",probe=True,side="heads",stake=1)
        cog=Coinflip(bot);cog.turns_lost=2;cog.start_cf=AsyncMock()
        message=NS(id=123,author=NS(id=408785106942164992),channel=NS(id=99),content="player spent **<:cowoncy:123> 1** and chose **heads** and you lost it all... :c")
        config={**bot_control.DEFAULTS,"coinflipEnabled":True,"coinflipSide":"probe"}
        with patch.object(bot_control,"get_settings",return_value=config):
            await cog.on_message_edit(message,message)
            await cog.on_message_edit(message,message)
        self.assertEqual(cog.turns_lost,2)
        self.assertEqual(bot.stats.gain_or_lose,-1)
        bot.update_cash.assert_called_once_with(1,reduce=True)
        cog.start_cf.assert_awaited_once()
        self.assertEqual(bot.coinflip_probe.phase,"wager")
