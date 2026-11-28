"""Manage equipment through scoped, confirmed OwO command responses."""

from __future__ import annotations

import asyncio
import inspect
import re
import time
from dataclasses import dataclass

from discord.ext import commands

from core.cogs._BASE import BaseCog
from utils import bot_control
from utils.weapon_equipment import (
    TeamSlot,
    extract_message_text,
    parse_inventory_page,
    parse_team_slots,
    parse_weapon_inventory,
)
from utils.weapon_strategy import (
    ANIMAL_RANKS,
    caught_team_animals,
    first_zoo_pet,
    parse_gear,
    plan_equipment,
    plan_team_changes,
    team_animals,
    team_stats,
    weapon_role,
    zoo_animals,
)
_NO_TEAM = "create one with `owo team add {animal}`"
_NO_WEAPONS = re.compile(r"you do not have any weapons(?:\s*,\s*or the page is out of bounds)?[.!]?\s*$|no weapons found[.!]?", re.I)
_HUNT_MARKER = re.compile(r"\bspent\s+5\b|\bhunt is empowered by\b", re.I)


@dataclass
class _Pending:
    kind: str
    future: asyncio.Future
    command: str | None = None
    sent_id: int | None = None
    source_id: int | None = None
    expected_page: int | None = None


class Weapons(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self._task = None
        self._pending = None
        self._cycle_lock = asyncio.Lock()
        self._next_team_check = 0.0
        self._inventory_empty_until = 0.0
        self._team_text = ""
        self._team_slots = None
        self._team_requested = False
        self._team_refresh_requested = False
        self._team_members = {}
        self._manual_team_read_id = None
        self._zoo = None
        self._new_pets = {}
        self._unranked_catches = set()
        self._seen_catches = set()
        self._wake = asyncio.Event()
        self._needs_setup = True
        self._setup_was_enabled = self.setup_enabled
        self._bootstrap_attempted = False
        self._legacy_waiting_pet = False
        self.bot.message_dispatcher.register(self.on_component_message)
        self.bot.message_dispatcher.register(self.on_component_message, edit=True)

    @property
    def settings(self):
        return self.bot.settings_dict.autoWeapons

    @property
    def setup_enabled(self):
        return bot_control.settings_for(self.bot).get("teamSetupEnabled", False)

    def setup_status(self, status):
        self.bot._team_setup_status = status
        self.bot._team_setup_ready = status == "ready"
        self._needs_setup = status != "ready"

    def refresh_setup(self):
        enabled = self.setup_enabled
        if enabled and not self._setup_was_enabled:
            self._next_team_check = 0
            self._wake.set()
        self._setup_was_enabled = enabled

    async def cog_load(self):
        if (self.settings.enabled or self.setup_enabled) and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run())

    async def cog_unload(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for name in ("_message_handlers", "_edit_handlers"):
            handlers = getattr(self.bot.message_dispatcher, name, [])
            if self.on_component_message in handlers:
                handlers.remove(self.on_component_message)
        await self._discard_queued()

    async def _run(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.bot.log(
                    f"Auto weapons: check failed ({type(exc).__name__}); retrying later.",
                    "#b8860b",
                )
                self._inventory_empty_until = time.monotonic() + self.settings.inventoryCheckInterval
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(1, self.settings.teamCheckInterval))
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def check_once(self):
        if not (self.settings.enabled or self.setup_enabled) or not await self._wait_until_sendable():
            return
        now = time.monotonic()
        event_pending = self._new_pets or self._unranked_catches or self._team_refresh_requested
        if (now < self._next_team_check and not event_pending) or self._cycle_lock.locked():
            return
        self._next_team_check = now + self.settings.teamCheckInterval
        async with self._cycle_lock:
            if self.setup_enabled and self._unranked_catches:
                await self._rank_new_catches()
            if not self._team_requested or (self._team_slots is None and self._team_refresh_requested):
                self._team_requested = True
                self._team_refresh_requested = False
                if self.setup_enabled:
                    self.setup_status("checking_team")
                self._team_slots = await self._fetch_team(allow_bootstrap=not self.setup_enabled)
                self._team_members = team_animals(self._team_text) if self._team_slots else {}
            slots = self._team_slots
            if slots is None:
                if self.setup_enabled:
                    self.setup_status("waiting_confirmation")
                return
            if self.setup_enabled and (self._needs_setup or self._new_pets):
                await self._setup_team()
                return
            if not self.settings.enabled or not slots:
                return
            if getattr(self.settings, "strategy", "fill_empty") == "roles":
                await self._manage_roles(slots)
            else:
                await self._fill_empty(slots)

    async def _setup_team(self):
        if len(self._team_slots) != 3:
            self.setup_status("waiting_confirmation")
            return
        if self._zoo is None:
            self.setup_status("checking_zoo")
            self._zoo = await self._fetch_zoo()
            if self._zoo is None:
                return

        recent = dict(self._new_pets)
        self._zoo.update(recent)
        for name in recent:
            self._new_pets.pop(name, None)
        changes = plan_team_changes(self._team_slots, self._team_members, self._zoo.values())
        if changes and not await self._apply_team_changes(changes):
            self.setup_status("waiting_confirmation")
            return
        if not any(slot.has_pet for slot in self._team_slots):
            self.setup_status("waiting_pet")
            return
        self.setup_status("equipping")
        if await self._manage_roles(self._team_slots, first_setup=True):
            self.setup_status("ready")

    async def _fetch_zoo(self):
        response = await self._request_response("zoo", "zoo")
        if response is None:
            return None
        message, text = response
        page = parse_inventory_page(text)
        animals = {animal.key: animal for animal in zoo_animals(text)}
        if page is None:
            return animals
        current, total = page
        if current != 1 or total > self.settings.maxInventoryPages:
            return None
        for expected in range(2, total + 1):
            response = await self._next_page(message, expected, kind="zoo")
            if response is None:
                return None
            message, text = response
            if parse_inventory_page(text) != (expected, total):
                return None
            animals.update((animal.key, animal) for animal in zoo_animals(text))
        return animals

    async def _rank_new_catches(self):
        unranked = self._unranked_catches
        self._unranked_catches = set()
        zoo = await self._fetch_zoo()
        if zoo is None:
            return
        self._zoo = zoo
        for key in unranked:
            if key in zoo:
                self._consider_new_pet(zoo[key])

    async def _apply_team_changes(self, changes):
        attempted = {}
        team_before = self._team_slots
        for position, animal in changes:
            if self._team_slots is not team_before or not self.setup_enabled or not await self._wait_until_sendable():
                break
            attempted[position] = animal
            response = await self._request_response("team_add", "team", f"add {animal.command} {position}")
            if not response:
                break
            confirmed = team_animals(response[1]).get(position)
            if not confirmed or confirmed.key != animal.key:
                break
        if not attempted:
            return False
        # Compact updates prove each mutation; this one full read gathers stats and
        # current gear for every changed pet, including pet gear held on other teams.
        confirmed = await self._fetch_team(allow_bootstrap=False)
        members = team_animals(self._team_text) if confirmed else {}
        if not confirmed or any(not members.get(pos) or members[pos].key != animal.key for pos, animal in attempted.items()):
            self._team_slots = None
            return False
        self._team_slots = confirmed
        self._team_members = members
        self._inventory_empty_until = 0
        return len(attempted) == len(changes)

    async def _fill_empty(self, slots):
        if not any(slot.has_pet and not slot.weapon_id for slot in slots) or time.monotonic() < self._inventory_empty_until:
            return
        if not await self._wait_until_sendable():
            return
        candidates = await self._fetch_inventory()
        if candidates and self._team_slots is slots:
            for target in slots:
                if not target.has_pet or target.weapon_id:
                    continue
                equipped = {slot.weapon_id for slot in self._team_slots}
                eligible = [item for item in candidates if item.weapon_id not in equipped]
                if not eligible:
                    break
                weapon = min(eligible, key=lambda item: (item.quality, item.weapon_id))
                if not await self._equip_weapon(target.position, weapon.weapon_id):
                    break
        self._inventory_empty_until = time.monotonic() + self.settings.inventoryCheckInterval

    async def _equip_weapon(self, position, weapon_id, name=None):
        if not await self._wait_until_sendable() or self._team_slots is None:
            return False
        team_before = self._team_slots
        response = await self._request_response("equip", "weapon", f"{weapon_id} {position}")
        if self._team_slots is not team_before:
            return False
        text = response[1].casefold() if response else ""
        if not re.search(r"\bis now wielding\b|\bsuccessfully equipped\b", text) or (name and name.casefold() not in text):
            if not any(failure in text for failure in ("cannot change your weapon", "could not find", "invalid arguments")):
                self._team_slots = None  # Ambiguous outcome; avoid a blind second change.
            return False
        self._team_slots = [
            TeamSlot(slot.position, slot.has_pet,
                     weapon_id if slot.position == position else None if slot.weapon_id == weapon_id else slot.weapon_id)
            for slot in team_before
        ]
        return True

    async def _fetch_team(self, *, allow_bootstrap=True):
        response = await self._request_response("team", "team")
        if response is None:
            return None
        self._team_text = response[1]
        slots = parse_team_slots(response[1])
        no_team = _NO_TEAM in response[1].casefold()
        if (no_team or (len(slots) == 3 and not any(s.has_pet for s in slots))) and allow_bootstrap and getattr(self.settings, "bootstrapFirstPet", False):
            if self._bootstrap_attempted:
                return None
            self._bootstrap_attempted = True
            zoo = await self._request_response("zoo", "zoo")
            pet = first_zoo_pet(zoo[1]) if zoo else None
            if zoo and pet is None:
                self._bootstrap_attempted = False
                self._legacy_waiting_pet = True  # An owned first catch will wake setup once.
            if pet:
                await self._request_response("team_add", "team", f"add {pet} 1")
                # Read back the team, rather than assuming the add succeeded.
                confirmed = await self._request_response("team", "team")
                if confirmed:
                    self._team_text = confirmed[1]
                    slots = parse_team_slots(confirmed[1])
                    if any(s.has_pet for s in slots):
                        await self.bot.log(f"Auto weapons: created team with first zoo pet ({pet}).", "#74c8d1")
                        return slots
                    if "create one with `owo team add {animal}`" in confirmed[1].casefold():
                        self._bootstrap_attempted = False
            # No blind repeated add commands after a timeout. Recheck next cycle.
            return None
        if no_team:
            return [TeamSlot(position, False, None) for position in (1, 2, 3)]
        if not allow_bootstrap and len(slots) != 3:
            return None
        if not slots:
            await self.bot.log("Auto weapons: unknown team format; leaving equipment unchanged.", "#b8860b")
            return None
        return slots

    async def _full_inventory(self):
        response = await self._sorted_inventory()
        found = {}
        expected_total = None
        for expected in range(1, self.settings.maxInventoryPages + 1):
            if response is None:
                return None
            message, text = response
            page = parse_inventory_page(text)
            # No partial/filtered/ambiguous scan may drive a sale.
            filters = re.search(r"Weapon Filters:\*{0,2}\s*`?([^\n`]+)", text, re.I)
            if filters and filters[1].strip().casefold() != "none":
                return None
            if expected == 1 and page in (None, (1, 1)) and _NO_WEAPONS.search(text):
                return []
            rows = parse_gear(text)
            if rows is None or page is None or page[0] != expected:
                return None
            if expected_total is None:
                expected_total = page[1]
            if page[1] != expected_total:
                return None
            for item in rows:
                if item.weapon_id in found:
                    return None  # Inventory shifted while paging.
                found[item.weapon_id] = item
            if page[0] == page[1]:
                return list(found.values())
            response = await self._next_page(message, expected + 1)
        return None

    async def _manage_roles(self, slots, *, first_setup=False):
        if not slots or len(slots) != 3 or time.monotonic() < self._inventory_empty_until:
            return False
        delay = self.settings.teamCheckInterval if first_setup else self.settings.inventoryCheckInterval
        self._inventory_empty_until = time.monotonic() + delay
        stats = team_stats(self._team_text)
        if any(slot.has_pet and slot.position not in stats for slot in slots):
            return False
        if self._team_slots is None:
            self._team_slots = slots
        gear = await self._full_inventory()
        if gear is None or self._team_slots is not slots:
            return False
        if not gear:
            return True
        plan = plan_equipment(slots, stats, gear)
        if plan is None:
            return False
        for position, weapon_id in plan.items():
            current = next((slot for slot in self._team_slots if slot.position == position), None)
            if weapon_id is None or (current and current.weapon_id == weapon_id):
                continue
            weapon = next(item for item in gear if item.weapon_id == weapon_id)
            if not await self._equip_weapon(position, weapon_id, weapon.name):
                return False
        if first_setup or not getattr(self.settings, "sellSurplus", False):
            return True

        # Sale eligibility is confirmed from current inventory, including equipment
        # on other teams. A changed/unknown roster stops the legacy surplus sale.
        slots = self._team_slots
        if any(slot.has_pet and (not plan.get(slot.position) or slot.weapon_id != plan[slot.position]) for slot in slots):
            return True
        keep = set(plan.values())
        gear = await self._full_inventory()
        if gear is None or self._team_slots is not slots:
            return True
        for item in gear:
            if item.weapon_id in keep or item.equipped or item.favorite or weapon_role(item) is None or item.quality > 40:
                continue
            latest_inventory = await self._full_inventory()
            if latest_inventory is None or self._team_slots is not slots:
                break
            if plan_equipment(slots, stats, latest_inventory) != plan:
                break
            latest = next((item_now for item_now in latest_inventory if item_now.weapon_id == item.weapon_id), None)
            if latest != item:
                break
            response = await self._request_response("weapon_sell", "sell", item.weapon_id)
            if response is None or "you sold a(n)" not in response[1].casefold():
                break
            await self.bot.log(f"Đã bán vũ khí dư {item.weapon_id}.", "#74c8d1")
        return True

    async def _fetch_inventory(self):
        response = await self._sorted_inventory()
        if response is None:
            return None
        found = {}
        seen_pages = set()
        for page_index in range(self.settings.maxInventoryPages):
            message, text = response
            for item in parse_weapon_inventory(text, set(self.settings.rarities)):
                found.setdefault(item.weapon_id, item)
            page = parse_inventory_page(text)
            if page is None or page[0] >= page[1]:
                return list(found.values())
            if page[0] in seen_pages:
                return list(found.values()) if found else None
            seen_pages.add(page[0])
            if len(found) >= 3:
                return list(found.values())
            if page_index + 1 >= self.settings.maxInventoryPages:
                break
            response = await self._next_page(message, page[0] + 1)
            if response is None:
                return list(found.values()) if found else None
        await self.bot.log("Auto weapons: inventory page limit reached; remaining pages deferred.", "#b8860b")
        return list(found.values()) if found else None

    async def _wait_until_sendable(self):
        """Wait briefly for another cog, while respecting explicit pauses."""
        from utils import bot_control
        if getattr(self, "_manual_requests", False):
            status = self.bot.ch.command_handler_status
            return not (status.captcha or status.sleep or self.bot.response_guard.cooling_down)
        if not bot_control.running_for(self.bot):
            return False
        deadline = time.monotonic() + self.settings.responseTimeout
        while self.bot.ch.should_not_send:
            status = getattr(self.bot.ch, "command_handler_status", None)
            if status is None or status.captcha or status.sleep:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(0.25, remaining))
        return True

    async def _request_response(self, kind, command, arguments=""):
        manual = getattr(self, "_manual_requests", False)
        channel = self.bot.cm
        prefix = self.bot.settings_dict.prefix
        if not await self._wait_until_sendable():
            return None
        if manual and channel is None:
            return None
        if not manual:
            prefix = self.bot.settings_dict.prefix
        full_command = f"{prefix}{command} {arguments}".rstrip()
        pending = _Pending(kind, asyncio.get_running_loop().create_future(), full_command)
        self._pending = pending
        completed = False

        def request_current():
            return (
                self._pending is pending and not pending.future.done()
                and channel is not None and getattr(self.bot.cm, "id", None) == channel.id
                and self.bot.settings_dict.prefix == prefix
            )

        try:
            if manual:
                from core.quick_sales import SaleStopped, check_context

                def can_send():
                    if not request_current():
                        return False
                    try:
                        check_context(self.bot, (channel.id, prefix))
                    except SaleStopped:
                        return False
                    return True

                sent = await asyncio.wait_for(
                    self.bot.send(full_command, channel=channel, expect_response=True, manual=True,
                                  automation_check=can_send),
                    self.settings.responseTimeout + bot_control.settings_for(self.bot)["messageInterval"],
                )
                if not sent:
                    return None
                self.bot.db.update_cmd_db("sac" if command == "sac" else "sell")
            else:
                await asyncio.wait_for(
                    self.bot.ch.put_queue({
                        "cmd_name": command,
                        "cmd_arguments": arguments,
                        "prefix": True,
                        "checks": False,
                        "id": "weapons",
                        "automation_check": request_current,
                    }),
                    self.settings.responseTimeout,
                )
            response = await asyncio.wait_for(pending.future, self.settings.responseTimeout)
            completed = True
            return response
        except asyncio.TimeoutError:
            text = ("Thao tác thủ công: chưa nhận được phản hồi; không tự gửi lại lệnh."
                    if manual else f"Auto weapons: {kind} response unavailable; leaving equipment unchanged.")
            await self.bot.log(text, "#b8860b")
            return None
        finally:
            if self._pending is pending:
                self._pending = None
            if not pending.future.done():
                pending.future.cancel()
            if not completed and not manual:
                await self._discard_queued()

    @staticmethod
    def _rarity_sort_menu(message):
        stack = list(getattr(message, "components", []) or [])
        seen = set()
        while stack:
            item = stack.pop(0)
            if id(item) in seen:
                continue
            seen.add(id(item))
            if "sort" in str(getattr(item, "custom_id", "")).casefold():
                for option in getattr(item, "options", []) or []:
                    if str(getattr(option, "value", "")).casefold() == "rarity":
                        if callable(getattr(item, "select", None)) or callable(getattr(item, "choose", None)):
                            return item, bool(getattr(option, "default", False))
            for name in ("components", "children"):
                stack.extend(getattr(item, name, []) or [])
        return None, False

    @classmethod
    def _is_quality_sorted(cls, message, text):
        _, selected = cls._rarity_sort_menu(message)
        return selected or bool(re.search(r"sorting by rarity", text, re.I))

    async def _sorted_inventory(self):
        response = await self._request_response("inventory", "weapon")
        if response is None:
            return None
        message, text = response
        if _NO_WEAPONS.search(text):
            return response
        if self._is_quality_sorted(message, text):
            return response
        menu, _ = self._rarity_sort_menu(message)
        if menu is None or not await self._wait_until_sendable():
            await self.bot.log("Auto weapons: không tìm thấy menu Sort by Rarity; hoãn đọc kho.", "#b8860b")
            return None
        pending = _Pending("inventory", asyncio.get_running_loop().create_future(),
                           source_id=int(message.id), expected_page=1)
        self._pending = pending
        try:
            select = getattr(menu, "select", None)
            required = {p.name for p in inspect.signature(select).parameters.values()
                        if p.default is inspect.Parameter.empty and p.kind not in
                        (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)} if callable(select) else None
            if required is None and callable(getattr(menu, "choose", None)):
                option = next(o for o in menu.options if str(o.value).casefold() == "rarity")
                operation = menu.choose(option)
            elif required == {"values", "session", "headers", "guild_id"}:
                operation = select(["rarity"], self.bot.ws.session_id,
                                        self.bot.local_headers, self.bot.cm.guild.id)
            elif required == {"values"}:
                operation = select(["rarity"])
            else:
                return None
            if await asyncio.wait_for(operation, self.settings.responseTimeout) is False:
                return None
            result = await asyncio.wait_for(pending.future, self.settings.responseTimeout)
            if self._is_quality_sorted(*result):
                await self.bot.log("Auto weapons: đã xếp weapon theo % cao → thấp (Rarity).", "#74c8d1")
                return result
            return None
        except (asyncio.TimeoutError, AttributeError, TypeError):
            return None
        finally:
            if self._pending is pending:
                self._pending = None
            if not pending.future.done():
                pending.future.cancel()

    async def _next_page(self, message, page, *, kind="inventory"):
        if not await self._wait_until_sendable():
            return None
        button = self._find_next_button(message)
        if button is None:
            await self.bot.log("Auto weapons: inventory pagination unavailable; no blind equipment changes.", "#b8860b")
            return None
        pending = _Pending(
            kind, asyncio.get_running_loop().create_future(),
            source_id=int(message.id), expected_page=page,
        )
        self._pending = pending
        try:
            click = button.click
            parameters = inspect.signature(click).parameters.values()
            required = [
                parameter for parameter in parameters
                if parameter.default is inspect.Parameter.empty
                and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ]
            if not required:
                operation = click()
            elif {parameter.name for parameter in required} == {"session", "headers", "guild_id"}:
                operation = click(self.bot.ws.session_id, self.bot.local_headers, self.bot.cm.guild.id)
            else:
                return None
            await asyncio.wait_for(operation, self.settings.responseTimeout)
            return await asyncio.wait_for(pending.future, self.settings.responseTimeout)
        except (asyncio.TimeoutError, AttributeError, TypeError):
            return None
        finally:
            if self._pending is pending:
                self._pending = None
            if not pending.future.done():
                pending.future.cancel()

    @staticmethod
    def _find_next_button(message):
        stack = list(getattr(message, "buttons", []) or []) + list(getattr(message, "components", []) or [])
        seen = set()
        while stack:
            item = stack.pop(0)
            if id(item) in seen:
                continue
            seen.add(id(item))
            custom_id = str(getattr(item, "custom_id", "")).lower()
            if custom_id in {"next", "paged_next"} and not getattr(item, "disabled", False) and callable(getattr(item, "click", None)):
                return item
            for name in ("components", "children", "buttons"):
                stack.extend(getattr(item, name, []) or [])
        return None

    def _owned_response(self, message, text, pending):
        if pending.source_id is not None:
            # A pagination update is trusted only for the already owned message.
            return int(getattr(message, "id", 0)) == pending.source_id
        reference = getattr(message, "reference", None)
        reply_to = getattr(reference, "message_id", None)
        if reply_to is not None:
            return reply_to == pending.sent_id
        mentions = re.findall(r"<@!?(\d+)>", text)
        if mentions:
            return str(self.bot.user.id) in mentions
        names = {
            getattr(self.bot.user, "name", ""),
            getattr(self.bot.user, "display_name", ""),
            getattr(self.bot, "username", ""),
        }
        try:
            names.add(self.bot.get_nick(message))
        except (AttributeError, TypeError):
            pass
        plain = re.sub(r"[*~`]", "", text).casefold()
        header = re.sub(r"<a?:\w+:\d+>", "", plain).lstrip()
        owner = re.match(r"(?:[^\n]*?\|\s*)?([^\n]+?)(?:['’]s\s+(?:team|zoo|weapons)\b|,\s+you\b|\s+(?:sold|sacrificed)\b)", header)
        if owner:
            return any(owner[1].strip() == name.casefold() for name in names if name)
        return any(
            re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", plain)
            for name in names if name
        )

    async def _handle_message(self, message):
        pending = self._pending
        if pending is None or pending.future.done():
            return
        channel = getattr(message, "channel", None)
        channel_id = getattr(channel, "id", None) or getattr(message, "channel_id", None)
        if channel_id != self.bot.cm.id:
            return
        author_id = getattr(getattr(message, "author", None), "id", 0)
        message_id = int(getattr(message, "id", 0))
        content = getattr(message, "content", "") or ""
        if author_id == self.bot.user.id:
            if pending.command and content.rstrip() == pending.command:
                pending.sent_id = message_id
            return
        is_known_edit = pending.source_id is not None and message_id == pending.source_id
        if author_id != self.bot.owo_bot_id and not (is_known_edit and author_id == 0):
            return
        if pending.source_id is None and (pending.sent_id is None or message_id < pending.sent_id):
            return
        text = extract_message_text(message)
        if not self._owned_response(message, text, pending):
            return
        if pending.kind == "team":
            if not parse_team_slots(text) and "create one with `owo team add {animal}`" not in text.casefold():
                return
        elif pending.kind == "zoo":
            if "zoo!" not in text.casefold():
                return
            if pending.expected_page is not None:
                page = parse_inventory_page(text)
                if page is None or page[0] != pending.expected_page:
                    return
        elif pending.kind == "team_add":
            if not any(word in text.casefold() for word in ("added", "team", "could not find")):
                return
        elif pending.kind == "weapon_sell":
            if not any(word in text.casefold() for word in ("you sold a(n)", "weapon", "cannot be sold")):
                return
        elif pending.kind == "animal_sell":
            lower = text.casefold()
            if not any(marker in lower for marker in (" sold ", "animals", "failed to sell", "invalid arguments")):
                return
        elif pending.kind == "weapon_rank_sell":
            lower = text.casefold()
            if not any(marker in lower for marker in ("weapons", "invalid arguments", "went terribly wrong")):
                return
        elif pending.kind == "animal_sacrifice":
            lower = text.casefold()
            if not any(marker in lower for marker in (" sacrificed ", "animals", "failed to sacrifice", "invalid arguments")):
                return
        elif pending.kind == "inventory":
            if "weapons" not in text.casefold():
                return
            if pending.expected_page is not None:
                page = parse_inventory_page(text)
                if page is None or page[0] != pending.expected_page:
                    return
        elif pending.kind == "equip":
            lower = text.casefold()
            if not any(marker in lower for marker in ("equipped", "is now wielding", "cannot change your weapon", "could not find", "invalid arguments")):
                return
        pending.future.set_result((message, text))

    def _observe_manual_team(self, message):
        if not self._team_requested:
            return
        text = getattr(message, "content", "") or ""
        if message.author.id == self.bot.user.id:
            own_channel = message.channel.id == self.bot.cm.id
            if own_channel and self._pending and text.rstrip() == self._pending.command:
                return
            text = text.casefold()
            prefixes = {self.bot.settings_dict.prefix.casefold(), "owo", "uwu"}
            prefix = next((candidate for candidate in sorted(prefixes, key=len, reverse=True)
                           if text.startswith(candidate)), None)
            if prefix is None:
                return
            arguments = text[len(prefix):].split()
            if not arguments:
                return
            command, *args = arguments
            if command in {"team", "tm", "squad"} and not args:
                if own_channel:
                    self._manual_team_read_id = message.id
            elif (command == "setteam" or command in {"team", "tm", "squad"} and args[0] in {"add", "remove", "rm"}
                  or command in {"weapon", "w", "wep"} and len(args) >= 2):
                self._team_slots = None
            return
        if (message.channel.id != self.bot.cm.id or message.author.id != self.bot.owo_bot_id or self._pending is not None
                or self._manual_team_read_id is None or message.id <= self._manual_team_read_id):
            return
        text = extract_message_text(message)
        slots = parse_team_slots(text)
        if len(slots) == 3 and self._owned_response(message, text, _Pending("team", None, sent_id=self._manual_team_read_id)):
            self._manual_team_read_id = None
            self._team_slots = slots
            self._team_text = text
            self._team_members = team_animals(text)
            if self.setup_enabled and self._needs_setup:
                self._next_team_check = 0
                self._wake.set()

    def _consider_new_pet(self, animal):
        slots = self._team_slots
        empty = slots is not None and not any(slot.has_pet for slot in slots)
        zoo = self._zoo or {}
        members = {position: zoo.get(member.key, member) for position, member in self._team_members.items() if member}
        if empty or animal.rank >= ANIMAL_RANKS["rare"] and (slots is None or plan_team_changes(slots, members, [animal])):
            self._new_pets[animal.key] = animal
            self._team_refresh_requested = slots is None
            self.setup_status("checking_team")
            self._wake.set()

    def _observe_zoo_catch(self, message):
        if (not self._team_requested or not (self.setup_enabled or self._legacy_waiting_pet) or message.author.id != self.bot.owo_bot_id
                or message.channel.id != self.bot.cm.id):
            return
        text = getattr(message, "content", "") or ""
        line = re.sub(r"[*~`]", "", text.partition("\n")[0])
        marker = _HUNT_MARKER.search(line)
        if not marker:
            return
        header = line[:marker.start()]
        label = (header.partition("|")[2] or header).strip(" ,").casefold()
        names = {self.bot.get_nick(message), self.bot.user.name, self.bot.user.display_name}
        mentions = re.findall(r"<@!?(\d+)>", header)
        if mentions:
            if str(self.bot.user.id) not in mentions:
                return
        elif label not in {name.casefold() for name in names if name}:
            return
        caught = caught_team_animals(text)
        if not self.setup_enabled:
            if caught:
                self._legacy_waiting_pet = False
                self._team_refresh_requested = True
                self._next_team_check = 0
                self._wake.set()
            return
        current = {member.key for member in self._team_members.values() if member}
        for animal in caught:
            if animal.key in current or animal.key in self._seen_catches or self._zoo and animal.key in self._zoo:
                continue
            self._seen_catches.add(animal.key)
            if animal.rank:
                self._consider_new_pet(animal)
            else:
                self._unranked_catches.add(animal.key)
                self._wake.set()

    @commands.Cog.listener()
    async def on_message(self, message):
        self._observe_manual_team(message)
        self._observe_zoo_catch(message)
        await self._handle_message(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        await self._handle_message(after)

    async def on_component_message(self, message):
        await self._handle_message(message)

    async def _discard_queued(self):
        handler = self.bot.ch
        async with handler._hold_or_create_lock():
            kept = []
            while not handler.queue.empty():
                item = handler.queue.get_nowait()
                if item[2].get("id") != "weapons":
                    kept.append(item)
            for item in kept:
                handler.queue.put_nowait(item)
            state = handler.cmds_state.get("weapons")
            if state is not None:
                state["in_queue"] = False
            handler.checks[:] = [item for item in handler.checks if item.get("id") != "weapons"]


async def setup(bot):
    await bot.add_cog(Weapons(bot))
