# This file is part of owo-dusk.
#
# Copyright (c) 2024-present EchoQuill
#
# Portions of this file are based on code by EchoQuill, licensed under the
# GNU General Public License v3.0 (GPL-3.0).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import asyncio
import re
import time

from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded

from core.cogs._BASE import BaseCog
from utils import bot_control, gem_control
from utils.weapon_equipment import extract_message_text

"""
REF :-
gem code - https://github.com/ChristopherBThai/Discord-OwO-Bot/blob/master/src/commands/commandList/shop/inventory.js
small numbers - https://github.com/ChristopherBThai/Discord-OwO-Bot/blob/master/src/commands/commandList/shop/util/shopUtil.js
"""


gem_tiers = {
    "common": ["051", "065", "072", "079"],
    "uncommon": ["052", "066", "073", "080"],
    "rare": ["053", "067", "074", "081"],
    "epic": ["054", "068", "075", "082"],
    "mythical": ["055", "069", "076", "083"],
    "legendary": ["056", "070", "077", "084"],
    "fabled": ["057", "071", "078", "085"],
}

GEM_TYPES = {
    "gem1": "huntGem",
    "gem3": "empoweredGem",
    "gem4": "luckyGem",
    "star": "specialGem",
}
GEM_TIERS = {tier[0]: tier for tier in gem_tiers}
GEM_NAMES = {"hunting": "huntGem", "empowering": "empoweredGem", "lucky": "luckyGem", "special": "specialGem"}
GEM_IDS = {gem_id: (tier, kind) for tier, ids in gem_tiers.items() for kind, gem_id in zip(GEM_TYPES.values(), ids)}
GEM_ID_BY_TYPE = {(tier, kind): gem_id for gem_id, (tier, kind) in GEM_IDS.items()}
SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
INVENTORY_ENTRY = re.compile(r"`([0-9]{3})`\s*<a?:\w+:[0-9]+>\s*([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")
EMOJI = re.compile(r"<a?:(\w+):[0-9]+>")
GEM_ICON = re.compile(r"([curemlf])(gem[1-4]|star)")
GEM_COUNTER = re.compile(r"\s*`?\[\s*([0-9][0-9,]*)\s*/\s*([0-9][0-9,]*)\s*\]")
EMPOWERED_HUNT = re.compile(r"\bhunt is empowered by\b", re.I)
PLAIN_HUNT = re.compile(r"\bspent\s+\*{0,2}5\b[^\n]*\band caught\b", re.I)
INVENTORY_TITLE = re.compile(r"['’]s (?:inventory|inv)\b", re.I)
USE_REPLY = re.compile(r"\byou (?:activated|already have an active)\b", re.I)
ACTIVATED_GEM = re.compile(
    rf"(?:a\(n\)|an?)\s+\*{{0,2}}({'|'.join(gem_tiers)})\s+({'|'.join(GEM_NAMES)})\s+gem\b", re.I
)


def find_gems_available(message):
    available_gems = {tier: dict.fromkeys(ids, 0) for tier, ids in gem_tiers.items()}
    for gem_id, count in INVENTORY_ENTRY.findall(message):
        if gem_id in GEM_IDS:
            tier, _ = GEM_IDS[gem_id]
            available_gems[tier][gem_id] = int(count.translate(SUPERSCRIPT_DIGITS))
    return available_gems


class Gems(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.available_gems = {}
        self.message_lock = asyncio.Lock()
        self.inventory_check = False
        self.inventory_deadline = 0
        self.inventory_after_id = 0
        self.last_inventory_id = 0
        self.cache_gems_in_use = []
        self.last_hunt_id = 0
        self.use_after_id = 0
        self.use_pending_until = 0
        self.pending_use_ids = ()
        self.last_use_reply_id = 0
        self.inventory_refresh_at = 0
        self.gem_cmd = {
            "cmd_name": self.bot.alias["use"]["normal"],
            "cmd_arguments": "",
            "prefix": True,
            "checks": False,
            "id": "gems",
        }
        self.inv_cmd = {
            "cmd_name": self.bot.alias["inv"]["normal"],
            "prefix": True,
            "checks": False,
            "id": "inv",
        }

    @property
    def settings(self):
        return self.bot.settings_dict.autoUse.gems

    def should_use_special_gem(self):
        if not self.settings.gemsToUse["specialGem"]:
            return False
        if self.settings.dynamicSpecialGem and not self.bot.ongoing_owobot_event:
            return False
        return True

    def enabled_gem_types(self):
        cnf = self.settings.gemsToUse
        return {
            "huntGem": cnf["huntGem"],
            "empoweredGem": cnf["empoweredGem"],
            "luckyGem": cnf["luckyGem"],
            "specialGem": self.should_use_special_gem(),
        }

    async def use_gems(self, available_gems, gems_in_use=None, full=False):
        config = bot_control.settings_for(self.bot)
        allowed_tiers = gem_control.allowed_rarities(config)
        if not config.get("gemsEnabled", True) or not allowed_tiers or time.monotonic() < self.use_pending_until:
            return
        result = self.find_specific_gems_to_use(gems_in_use or (), available_gems)
        if result:
            command = dict(self.gem_cmd, cmd_arguments=" ".join(str(int(gem_id)) for gem_id in result))
            if not await self.bot.ch.put_queue(command, priority=True, wait=False):
                return
            self.use_after_id = max(self.last_hunt_id, self.last_inventory_id, self.last_use_reply_id)
            self.use_pending_until = time.monotonic() + 2 * config["responseTimeout"]
            self.pending_use_ids = tuple(result)
            self.clear_inventory_request()
            self.bot.stats.no_gem = False
            if self.bot.hunt_disabled:
                self.bot.hunt_disabled = False

        elif full and not any(
            count > 0 for tier, stock in available_gems.items() if tier not in allowed_tiers for count in stock.values()
        ):
            await self.bot.log("Không có đá quý phù hợp để dùng tự động.", "#924444")
            self.bot.stats.no_gem = True
            if not self.bot.hunt_disabled and self.settings.disableHuntIfNoGems:
                await self.bot.log("Tạm dừng săn vì không có đá quý phù hợp.", "#C51818")
                self.bot.hunt_disabled = True

    def fetch_gems_in_use(self, msg):
        header = msg.partition("\n")[0].lower().partition("hunt is empowered by")[2]
        active = {}
        understood = False
        for emoji in EMOJI.finditer(header):
            icon = GEM_ICON.fullmatch(emoji[1])
            counter = GEM_COUNTER.match(header, emoji.end())
            if not icon:
                if counter:
                    return [], False  # The unknown icon could be one of our active types.
                continue
            if icon[2] == "gem2":  # Legacy Patreon gems are not auto-equipped.
                understood |= counter is not None
                continue
            kind = GEM_TYPES[icon[2]]
            # Confirm expiration only for an explicit zero with a valid capacity.
            if not counter:
                active[kind] = GEM_TIERS[icon[1]]
                continue
            remaining, capacity = (int(value.replace(",", "")) for value in counter.groups())
            if 0 <= remaining <= capacity and capacity > 0:
                understood = True
            if remaining > 0 or capacity == 0:
                active[kind] = GEM_TIERS[icon[1]]
        if not understood:
            return [], False
        missing = any(allowed and kind not in active for kind, allowed in self.enabled_gem_types().items())
        return [{"gem_type": kind, "gem_tier": tier} for kind, tier in active.items()], missing

    def reduce_used_gems(self, used_gem_ids):
        for gem_id in used_gem_ids:
            tier, _ = GEM_IDS[gem_id]
            stock = self.available_gems.get(tier)
            if stock and stock.get(gem_id, 0) > 0:
                stock[gem_id] -= 1

    def find_gems_to_use(self, available_gems, occupied=()):
        config = bot_control.settings_for(self.bot)
        tiers = gem_control.allowed_rarities(config)
        tier_order = reversed(tiers) if config["gemOrder"] == "high_to_low" else tiers
        tier_order = tuple(tier for tier in tier_order if self.settings.tiers.get(tier, False))
        enabled_types = self.enabled_gem_types()
        selected = []
        for kind, enabled in enabled_types.items():
            if not enabled or kind in occupied:
                continue
            for tier in tier_order:
                gem_id = GEM_ID_BY_TYPE[tier, kind]
                if available_gems.get(tier, {}).get(gem_id, 0) > 0:
                    selected.append(gem_id)
                    break
        return selected or None

    def find_specific_gems_to_use(self, gems_in_use, available_gems):
        return self.find_gems_to_use(available_gems, {gem["gem_type"] for gem in gems_in_use})

    async def cog_load(self):
        if (
            not self.bot.settings_dict.commands.hunt.enabled
            or not self.settings.enabled
        ):
            try:
                asyncio.create_task(self.bot.unload_cog("core.cogs.gems"))
            except ExtensionNotLoaded:
                pass

    async def cog_unload(self):
        await self.bot.ch.remove_queue(id="gems")

    def clear_inventory_request(self):
        self.inventory_check = False
        self.inventory_deadline = 0
        self.inventory_after_id = 0
        self.cache_gems_in_use = []

    async def request_inventory(self, active_gems):
        if await self.bot.ch.put_queue(self.inv_cmd, priority=True, wait=False):
            self.inventory_check = True
            self.cache_gems_in_use = active_gems
            self.inventory_after_id = self.last_hunt_id
            self.inventory_deadline = time.monotonic() + 2 * bot_control.settings_for(self.bot)["responseTimeout"]

    def owns_reply(self, message, header):
        user = getattr(self.bot, "user", None)
        mentions = re.findall(r"<@!?([0-9]+)>", header)
        if mentions:
            return str(getattr(user, "id", None)) in mentions
        names = (self.bot.get_nick(message), getattr(user, "display_name", None), getattr(user, "name", None))
        plain = re.sub(r"[*~`]", "", header).casefold().strip()
        candidates = {plain, plain.lstrip("= "), plain.partition("|")[2].strip()}
        labels = {candidate.rstrip(", ") for candidate in candidates if candidate}
        return any(re.sub(r"[*~`]", "", name).casefold().strip() in labels for name in names if name)

    async def handle_hunt(self, message_id, header, empowered, now):
        if message_id <= max(self.last_hunt_id, self.last_use_reply_id):
            return
        self.last_hunt_id = message_id
        if now < self.use_pending_until:
            return
        if self.use_pending_until:
            self.use_pending_until = 0
            self.pending_use_ids = ()
            self.inventory_refresh_at = 0
        active_gems, required = self.fetch_gems_in_use(header) if empowered else ([], True)
        if self.inventory_check:
            if required:
                self.cache_gems_in_use = active_gems
            else:
                self.clear_inventory_request()
            return
        if required and gem_control.allowed_rarities(bot_control.settings_for(self.bot)):
            if now >= self.inventory_refresh_at:
                await self.request_inventory(active_gems)
            elif self.available_gems:
                await self.use_gems(self.available_gems, active_gems)

    async def handle_inventory(self, message_id, text, now):
        if message_id <= max(self.last_inventory_id, self.last_use_reply_id):
            return
        self.last_inventory_id = message_id
        self.available_gems = find_gems_available(text)
        self.inventory_refresh_at = now + 60
        if self.inventory_check and message_id > self.inventory_after_id:
            active_gems = self.cache_gems_in_use
            self.clear_inventory_request()
            await self.use_gems(self.available_gems, active_gems, full=not active_gems)

    def handle_use_reply(self, message_id, text):
        if message_id <= max(self.last_use_reply_id, self.use_after_id):
            return
        self.last_use_reply_id = message_id
        confirmed = {
            GEM_ID_BY_TYPE[tier.lower(), GEM_NAMES[kind.lower()]]
            for tier, kind in ACTIVATED_GEM.findall(text)
        }
        if message_id > self.last_inventory_id:
            self.reduce_used_gems(confirmed)
            if not self.pending_use_ids or confirmed != set(self.pending_use_ids):
                self.inventory_refresh_at = 0
        self.pending_use_ids = ()
        self.use_pending_until = 0

    @commands.Cog.listener()
    async def on_message(self, message):
        if (
            not gem_control.enabled(self.bot)
            or message.channel.id != self.bot.channel_id
            or message.author.id != self.bot.owo_bot_id
        ):
            return
        text = extract_message_text(message)
        first_line = text.partition("\n")[0]
        empowered = EMPOWERED_HUNT.search(first_line)
        hunt = empowered or PLAIN_HUNT.search(first_line)
        inventory = INVENTORY_TITLE.search(first_line)
        use_reply = USE_REPLY.search(first_line) if "gem" in first_line.casefold() else None
        marker = hunt or inventory or use_reply
        if not marker or not self.owns_reply(message, first_line[:marker.start()]):
            return

        async with self.message_lock:
            if not gem_control.enabled(self.bot):
                return
            now = time.monotonic()
            if self.inventory_check and now >= self.inventory_deadline:
                self.clear_inventory_request()
            if hunt:
                await self.handle_hunt(message.id, first_line, empowered is not None, now)
            elif inventory:
                await self.handle_inventory(message.id, text, now)
            else:
                self.handle_use_reply(message.id, text)


async def setup(bot):
    await bot.add_cog(Gems(bot))
