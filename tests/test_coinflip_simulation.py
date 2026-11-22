import unittest
from unittest.mock import patch

from utils import coinflip_history, bot_control
from utils.coinflip_simulation import compare, generator_base
from website import website


def inputs(**changes):
    return {**dict(accountId="123", capital=1000000, base=10, warmupPercent=0, goal=None, lossLimit=None), **changes}


def rows(landings):
    return [(str(i),"heads","win" if side=="h" else "loss") for i,side in enumerate(landings)]


class SimulationTests(unittest.TestCase):
    def result(self, landings, variant, **changes):
        return next(r for r in compare(rows(landings), inputs(**changes))["results"] if r["id"]==variant)

    def test_fixed_and_doubling_exact_profit_drawdown(self):
        fixed=self.result("tth","heads-fixed")
        doubled=self.result("tth","heads-double")
        self.assertEqual(fixed["profit"],-10)
        self.assertEqual(doubled["profit"],10)
        self.assertEqual(doubled["maxDrawdown"],30)
        self.assertEqual(doubled["maxStake"],40)
        self.assertEqual(doubled["maxLossStreak"],2)

    def test_cap_capital_stop_loss_and_goal(self):
        self.assertEqual(self.result("tttttt","heads-double",base=10000)["stop"],"bet_cap")
        poor=self.result("tttt","heads-double",capital=25)
        self.assertEqual((poor["played"],poor["profit"],poor["stop"]),(1,-10,"capital"))
        limit=self.result("tttt","heads-double",lossLimit=30)
        self.assertEqual((limit["played"],limit["profit"],limit["stop"]),(2,-30,"loss_limit"))
        goal=self.result("hhhh","heads-fixed",goal=20)
        self.assertEqual((goal["played"],goal["profit"],goal["stop"]),(2,20,"goal"))

    def test_no_future_leak_and_inputs_untouched(self):
        source=rows("ththtt"*10);original=list(source)
        data=inputs(warmupPercent=20)
        first=compare(source,data)
        altered=source[:-1]+[(source[-1][0],"tails","win")]
        second=compare(altered,data)
        for a in first["results"]:
            b=next(r for r in second["results"] if r["id"]==a["id"])
            self.assertEqual(a["curve"][:-1],b["curve"][:-1])
        self.assertEqual(source,original)
        self.assertEqual(first["warmup"],12)
        self.assertEqual(first["tested"],48)
        self.assertEqual(len(first["results"]),20)
        self.assertEqual(first["results"],sorted(first["results"],key=lambda r:(r["played"]==0,-r["profit"],r["maxDrawdown"],r["id"])))

    def test_probe_costs_and_generator_tiers_are_not_fake_accuracy(self):
        probe=self.result("hh","probe-fixed")
        # Seed 42 chooses Heads; a winning Heads probe flips this to Tails.
        self.assertEqual((probe["profit"],probe["probes"],probe["played"]),(-9,1,2))
        self.assertEqual(generator_base(999999),204800)
        self.assertEqual(generator_base(1000000),409600)
        invalid=self.result("hh","generatorHeads-double")
        self.assertEqual((invalid["stop"],invalid["played"],invalid["applicable"]),("bet_cap",0,False))

    def test_probe_until_loss_counts_repeated_trials_and_main_progression(self):
        for landings,mode in (("hhth","probeLossHeads-fixed"),("ttht","probeLossTails-fixed")):
            r=self.result(landings,mode)
            self.assertEqual((r["profit"],r["probes"],r["played"],r["maxStake"]),(11,3,4,10))
        r=self.result("tthhth","probeLossHeads-double")
        self.assertEqual((r["profit"],r["probes"],r["maxStake"]),(10,4,20))

    def test_switch_after_win_stay_after_loss_has_no_probe(self):
        for landings,mode in (("hhth","switchHeads"),("ttht","switchTails")):
            fixed=self.result(landings,mode+"-fixed")
            doubled=self.result(landings,mode+"-double")
            self.assertEqual((fixed["profit"],fixed["probes"],fixed["played"]),(20,0,4))
            self.assertEqual((doubled["profit"],doubled["maxStake"]),(30,20))

    def test_rejects_invalid_amounts_and_short_history(self):
        for key,value in [("base",0),("base",250001),("base",True),("capital",-1),("warmupPercent",81),("goal",0),("lossLimit",False)]:
            with self.assertRaises(ValueError):compare(rows("hh"),inputs(**{key:value}))
        with self.assertRaises(ValueError):compare(rows("h"),inputs())


class SimulationApiTests(unittest.TestCase):
    def test_authenticated_read_only_replay(self):
        client=website.app.test_client()
        with patch.object(website,"password","test"):
            self.assertEqual(client.post("/api/gamble/simulate",json=inputs(), environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code,403)
            with patch.object(bot_control,"get_runtimes",return_value=[dict(accountId="123")]),patch.object(coinflip_history,"load",return_value=coinflip_history.History(rows("thth"))),patch.object(bot_control,"update_settings") as save:
                response=client.post("/api/gamble/simulate",json=inputs(),headers={"password":"test"})
                self.assertEqual(response.status_code,200)
                self.assertEqual(len(response.json["results"]),20)
                save.assert_not_called()
            with patch.object(bot_control,"get_runtimes",return_value=[]):
                self.assertEqual(client.post("/api/gamble/simulate",json=inputs(),headers={"password":"test"}).status_code,400)
