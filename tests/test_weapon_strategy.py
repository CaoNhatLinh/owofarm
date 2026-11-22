import unittest
from unittest.mock import AsyncMock

from test_weapons_runtime import make_bot, team_text
from core.cogs.weapons import Weapons
from utils.weapon_equipment import TeamSlot
from utils.weapon_strategy import Gear, first_zoo_pet, parse_gear, team_stats, plan_equipment


EMPTY = [TeamSlot(1, True, None), TeamSlot(2, False, None), TeamSlot(3, False, None)]


def row(wid, quality, name="Bow", extra=""):
    return f"`{wid}` **{name}** {quality}%{extra}"


class StrategyTests(unittest.TestCase):
    def test_first_pet_in_display_order_ignores_zero_and_header(self):
        self.assertEqual(first_zoo_pet("Player's zoo!\n:cat2:⁰ :dog2:² :cow2:⁹"), "dog")
        self.assertEqual(first_zoo_pet(":cow2:₀ :pig2:₁₀ :dog2:₅"), "pig")
        self.assertIsNone(first_zoo_pet(":dog2:⁰ :cat2:⁰"))

    def test_all_rarities_and_protections(self):
        gear = parse_gear(row("A1", 98, extra=" ➤ :dog2:") + "\n" + row("B1", 15, extra=" ⭐"))
        self.assertTrue(gear[0].equipped)
        self.assertTrue(gear[1].favorite)
        self.assertIsNone(parse_gear(row("A1", 98) + "\n" + row("A1", 12)))
        self.assertIsNone(parse_gear(row("A1", 120)))
        self.assertIsNone(parse_gear("`A1` <:common:123> **Bow** 99%"))

    def test_roles_beat_quality_and_do_not_reuse_weapon(self):
        slots = [TeamSlot(1, True, None), TeamSlot(2, True, None), TeamSlot(3, False, None)]
        stats = {1: dict(hp=500, wp=500, att=300, mag=40, pr=30, mr=30),
                 2: dict(hp=500, wp=500, att=40, mag=300, pr=30, mr=30)}
        gear = [Gear("A1", "Bow", 20), Gear("B1", "Spirit Staff", 95), Gear("C1", "Bow", 10)]
        self.assertEqual(plan_equipment(slots, stats, gear), {1: "A1", 2: "B1"})

    def test_unknown_current_and_other_team_equipment_are_protected(self):
        slots = [TeamSlot(1, True, "A1")]
        stats = {1: dict(hp=500, wp=500, att=300, mag=40, pr=30, mr=30)}
        self.assertEqual(plan_equipment(slots, stats, [Gear("A1", "Unknown Rune", 1, True), Gear("B1", "Bow", 99)]), {1: "A1"})
        self.assertEqual(plan_equipment([TeamSlot(1, True, None)], stats, [Gear("B1", "Bow", 99, True)]), {1: None})

    def test_stats_read_str_and_zero_wp(self):
        values = team_stats(team_text())[1]
        self.assertEqual(values["att"], 103)
        self.assertEqual(values["wp"], 0)


class NewRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = make_bot()
        self.bot.settings_dict.autoWeapons.bootstrapFirstPet = True
        self.bot.settings_dict.autoWeapons.strategy = "roles"
        self.bot.settings_dict.autoWeapons.sellSurplus = True
        self.cog = Weapons(self.bot)

    async def test_bootstrap_only_first_pet_then_confirm_team(self):
        self.cog._request_response = AsyncMock(side_effect=[
            (None, "Player, Create one with `owo team add {animal}`"),
            (None, "Player's zoo! :cat2:⁰ :dog2:² :cow2:³"),
            (None, "Player, added dog to team"), (None, team_text()),
        ])
        slots = await self.cog._fetch_team()
        self.assertEqual(slots, EMPTY)
        self.assertEqual(self.cog._request_response.await_args_list[2].args, ("team_add", "team", "add dog 1"))
        self.assertEqual(self.cog._request_response.await_count, 4)

    async def test_existing_team_is_not_replaced(self):
        self.cog._request_response = AsyncMock(return_value=(None, team_text()))
        self.assertEqual(await self.cog._fetch_team(), EMPTY)
        self.assertEqual(self.cog._request_response.await_count, 1)

    async def test_empty_zoo_does_not_add_and_can_retry_after_hunt(self):
        self.cog._request_response = AsyncMock(side_effect=[
            (None, "Player, Create one with `owo team add {animal}`"), (None, "Player's zoo! :dog2:⁰")])
        self.assertIsNone(await self.cog._fetch_team())
        self.assertFalse(self.cog._bootstrap_attempted)
        self.assertEqual(self.cog._request_response.await_count, 2)

    async def test_failed_equip_never_sells(self):
        self.cog._full_inventory = AsyncMock(return_value=[Gear("A1", "Bow", 20), Gear("B1", "Bow", 12)])
        self.cog._fetch_team = AsyncMock(return_value=EMPTY)
        self.cog._team_text = team_text()
        self.cog._request_response = AsyncMock(return_value=None)
        await self.cog._manage_roles(EMPTY)
        self.assertEqual(self.cog._request_response.await_args.args, ("equip", "weapon", "A1 1"))
        self.assertEqual(self.cog._request_response.await_count, 1)

    async def test_sell_only_common_uncommon_after_confirmed_equip(self):
        equipped = [TeamSlot(1, True, "A1"), *EMPTY[1:]]
        gear = [Gear("A1", "Bow", 100, True), Gear("B1", "Bow", 12),
                Gear("C1", "Bow", 60), Gear("D1", "Bow", 30, favorite=True),
                Gear("E1", "Unknown Rune", 12), Gear("F1", "Bow", 15, True)]
        self.cog._full_inventory = AsyncMock(return_value=gear)
        self.cog._fetch_team = AsyncMock(return_value=equipped)
        self.cog._team_text = team_text("A1")
        self.cog._request_response = AsyncMock(return_value=(None, "Player, You sold a(n) **Common Bow** for 100 cowoncy!"))
        await self.cog._manage_roles(equipped)
        self.cog._request_response.assert_awaited_once_with("weapon_sell", "sell", "B1")

    async def test_partial_team_or_inventory_never_drives_sale(self):
        self.cog._full_inventory = AsyncMock()
        await self.cog._manage_roles(EMPTY[:1])
        self.cog._full_inventory.assert_not_awaited()
        self.cog._request_response = AsyncMock(return_value=(None, "Player's weapons\n" + row("A1", 12) + "\nPage 1/2 | Sorting by rarity"))
        self.cog._next_page = AsyncMock(return_value=None)
        self.assertIsNone(await Weapons._full_inventory(self.cog))

    async def test_filtered_inventory_is_rejected(self):
        self.cog._request_response = AsyncMock(return_value=(None, "Player's weapons\n**Weapon Filters:** `Bow`\n" + row("A1", 12) + "\nPage 1/1 | Sorting by rarity"))
        self.assertIsNone(await self.cog._full_inventory())


if __name__ == "__main__":
    unittest.main()
