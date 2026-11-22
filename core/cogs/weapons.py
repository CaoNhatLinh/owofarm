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
    extract_message_text,
    parse_inventory_page,
    parse_team_slots,
    parse_weapon_inventory,
)
from utils.weapon_strategy import first_zoo_pet, parse_gear, team_stats, plan_equipment, weapon_role


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
        self._bootstrap_attempted = False
        self.bot.message_dispatcher.register(self.on_component_message)
        self.bot.message_dispatcher.register(self.on_component_message, edit=True)

    @property
    def settings(self):
        return self.bot.settings_dict.autoWeapons

    async def cog_load(self):
        if self.settings.enabled and (self._task is None or self._task.done()):
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
        while self.settings.enabled:
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
            await asyncio.sleep(max(1, self.settings.teamCheckInterval))

    async def check_once(self):
        if not self.settings.enabled or not await self._wait_until_sendable():
            return
        now = time.monotonic()
        if now < self._next_team_check or self._cycle_lock.locked():
            return
        self._next_team_check = now + self.settings.teamCheckInterval
        async with self._cycle_lock:
            slots = await self._fetch_team()
            if getattr(self.settings, "strategy", "fill_empty") == "roles":
                await self._manage_roles(slots)
                return
            if not slots or not any(slot.has_pet and not slot.weapon_id for slot in slots):
                return
            if time.monotonic() < self._inventory_empty_until:
                return

            attempted = set()
            # There are at most three occupied positions on the active team.
            for _ in range(3):
                if not await self._wait_until_sendable():
                    return
                candidates = await self._fetch_inventory()
                if not candidates:
                    self._inventory_empty_until = time.monotonic() + self.settings.inventoryCheckInterval
                    await self.bot.log(
                        "Auto weapons: no confirmed eligible unused weapons; inventory check deferred for one hour.",
                        "#b8860b",
                    )
                    return

                # Inventory reads/pagination can take time. Re-read the active
                # team immediately before each equipment change.
                slots = await self._fetch_team()
                if not slots:
                    return
                missing = [slot for slot in slots if slot.has_pet and not slot.weapon_id]
                if not missing:
                    return
                equipped = {slot.weapon_id for slot in slots if slot.weapon_id}
                eligible = [
                    item for item in candidates
                    if item.weapon_id not in attempted and item.weapon_id not in equipped
                ]
                if not eligible:
                    self._inventory_empty_until = time.monotonic() + self.settings.inventoryCheckInterval
                    return
                weapon = min(eligible, key=lambda item: (item.quality, item.weapon_id))
                target = min(missing, key=lambda slot: slot.position)
                attempted.add(weapon.weapon_id)
                if not await self._wait_until_sendable():
                    return
                await self._request_response(
                    "equip", "weapon", f"{weapon.weapon_id} {target.position}"
                )
                # A request timeout is not an equip success. Stop if a fresh
                # team read cannot confirm the exact weapon in the exact slot.
                confirmed = await self._fetch_team()
                actual = next((slot for slot in confirmed or [] if slot.position == target.position), None)
                if actual is None or actual.weapon_id != weapon.weapon_id:
                    self._inventory_empty_until = time.monotonic() + self.settings.inventoryCheckInterval
                    await self.bot.log(
                        "Auto weapons: equipment change not confirmed; no further changes this cycle.",
                        "#b8860b",
                    )
                    return
                await self.bot.log(
                    f"Auto weapons: equipped {weapon.weapon_id} ({weapon.rarity}) in slot {target.position}.",
                    "#74c8d1",
                )
                if all(not slot.has_pet or slot.weapon_id for slot in confirmed):
                    return

    async def _fetch_team(self):
        response = await self._request_response("team", "team")
        if response is None:
            return None
        self._team_text = response[1]
        slots = parse_team_slots(response[1])
        no_team = "create one with `owo team add {animal}`" in response[1].casefold()
        if (no_team or (len(slots) == 3 and not any(s.has_pet for s in slots))) and getattr(self.settings, "bootstrapFirstPet", False):
            if self._bootstrap_attempted:
                return None
            self._bootstrap_attempted = True
            zoo = await self._request_response("zoo", "zoo")
            pet = first_zoo_pet(zoo[1]) if zoo else None
            if zoo and pet is None:
                self._bootstrap_attempted = False  # Try again after hunting the first animal.
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
            rows = parse_gear(text)
            # No partial/filtered/ambiguous scan may drive a sale.
            filters = re.search(r"Weapon Filters:\*{0,2}\s*`?([^\n`]+)", text, re.I)
            if filters and filters[1].strip().casefold() != "none":
                return None
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

    async def _manage_roles(self, slots):
        if not slots or len(slots) != 3 or time.monotonic() < self._inventory_empty_until:
            return
        self._inventory_empty_until = time.monotonic() + self.settings.inventoryCheckInterval
        gear = await self._full_inventory()
        if not gear:
            return
        slots = await self._fetch_team()
        if not slots or len(slots) != 3:
            return
        plan = plan_equipment(slots, team_stats(self._team_text), gear)
        if plan is None:
            return
        for position, wid in plan.items():
            current = next((s for s in slots if s.position == position), None)
            if wid is None or (current and current.weapon_id == wid):
                continue
            if not await self._wait_until_sendable():
                return
            await self._request_response("equip", "weapon", f"{wid} {position}")
            slots = await self._fetch_team()
            if not slots or len(slots) != 3 or not any(s.position == position and s.weapon_id == wid for s in slots):
                return
        slots = await self._fetch_team()
        if not slots or len(slots) != 3 or any(s.has_pet and (not plan.get(s.position) or s.weapon_id != plan[s.position]) for s in slots):
            return
        if not getattr(self.settings, "sellSurplus", False):
            return
        keep = set(plan.values())
        # Refresh after equipping: previously equipped gear may now be surplus.
        gear = await self._full_inventory()
        if gear is None:
            return
        for item in gear:
            if item.weapon_id in keep or item.equipped or item.favorite or weapon_role(item) is None or item.quality > 40:
                continue
            fresh_team = await self._fetch_team()
            fresh_gear = await self._full_inventory()
            if not fresh_team or len(fresh_team) != 3 or fresh_gear is None:
                return
            if any(s.has_pet and (not plan.get(s.position) or s.weapon_id != plan[s.position]) for s in fresh_team):
                return
            if plan_equipment(fresh_team, team_stats(self._team_text), fresh_gear) != plan:
                return
            latest = next((g for g in fresh_gear if g.weapon_id == item.weapon_id), None)
            if latest is None or latest.equipped or latest.favorite or latest != item:
                return
            response = await self._request_response("weapon_sell", "sell", item.weapon_id)
            if response is None or "you sold a(n)" not in response[1].casefold():
                return
            await self.bot.log(f"Auto weapons: sold surplus weapon {item.weapon_id}.", "#74c8d1")

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
        if not bot_control.is_running():
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
        if not await self._wait_until_sendable():
            return None
        full_command = f"{self.bot.settings_dict.prefix}{command} {arguments}".rstrip()
        pending = _Pending(kind, asyncio.get_running_loop().create_future(), full_command)
        self._pending = pending
        completed = False
        manual = getattr(self, "_manual_requests", False)
        try:
            if manual:
                sent = await asyncio.wait_for(
                    self.bot.send(full_command, expect_response=True, manual=True),
                    self.settings.responseTimeout + bot_control.get_settings()["messageInterval"],
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

    async def _next_page(self, message, page):
        if not await self._wait_until_sendable():
            return None
        button = self._find_next_button(message)
        if button is None:
            await self.bot.log("Auto weapons: inventory pagination unavailable; no blind equipment changes.", "#b8860b")
            return None
        pending = _Pending(
            "inventory", asyncio.get_running_loop().create_future(),
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
        if reference and getattr(reference, "message_id", None) == pending.sent_id:
            return True
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
        plain = re.sub(r"[*_~`]", "", text).casefold()
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

    @commands.Cog.listener()
    async def on_message(self, message):
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
