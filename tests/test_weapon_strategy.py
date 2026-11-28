import unittest
from unittest.mock import AsyncMock, call, patch

from test_weapons_runtime import PET_STATS, make_bot, message, team_text
from core.cogs.weapons import Weapons
from utils.weapon_equipment import TeamSlot
from utils import bot_control
from utils.weapon_strategy import ANIMAL_RANKS, Gear, caught_team_animals, first_zoo_pet, parse_gear, team_stats, plan_equipment, zoo_animals


EMPTY = [TeamSlot(1, True, None), TeamSlot(2, False, None), TeamSlot(3, False, None)]


def row(wid, quality, name="Bow", extra=""):
    return f"`{wid}` **{name}** {quality}%{extra}"


class StrategyTests(unittest.TestCase):
    def test_first_pet_in_display_order_ignores_zero_and_header(self):
        self.assertEqual(first_zoo_pet("Player's zoo!\n:cat2:⁰ :dog2:² :cow2:⁹"), "dog")
        self.assertEqual(first_zoo_pet(":cow2:₀ :pig2:₁₀ :dog2:₅"), "pig")
        self.assertIsNone(first_zoo_pet(":dog2:⁰ :cat2:⁰"))

    def test_zoo_recognizes_unicode_and_dynamic_ranked_species(self):
        stock = zoo_animals(
            "Player's zoo!\n<:rare:77> 🐕₁₀ 🐈⁰\n<a:hidden:78> <a:futurepet:80>³\nZoo Points: 50"
        )
        self.assertEqual([(animal.key, animal.command) for animal in stock], [("dog", "dog"), ("80", "<a:futurepet:80>")])
        self.assertLess(stock[0].rank, stock[1].rank)

    def test_new_species_uses_an_explicit_catch_rank_or_remains_unranked(self):
        pet = "<a:futurepet:100>"
        self.assertEqual(caught_team_animals(f"Player spent 5 and caught a <:hidden:99> Hidden {pet}!" )[0].rank,
                         ANIMAL_RANKS["hidden"])
        self.assertEqual(caught_team_animals(f"Player, hunt is empowered by ...\nYou found: {pet}")[0].rank, 0)

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

    async def test_legacy_empty_zoo_wakes_once_after_the_first_owned_catch(self):
        header = "Player, Create one with `owo team add {animal}`"
        self.cog._request_response = AsyncMock(side_effect=[
            (None, header), (None, "Player's zoo! :dog2:⁰"),
            (None, header), (None, "Player's zoo! :dog2:¹"), (None, "Player, added dog"), (None, team_text()),
        ])
        self.cog._full_inventory = AsyncMock(return_value=[])
        with patch.object(bot_control, "get_settings", return_value={**bot_control.DEFAULTS, "teamSetupEnabled": False}):
            for instant in (100, 401):
                with patch("core.cogs.weapons.time.monotonic", return_value=instant):
                    await self.cog.check_once()
            self.assertEqual(self.cog._request_response.await_count, 2)
            await self.cog.on_message(message("Player spent 5 and caught a 🐕!"))
            with patch("core.cogs.weapons.time.monotonic", return_value=402):
                await self.cog.check_once()
        self.assertEqual(self.cog._request_response.await_args_list[4], call("team_add", "team", "add dog 1"))

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

    async def test_empty_filtered_view_is_not_confirmation_of_an_empty_inventory(self):
        self.cog._request_response = AsyncMock(return_value=(None, "Player's weapons\n**Weapon Filters:** `Bow`\nNo weapons found.\nPage 1/1"))
        self.assertIsNone(await self.cog._full_inventory())


class ScopedTeamSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {**bot_control.DEFAULTS, "teamSetupEnabled": True}
        self.enterContext(patch.object(bot_control, "get_settings", return_value=self.config))
        self.bot = make_bot()
        self.bot.settings_dict.autoWeapons.enabled = False
        self.bot.settings_dict.autoWeapons.sellSurplus = True
        self.cog = Weapons(self.bot)
        self.cog._full_inventory = AsyncMock(return_value=[])

    @staticmethod
    def roster(*animals):
        return "Player's team\n" + "\n".join(
            f"[{position}] {animal}\n{PET_STATS}" if animal else f"[{position}] none"
            for position, animal in enumerate(animals, start=1)
        )

    async def test_existing_tied_team_reads_once_and_keeps_original_slots(self):
        roster = self.roster("gfox", "gowl", "glion")
        self.cog._request_response = AsyncMock(side_effect=[
            (None, roster), (None, "Player's zoo! <a:gdeer:418290217989046274>²"),
        ])
        for instant in (100, 4001, 5001):
            with patch("core.cogs.weapons.time.monotonic", return_value=instant):
                await self.cog.check_once()
        self.assertEqual(self.cog._request_response.await_args_list, [call("team", "team"), call("zoo", "zoo")])
        self.assertTrue(self.bot._team_setup_ready)

    async def test_only_explicit_species_confirmation_and_one_stat_read_follow_team_update(self):
        before = self.roster("dog", "gowl", None)
        after = self.roster("gfox", "gowl", "glitchzebra")
        self.cog._request_response = AsyncMock(side_effect=[
            (None, before),
            (None, "Player's zoo! <a:gfox:418291892376305664>⁴ <a:glitchzebra:727735573246247045>²"),
            (None, "Player, Your team has been updated!\nYour team: [1]🐕 [2]<a:gowl:418284974593277954> [3]<a:glitchzebra:727735573246247045>"),
            (None, "Player, Your team has been updated!\nYour team: [1]<a:gfox:418291892376305664> [2]<a:gowl:418284974593277954> [3]<a:glitchzebra:727735573246247045>"),
            (None, after),
        ])
        await self.cog.check_once()
        self.assertEqual(self.cog._request_response.await_args_list, [
            call("team", "team"), call("zoo", "zoo"), call("team_add", "team", "add glitchzebra 3"),
            call("team_add", "team", "add gfox 1"), call("team", "team"),
        ])
        self.assertTrue(self.bot._team_setup_ready)

    async def test_only_a_new_upgrade_catch_triggers_a_later_team_change(self):
        roster = self.roster("gfox", "gowl", "glion")
        upgraded = self.roster("glitchzebra", "gowl", "glion")
        self.cog._request_response = AsyncMock(side_effect=[
            (None, roster), (None, "Player's zoo! <a:gdeer:418290217989046274>²"),
            (None, "Player, Your team: [1]<a:glitchzebra:727735573246247045> [2]<a:gowl:418284974593277954> [3]<a:glion:418289164736528404>"),
            (None, upgraded),
        ])
        await self.cog.check_once()
        for name, animal in (("Player", "<a:gdeer:418290217989046274>"), ("Player", "<a:gsquid:417968419984375808>"),
                             ("Player Two", "<a:glitchzebra:727735573246247045>")):
            await self.cog.on_message(message(f"🌱 | {name} spent 5 cowoncy and caught {animal}!"))
        self.assertFalse(self.cog._wake.is_set())
        await self.cog.on_message(message("🌱 | Player spent 5 cowoncy and caught <a:glitchzebra:727735573246247045>!"))
        self.assertTrue(self.cog._wake.is_set())
        self.assertFalse(self.bot._team_setup_ready)
        await self.cog.check_once()
        self.assertEqual(self.cog._request_response.await_args_list[2:], [
            call("team_add", "team", "add glitchzebra 1"), call("team", "team"),
        ])
        self.assertTrue(self.bot._team_setup_ready)

    async def test_confirmed_upgrade_retries_an_unavailable_gear_read_without_oteam(self):
        starting = self.roster("gfox", "gowl", "glion")
        upgraded = self.roster("glitchzebra", "gowl", "glion")
        self.cog._request_response = AsyncMock(side_effect=[
            (None, starting), (None, "Player's zoo!"),
            (None, "Player, Your team: [1]<a:glitchzebra:727735573246247045>"),
            (None, upgraded),
        ])
        self.cog._full_inventory = AsyncMock(side_effect=[[], None, []])
        with patch("core.cogs.weapons.time.monotonic", return_value=100):
            await self.cog.check_once()
        await self.cog.on_message(message("🌱 | Player spent 5 cowoncy and caught <a:glitchzebra:727735573246247045>!"))
        with patch("core.cogs.weapons.time.monotonic", return_value=120):
            await self.cog.check_once()
        self.assertFalse(self.bot._team_setup_ready)
        self.assertTrue(self.cog._needs_setup)
        with patch("core.cogs.weapons.time.monotonic", return_value=421):
            await self.cog.check_once()
        self.assertTrue(self.bot._team_setup_ready)
        self.assertEqual(self.cog._request_response.await_count, 4)

    async def test_unconfirmed_update_waits_for_a_manual_read_without_polling(self):
        starting = self.roster("gfox", "gowl", "glion")
        upgraded = self.roster("glitchzebra", "gowl", "glion")
        self.cog._request_response = AsyncMock(side_effect=[
            (None, starting), (None, "Player's zoo! <a:glitchzebra:727735573246247045>¹"),
            (None, "Player, Your team: [1]<a:glitchzebra:727735573246247045>"), None,
        ])
        with patch("core.cogs.weapons.time.monotonic", return_value=100):
            await self.cog.check_once()
        self.assertEqual(self.bot._team_setup_status, "waiting_confirmation")
        with patch("core.cogs.weapons.time.monotonic", return_value=401):
            await self.cog.check_once()
        self.assertEqual(self.cog._request_response.await_count, 4)
        await self.cog.on_message(message("owo team", author=42, message_id=500))
        await self.cog.on_message(message(upgraded, message_id=501))
        with patch("core.cogs.weapons.time.monotonic", return_value=402):
            await self.cog.check_once()
        self.assertTrue(self.bot._team_setup_ready)
        self.assertEqual(self.cog._request_response.await_count, 4)

    async def test_unknown_empowered_catch_has_one_zoo_rank_check_before_team_mutation(self):
        pet = "<a:futurepet:100>"
        start = self.roster("gfox", "gowl", "glion")
        finish = self.roster(pet, "gowl", "glion")
        self.cog._request_response = AsyncMock(side_effect=[
            (None, start), (None, "Player's zoo!"),
            (None, f"Player's zoo!\n<a:hidden:99> {pet}¹"), (None, f"Player, Your team: [1]{pet}"),
            (None, finish),
        ])
        await self.cog.check_once()
        event = message(f"🌱 | Player, hunt is empowered by gem\nYou found: {pet}")
        await self.cog.on_message(event)
        await self.cog.check_once()
        self.assertEqual(self.cog._request_response.await_args_list[2:], [
            call("zoo", "zoo"), call("team_add", "team", f"add {pet} 1"), call("team", "team"),
        ])
        await self.cog.on_message(event)
        await self.cog.check_once()
        self.assertTrue(self.bot._team_setup_ready)
        self.assertEqual(self.cog._request_response.await_count, 5)

    async def test_partial_initial_team_read_is_retried_only_for_a_relevant_catch(self):
        start = self.roster("gfox", "gowl", "glion")
        new = self.roster("glitchzebra", "gowl", "glion")
        glitch = "<a:glitchzebra:727735573246247045>"
        self.cog._request_response = AsyncMock(side_effect=[
            (None, "Player's team\n[2] none"), (None, start), (None, f"Player's zoo! {glitch}¹"),
            (None, f"Player, Your team: [1]{glitch}"), (None, new),
        ])
        for instant in (100, 401):
            with patch("core.cogs.weapons.time.monotonic", return_value=instant):
                await self.cog.check_once()
        self.assertIsNone(self.cog._team_slots)
        self.assertEqual(self.cog._request_response.await_count, 1)
        await self.cog.on_message(message(f"🌱 | Player spent 5 cowoncy and caught {glitch}!"))
        with patch("core.cogs.weapons.time.monotonic", return_value=402):
            await self.cog.check_once()
        self.assertEqual(self.cog._request_response.await_args_list[1:], [
            call("team", "team"), call("zoo", "zoo"), call("team_add", "team", "add glitchzebra 1"), call("team", "team"),
        ])
        self.assertTrue(self.bot._team_setup_ready)


if __name__ == "__main__":
    unittest.main()
