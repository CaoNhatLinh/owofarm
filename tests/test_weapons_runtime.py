import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from core.cogs.weapons import Weapons, _Pending
from utils.weapon_equipment import TeamSlot, WeaponCandidate


PET_STATS = "Lvl 3 `[100/1081]`\nHP `506` WP `0`\nATT `103` MAG `103`\nPR `21%` MR `21%`"


def team_text(weapon=None):
    text = "Player's team\n[1] Dog\n" + PET_STATS
    if weapon:
        text += f"\n`{weapon}` <:common:111><:sword:222> 12%"
    return text + "\n[2] none\n[3] none"


def inventory_text(weapon="A1", page="1/1", owner=42):
    row = f"`{weapon}` <:common:111><:sword:222> **Sword** 12%" if weapon else "No weapons found."
    return f"Player's weapons\nThese weapons belong to <@{owner}>\n{row}\nPage {page} | Sorting by rarity"


def message(text, author=408, channel=99, message_id=200, **kwargs):
    return NS(content=text, author=NS(id=author), channel=NS(id=channel), id=message_id,
              embeds=[], components=[], **kwargs)


class FakeDispatcher:
    def __init__(self):
        self._message_handlers = []
        self._edit_handlers = []

    def register(self, callback, edit=False):
        (self._edit_handlers if edit else self._message_handlers).append(callback)


class FakeHandler:
    def __init__(self):
        self.should_not_send = False
        self.command_handler_status = NS(state=True, hold_handler=False, sleep=False, captcha=False)
        self.queue = asyncio.PriorityQueue()
        self.checks = []
        self.cmds_state = {"weapons": {"in_queue": False}}
        self.put_queue = AsyncMock()
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def _hold_or_create_lock(self):
        async with self._lock:
            yield


def make_bot():
    settings = NS(enabled=True, rarities=["common", "uncommon"],
                  inventoryCheckInterval=3600, teamCheckInterval=300,
                  responseTimeout=0.1, maxInventoryPages=20)
    return NS(settings_dict=NS(autoWeapons=settings, prefix="owo "),
              message_dispatcher=FakeDispatcher(), ch=FakeHandler(),
              cm=NS(id=99, guild=NS(id=88)), user=NS(id=42, name="Player", display_name="Player"),
              username="Player", owo_bot_id=408, get_nick=lambda _: "Player",
              log=AsyncMock(), wait_until_ready=AsyncMock())


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = make_bot()
        self.cog = Weapons(self.bot)

    async def test_inventory_sort_selects_rarity_and_waits_for_owned_edit(self):
        calls = []
        async def select(values):
            calls.append(values)
            await self.cog.on_message_edit(None, message(inventory_text(), message_id=200))
        original = message(inventory_text().replace("Sorting by rarity", "Sorting by id"))
        original.components = [NS(custom_id="sort", options=[NS(value="rarity", default=False)], select=select)]
        self.cog._request_response = AsyncMock(return_value=(original, original.content))
        result = await self.cog._sorted_inventory()
        self.assertIsNotNone(result)
        self.assertEqual(calls, [["rarity"]])
        self.assertIn("Sorting by rarity", result[1])

    async def test_raw_sort_receives_context_and_requires_confirmation(self):
        self.bot.ws = NS(session_id="session")
        self.bot.local_headers = {"test": "header"}
        calls = []
        async def select(values, session, headers, guild_id):
            calls.append((values, session, headers, guild_id))
            await self.cog.on_component_message(message(inventory_text(), author=0, message_id=200))
        original = message(inventory_text().replace("Sorting by rarity", "Sorting by id"))
        original.components = [NS(custom_id="sort", options=[NS(value="rarity", default=False)], select=select)]
        self.cog._request_response = AsyncMock(return_value=(original, original.content))
        self.assertIsNotNone(await self.cog._sorted_inventory())
        self.assertEqual(calls, [(["rarity"], "session", {"test": "header"}, 88)])

    async def test_discord_native_choose_uses_option_object(self):
        option = NS(value="rarity", default=False)
        async def choose(*options):
            self.assertEqual(options, (option,))
            await self.cog.on_message_edit(None, message(inventory_text(), message_id=200))
        original = message(inventory_text().replace("Sorting by rarity", "Sorting by id"))
        original.components = [NS(custom_id="sort", options=[option], choose=choose)]
        self.cog._request_response = AsyncMock(return_value=(original, original.content))
        self.assertIsNotNone(await self.cog._sorted_inventory())

    async def test_inventory_does_not_scan_unsorted_without_menu(self):
        original = message(inventory_text().replace("Sorting by rarity", "Sorting by id"))
        self.cog._request_response = AsyncMock(return_value=(original, original.content))
        self.assertIsNone(await self.cog._fetch_inventory())

    async def test_sort_timeout_does_not_read_unconfirmed_inventory(self):
        original = message(inventory_text().replace("Sorting by rarity", "Sorting by id"))
        original.components = [NS(custom_id="sort", options=[NS(value="rarity", default=False)], select=AsyncMock(return_value=True))]
        self.cog._request_response = AsyncMock(return_value=(original, original.content))
        self.assertIsNone(await self.cog._sorted_inventory())
        self.assertIsNone(self.cog._pending)

    async def test_paused_bot_never_queries_or_equips(self):
        self.bot.ch.should_not_send = True
        self.bot.ch.command_handler_status.captcha = True
        self.cog._fetch_team = AsyncMock()
        await self.cog.check_once()
        self.cog._fetch_team.assert_not_awaited()
        self.bot.ch.put_queue.assert_not_awaited()

    async def test_temporary_gem_hold_clears_without_delaying_equipment_cycle(self):
        async def release_hold():
            await asyncio.sleep(0.01)
            self.bot.ch.should_not_send = False
            self.bot.ch.command_handler_status.state = True

        calls = 0
        async def fetch_team(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.bot.ch.should_not_send = True
                self.bot.ch.command_handler_status.state = False
                asyncio.create_task(release_hold())
                return [TeamSlot(1, True, None)]
            if calls == 2:
                return [TeamSlot(1, True, None)]
            return [TeamSlot(1, True, "A1")]

        self.cog._fetch_team = AsyncMock(side_effect=fetch_team)
        self.cog._fetch_inventory = AsyncMock(return_value=[WeaponCandidate("A1", "common", 12)])
        self.cog._request_response = AsyncMock(return_value=(None, "Player, Dog is now wielding Sword!"))
        await self.cog.check_once()
        self.cog._fetch_inventory.assert_awaited_once()
        self.cog._request_response.assert_awaited_once_with("equip", "weapon", "A1 1")
        self.assertEqual(calls, 1)

    async def test_captcha_during_team_read_prevents_inventory_and_equipment(self):
        async def fetch_team(**kwargs):
            self.bot.ch.should_not_send = True
            self.bot.ch.command_handler_status.captcha = True
            return [TeamSlot(1, True, None)]
        self.cog._fetch_team = AsyncMock(side_effect=fetch_team)
        self.cog._fetch_inventory = AsyncMock()
        self.cog._request_response = AsyncMock()
        await self.cog.check_once()
        self.cog._fetch_inventory.assert_not_awaited()
        self.cog._request_response.assert_not_awaited()

    async def test_full_team_does_not_request_inventory(self):
        self.cog._fetch_team = AsyncMock(return_value=[TeamSlot(1, True, "HIGH1"), TeamSlot(2, False, None)])
        self.cog._fetch_inventory = AsyncMock()
        await self.cog.check_once()
        self.cog._fetch_inventory.assert_not_awaited()

    async def test_manual_equip_invalidates_cached_team_before_auto_equip(self):
        self.cog._fetch_team = AsyncMock(return_value=[TeamSlot(1, True, None)])
        async def fetch_inventory():
            await self.cog.on_message(message("OwOweapon KEEP1 1", author=42, channel=100))
            return [WeaponCandidate("A1", "common", 12)]
        self.cog._fetch_inventory = AsyncMock(side_effect=fetch_inventory)
        self.cog._request_response = AsyncMock()
        await self.cog.check_once()
        self.cog._request_response.assert_not_awaited()
        self.cog._fetch_team.assert_awaited_once()

    async def test_one_equip_must_be_confirmed(self):
        self.cog._fetch_team = AsyncMock(return_value=[TeamSlot(1, True, None)])
        self.cog._fetch_inventory = AsyncMock(return_value=[WeaponCandidate("A1", "common", 12)])
        self.cog._request_response = AsyncMock(return_value=(None, "Player, Dog is now wielding Sword!"))
        await self.cog.check_once()
        self.cog._request_response.assert_awaited_once_with("equip", "weapon", "A1 1")
        self.assertEqual(self.cog._team_slots, [TeamSlot(1, True, "A1")])
        self.cog._fetch_team.assert_awaited_once()

    async def test_unknown_team_never_equips(self):
        self.cog._request_response = AsyncMock(return_value=(None, "Unknown team display"))
        self.assertIsNone(await self.cog._fetch_team())

    async def test_unconfirmed_equip_stops_cycle_and_defers(self):
        self.cog._fetch_team = AsyncMock(side_effect=[
            [TeamSlot(1, True, None), TeamSlot(2, True, None)],
            [TeamSlot(1, True, None), TeamSlot(2, True, None)],
            [TeamSlot(1, True, "OTHER"), TeamSlot(2, True, None)],
        ])
        self.cog._fetch_inventory = AsyncMock(return_value=[WeaponCandidate("A1", "common", 12)])
        self.cog._request_response = AsyncMock(return_value=None)
        with patch("core.cogs.weapons.time.monotonic", return_value=100):
            await self.cog.check_once()
        self.assertEqual(self.cog._request_response.await_count, 1)
        self.assertEqual(self.cog._inventory_empty_until, 3700)

    async def test_assigned_weapon_id_is_not_reused(self):
        empty = [TeamSlot(1, True, None), TeamSlot(2, True, None)]
        self.cog._fetch_team = AsyncMock(return_value=empty)
        self.cog._fetch_inventory = AsyncMock(return_value=[
            WeaponCandidate("A1", "common", 12), WeaponCandidate("B1", "uncommon", 22),
        ])
        self.cog._request_response = AsyncMock(side_effect=[
            (None, "Player, Dog is now wielding Sword!"), (None, "Player, Cat is now wielding Bow!"),
        ])
        await self.cog.check_once()
        self.assertEqual([call.args[2] for call in self.cog._request_response.await_args_list], ["A1 1", "B1 2"])
        self.cog._fetch_team.assert_awaited_once()

    async def test_empty_inventory_is_not_checked_again_before_one_hour(self):
        self.cog._fetch_team = AsyncMock(return_value=[TeamSlot(1, True, None)])
        self.cog._fetch_inventory = AsyncMock(return_value=[])
        with patch("core.cogs.weapons.time.monotonic", return_value=100):
            await self.cog.check_once()
        with patch("core.cogs.weapons.time.monotonic", return_value=500):
            await self.cog.check_once()
        self.assertEqual(self.cog._fetch_inventory.await_count, 1)
        with patch("core.cogs.weapons.time.monotonic", return_value=3701):
            await self.cog.check_once()
        self.assertEqual(self.cog._fetch_inventory.await_count, 2)
        self.cog._fetch_team.assert_awaited_once()

    async def test_queries_disable_command_retries_and_require_own_send(self):
        task = asyncio.create_task(self.cog._request_response("inventory", "weapon"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        payload = self.bot.ch.put_queue.await_args.args[0]
        self.assertFalse(payload["checks"])
        self.assertEqual(payload["id"], "weapons")
        await self.cog.on_message(message(inventory_text(), message_id=201))
        self.assertFalse(task.done())
        await self.cog.on_message(message("owo weapon", author=42, message_id=200))
        await self.cog.on_message(message(inventory_text(owner=43), message_id=202))
        await self.cog.on_message(message(inventory_text(), author=407, message_id=203))
        await self.cog.on_message(message(inventory_text(), channel=98, message_id=204))
        self.assertFalse(task.done())
        good = message(inventory_text(), message_id=205)
        await self.cog.on_message(good)
        result = await task
        self.assertIs(result[0], good)

    async def test_team_message_with_zero_wp_retains_equipment(self):
        future = asyncio.get_running_loop().create_future()
        self.cog._pending = _Pending("team", future, sent_id=100)
        good = message(team_text("KEEP1"), message_id=200)
        await self.cog.on_message(good)
        result = future.result()
        from utils.weapon_equipment import parse_team_slots
        self.assertEqual(parse_team_slots(result[1])[0].weapon_id, "KEEP1")

    async def test_public_wielding_confirmation_is_recognized(self):
        future = asyncio.get_running_loop().create_future()
        self.cog._pending = _Pending("equip", future, sent_id=100)
        await self.cog.on_message(message("🗡️ **Player**, 🐶 **Dog** is now wielding <:ugaxe:123> **Glacial Axe**!"))
        self.assertTrue(future.done())

    async def test_native_and_raw_edits_are_scoped_to_known_page_message(self):
        future = asyncio.get_running_loop().create_future()
        self.cog._pending = _Pending("inventory", future, source_id=200, expected_page=2)
        wrong = message(inventory_text(page="2/2"), author=0, message_id=201)
        await self.cog.on_component_message(wrong)
        old_page = message(inventory_text(page="1/2"), author=0, message_id=200)
        await self.cog.on_component_message(old_page)
        self.assertFalse(future.done())
        good = message(inventory_text(page="2/2"), author=0, message_id=200)
        await self.cog.on_component_message(good)
        self.assertIs(future.result()[0], good)

    async def test_pagination_collects_low_tier_from_later_page(self):
        first = message(inventory_text(weapon=None, page="1/2"))
        second = message(inventory_text(weapon="B2", page="2/2"))
        self.cog._request_response = AsyncMock(return_value=(first, first.content))
        self.cog._next_page = AsyncMock(return_value=(second, second.content))
        result = await self.cog._fetch_inventory()
        self.assertEqual([item.weapon_id for item in result], ["B2"])
        self.cog._next_page.assert_awaited_once_with(first, 2)

    async def test_unavailable_pagination_does_not_invent_inventory(self):
        first = message(inventory_text(weapon=None, page="1/3"))
        self.cog._request_response = AsyncMock(return_value=(first, first.content))
        self.cog._next_page = AsyncMock(return_value=None)
        self.assertIsNone(await self.cog._fetch_inventory())

    async def test_pagination_is_bounded(self):
        self.bot.settings_dict.autoWeapons.maxInventoryPages = 2
        pages = [message(inventory_text(weapon=None, page=f"{i}/8"), message_id=i) for i in range(1, 4)]
        self.cog._request_response = AsyncMock(return_value=(pages[0], pages[0].content))
        self.cog._next_page = AsyncMock(side_effect=[(p, p.content) for p in pages[1:]])
        self.assertIsNone(await self.cog._fetch_inventory())
        self.assertEqual(self.cog._next_page.await_count, 1)

    async def test_production_v2_inventory_uses_raw_listener(self):
        future = asyncio.get_running_loop().create_future()
        self.cog._pending = _Pending("inventory", future, sent_id=100)
        empty_native = message("", message_id=200)
        await self.cog.on_message(empty_native)
        self.assertFalse(future.done())
        raw = NS(id=200, author=NS(id=408), channel_id=99, content="", buttons=[], components=[
            NS(component_name="section", components=[NS(content="## 🗡️ <@42>'s Weapons")]),
            NS(content="`G863V0` <:uncommon:123><:ugaxe:234> **Glacial Axe** 32.5%\n"
                       "`G8625U` <:rare:345><:poison:456> **Poison Dagger** 59.2%"),
        ])
        await self.cog.on_component_message(raw)
        self.assertTrue(future.done())
        from utils.weapon_equipment import parse_weapon_inventory
        self.assertEqual([item.weapon_id for item in parse_weapon_inventory(future.result()[1], {"common", "uncommon"})], ["G863V0"])

    async def test_production_paged_next_button_is_recognized(self):
        callback = AsyncMock()
        button = NS(custom_id="paged_next", disabled=False, click=callback)
        raw = NS(buttons=[NS(custom_id="noop", disabled=True, label="1/2"), button], components=[])
        self.assertIs(self.cog._find_next_button(raw), button)

    async def test_native_next_button_optional_keyword_arguments(self):
        calls = []
        async def click(*, timeout=10, wait=True):
            calls.append((timeout, wait))
            await self.cog.on_message_edit(None, message(inventory_text(page="2/2"), message_id=200))
        original = message(inventory_text(page="1/2"), message_id=200)
        original.components = [NS(custom_id="paged_next", disabled=False, click=click)]
        result = await self.cog._next_page(original, 2)
        self.assertIsNotNone(result)
        self.assertEqual(calls, [(10, True)])

    async def test_raw_next_button_receives_existing_component_context(self):
        calls = []
        self.bot.ws = NS(session_id="test-session")
        self.bot.local_headers = {"test": "header"}
        async def click(session, headers, guild_id):
            calls.append((session, headers, guild_id))
            await self.cog.on_component_message(message(inventory_text(page="2/2"), author=0, message_id=200))
        original = message(inventory_text(page="1/2"), message_id=200)
        original.buttons = [NS(custom_id="paged_next", disabled=False, click=click)]
        result = await self.cog._next_page(original, 2)
        self.assertIsNotNone(result)
        self.assertEqual(calls, [("test-session", {"test": "header"}, 88)])

    async def test_timeout_cancels_owned_queue_entries_only(self):
        await self.bot.ch.queue.put((2, 1, {"id": "hunt"}))
        await self.bot.ch.queue.put((3, 2, {"id": "weapons"}))
        self.bot.ch.cmds_state["weapons"]["in_queue"] = True
        self.bot.ch.checks = [{"id": "weapons"}, {"id": "hunt"}]
        result = await self.cog._request_response("inventory", "weapon")
        self.assertIsNone(result)
        self.assertEqual(self.bot.ch.queue.qsize(), 1)
        self.assertEqual(self.bot.ch.queue.get_nowait()[2]["id"], "hunt")
        self.assertEqual(self.bot.ch.checks, [{"id": "hunt"}])
        self.assertFalse(self.bot.ch.cmds_state["weapons"]["in_queue"])

    async def test_cancellation_removes_pending_mutation(self):
        await self.bot.ch.queue.put((3, 1, {"id": "weapons", "cmd_name": "weapon"}))
        task = asyncio.create_task(self.cog._request_response("equip", "weapon", "A1 1"))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.bot.ch.queue.empty())
        self.assertIsNone(self.cog._pending)

    async def test_single_task_and_unload_unregisters_callbacks(self):
        async def waiting():
            await asyncio.sleep(60)
        self.cog._run = waiting
        await self.cog.cog_load()
        task = self.cog._task
        await self.cog.cog_load()
        self.assertIs(self.cog._task, task)
        await self.cog.cog_unload()
        self.assertTrue(task.cancelled())
        self.assertEqual(self.bot.message_dispatcher._message_handlers, [])
        self.assertEqual(self.bot.message_dispatcher._edit_handlers, [])


if __name__ == "__main__":
    unittest.main()
