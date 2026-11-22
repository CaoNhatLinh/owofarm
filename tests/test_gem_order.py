import unittest
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import patch

from core.cogs.gems import Gems, gem_tiers


class GemOrderTests(unittest.TestCase):
    def setUp(self):
        self.settings = NS(tiers={tier: True for tier in gem_tiers},
            gemsToUse=dict(huntGem=True, empoweredGem=True, luckyGem=True, specialGem=True),
            dynamicSpecialGem=False, useLowest=True)
        bot = NS(settings_dict=NS(autoUse=NS(gems=self.settings)),
            alias={name:{"normal":name} for name in ("use","inv")})
        self.cog = Gems(bot)
        self.stock = {tier:{gem:0 for gem in ids} for tier,ids in gem_tiers.items()}

    def choose(self, order):
        with patch("utils.bot_control.get_settings",return_value={"gemOrder":order}):
            return self.cog.find_gems_to_use(self.stock)

    def test_lowest_first_is_per_type_even_with_mixed_tier_stock(self):
        self.stock["common"]["051"] = 1
        self.stock["epic"].update({"054":10,"068":5,"075":5})
        self.stock["fabled"]["085"] = 1
        self.assertEqual(self.choose("low_to_high"),["051","068","075","085"])

    def test_highest_first_does_not_select_duplicate_types(self):
        for tier in self.stock:
            self.stock[tier] = {gem:2 for gem in self.stock[tier]}
        self.assertEqual(self.choose("high_to_low"),["057","071","078","085"])
        self.assertEqual(self.choose("low_to_high"),["051","065","072","079"])

    def test_disabled_tiers_and_types_are_preserved(self):
        self.stock["fabled"].update({"057":3,"071":3})
        self.stock["legendary"].update({"056":2,"070":2})
        self.settings.tiers["fabled"] = False
        self.settings.gemsToUse["empoweredGem"] = False
        self.assertEqual(self.choose("high_to_low"),["056"])

    def test_active_gem_type_is_not_replaced_or_inventory_mutated(self):
        self.stock["common"].update({"051":2,"065":2})
        self.stock["fabled"].update({"057":2,"071":2})
        before = deepcopy(self.stock)
        with patch("utils.bot_control.get_settings",return_value={"gemOrder":"high_to_low"}):
            result = self.cog.find_specific_gems_to_use([{"gem_type":"huntGem","gem_tier":"common"}],self.stock)
        self.assertEqual(result,["071"])
        self.assertEqual(self.stock,before)

    def test_empty_inventory_never_selects_zero_count_gems(self):
        self.assertIsNone(self.choose("high_to_low"))
        self.assertIsNone(self.choose("low_to_high"))

    def test_special_gem_event_rule_still_applies(self):
        self.stock["fabled"]["085"] = 5
        self.settings.dynamicSpecialGem = True
        self.cog.bot.ongoing_owobot_event = False
        self.assertIsNone(self.choose("high_to_low"))


if __name__ == "__main__": unittest.main()
