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
from collections import deque

from discord.ext import commands, tasks

from core.cogs._BASE import BaseCog
from utils import bot_control, farm_control
from utils.gambling_control import invalidate_wallet

RARITY_MAP = {
    "c": "common",
    "u": "uncommon",
    "r": "rare",
    "e": "epic",
    "s": "special",  # special
    "m": "mythical",
    "g": "gem",
    "l": "legendary",
    "d": "distorted",
    "f": "fabled",
    "h": "hidden",
}

INSUFFICIENT_MONEY = re.compile(
    r"\b(?:you\s+(?:(?:don't|do not)\s+have\s+(?:enough|any)|"
    r"have\s+(?:insufficient|not enough|no))|insufficient|not enough)"
    r"\s+(?:cowoncy|cash|money)\b"
)
CASH_BALANCE = re.compile(r"\byou currently have\s+_*(\d+(?:,\d{3})*)_*\s+cowoncy\b")
NON_HUNT_COST = re.compile(r"\b(?:wp|weapons?|shards?|autohunt|huntbot|buy|cashout|gamble|coinflip|blackjack|slots|mines)\b")
CASH_COMMANDS = {"balance", "cash", "cowoncy", "credit", "currency", "money"}
SURPLUS_THRESHOLD = 5000
BALANCE_CHECK_INTERVAL = 60


def normalize_economy_content(content):
    content = re.sub(r"<a?:cowoncy:\d+>", "cowoncy", content, flags=re.I)
    content = re.sub(r"[*`~]", "", content).replace("\u2019", "'")
    return " ".join(content.casefold().split())


def is_economy_message_for_account(bot, message, text):
    if re.search(rf"(?<!\d){bot.user.id}(?!\d)", text):
        return True
    names = (bot.get_nick(message), getattr(bot.user, "display_name", ""), getattr(bot.user, "name", ""))
    return any(
        re.search(rf"(?<!\w){re.escape(normalize_economy_content(name))}(?!\w)", text)
        for name in names
        if name and name.strip()
    )


class Sell(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        # Wait a full sale cooldown after startup before the first sale.
        self.sell_lastran = time.monotonic()
        self.sac_lastran = 0
        self.startup = True
        self._sale_lock = asyncio.Lock()
        self._emergency_lastran = None
        self._emergency_message_ids = deque(maxlen=128)
        self._last_request = None
        self._last_balance_check = None
        self._surplus_balance = None

    @property
    def animal_setting(self):
        return self.bot.settings_dict.animal

    @property
    def sell_settings(self):
        return self.animal_setting.sell

    @property
    def sac_settings(self):
        return self.animal_setting.sac

    """def allocate_points(self, command: str, rarities: str):
        if command not in ("sell", "sac"):
            raise ValueError("Invalid command name")

        rarities_list = rarities.split()
        for item in rarities_list:
            self.__dict__[f"{command}_point"] += POINT_CHART[item]

    def calculate_allocation(self, command: str):
        if command not in ("sell", "sac"):
            raise ValueError("Invalid command name")
        cmds = ["sell", "sac"]
        cmds.pop(command)"""

    def get_cmd_argument(self, cmd):
        arg = getattr(self, f"{cmd}_settings").rarity.get_rarities()
        if self.startup:
            self.startup = False
            return arg

        arg_list = arg.split()
        filtered_items = [
            item
            for item in arg_list
            if (rarity := RARITY_MAP[item]) and self.bot.animal_rank_in_zoo[rarity]
            # https://www.geeksforgeeks.org/python/walrus-operator-in-python-3-8/
        ]
        arg = " ".join(filtered_items).strip()
        if arg != "":
            return " ".join(filtered_items)
        return None

    def get_command(self, name: str):
        if name not in ("sell", "sac"):
            raise ValueError("Invalid command name")
        if name == "sac" and not self.bot.cm:
            return None

        arg = self.get_cmd_argument(name)
        if not arg:
            return None

        base = {
            "cmd_name": name,
            "cmd_arguments": arg,
            "prefix": True,
            "checks": False,
            "id": name,
        }
        if name == "sac":
            base.update(economy_action="periodic-sacrifice", economy_channel=self.bot.cm.id)
        return base

    def get_last_ran(self):
        return "sell" if self.sell_lastran >= self.sac_lastran else "sac"

    def request_kind(self, content):
        prefix = self.bot.settings_dict.prefix
        aliases = getattr(self.bot, "alias", {})
        if farm_control.command_kind(content, prefix, aliases) == "hunt":
            return "hunt"
        for candidate in sorted({prefix, "owo ", "uwu "}, key=len, reverse=True):
            if not content.startswith(candidate):
                continue
            parts = content[len(candidate):].casefold().split()
            if parts:
                configured = aliases.get("cash", {}).get("normal", "cash")
                return "cash" if len(parts) == 1 and parts[0] in CASH_COMMANDS | {configured} else "other"
        return None

    def reply_matches_request(self, message, kind):
        if not self._last_request:
            return False
        request_kind, request_id, channel_id, deadline = self._last_request
        reference_id = getattr(getattr(message, "reference", None), "message_id", None)
        return (
            request_kind == kind and channel_id == message.channel.id
            and message.id > request_id and time.monotonic() <= deadline
            and (reference_id is None or reference_id == request_id)
        )

    def emergency_enabled(self):
        settings = getattr(self.animal_setting, "emergencySell", None)
        flags = bot_control.settings_for(self.bot)
        return bool(
            settings and flags.get("huntEmergencySellEnabled", settings.enabled)
            and flags.get("huntEnabled", True)
        )

    def surplus_enabled(self):
        flags = bot_control.settings_for(self.bot)
        return flags.get("zooSacrificeSurplusEnabled", False)

    def surplus_ready(self):
        flags = bot_control.settings_for(self.bot)
        if not flags.get("zooSacrificeSurplusEnabled", False):
            return False
        huntbot = self.bot.get_cog("Huntbot")
        launch = getattr(huntbot, "pending", None)
        return (
            not getattr(self.bot.response_guard, "huntbot_captcha", None)
            and (not launch or launch[0] != "start")
            and (not flags.get("teamSetupEnabled", False) or getattr(self.bot, "_team_setup_ready", False))
            and (not self.sac_lastran or time.monotonic() - self.sac_lastran > self.animal_setting.get_cd())
        )

    async def check_surplus_balance(self):
        if not self.bot.cm or not self.surplus_ready() or self.bot.ch.should_not_send:
            return
        now = time.monotonic()
        if self._last_balance_check is not None and now - self._last_balance_check < BALANCE_CHECK_INTERVAL:
            return
        handler = self.bot.ch
        if any(handler.cmds_state.get(kind, {}).get("in_queue") for kind in ("cash", "sell", "sac")):
            return
        alias = getattr(self.bot, "alias", {}).get("cash", {}).get("normal", "cash")
        command = {
            "cmd_name": alias,
            "prefix": True,
            "checks": False,
            "id": "cash",
            "economy_action": "surplus-check",
            "economy_channel": self.bot.cm.id,
        }
        if await handler.put_queue(command, wait=False):
            self._last_balance_check = now

    def allows_queued_command(self, command):
        if (not self.bot.cm or command["economy_channel"] != self.bot.cm.id
                or self.bot.ch.should_not_send or self._sale_lock.locked()):
            return False
        action = command["economy_action"]
        if action == "hunt-sale":
            return time.monotonic() <= command["economy_deadline"] and self.emergency_enabled()
        if action == "periodic-sacrifice":
            return self.sac_settings.enabled and not self.surplus_enabled()
        if action == "surplus-check":
            return self.surplus_ready()
        if action != "surplus-sacrifice" or not self.surplus_ready() or not self._surplus_balance:
            return False
        balance, response_id, deadline = self._surplus_balance
        stats = getattr(self.bot, "stats", None)
        return (
            response_id == command["economy_confirmation"]
            and time.monotonic() <= deadline
            and balance > SURPLUS_THRESHOLD
            and (not getattr(stats, "has_updated_balance", False) or stats.balance > SURPLUS_THRESHOLD)
        )

    def economy_command_sent(self, command):
        if command["economy_action"] == "surplus-sacrifice":
            self.sac_lastran = time.monotonic()
            self._surplus_balance = None

    async def sacrifice_surplus_animals(self, message, balance):
        async with self._sale_lock:
            handler = self.bot.ch
            if not self.surplus_ready() or balance <= SURPLUS_THRESHOLD or handler.should_not_send:
                return
            if any(handler.cmds_state[kind]["in_queue"] for kind in ("sell", "sac")):
                return
            command = {
                "cmd_name": "sac",
                "cmd_arguments": "all",
                "prefix": True,
                "checks": False,
                "id": "sac",
                "economy_action": "surplus-sacrifice",
                "economy_channel": message.channel.id,
                "economy_confirmation": message.id,
            }
            self._surplus_balance = (balance, message.id, time.monotonic() + BALANCE_CHECK_INTERVAL + 10)
            if await handler.put_queue(command, quick=True, wait=False):
                await self.bot.log(
                    f"Đã xác nhận {balance:,} cowoncy và xếp lệnh hiến tế toàn bộ thú trong zoo.",
                    "#afaf87",
                )

    async def enqueue_sale(self, command):
        state = self.bot.ch.cmds_state["sell"]
        if self.bot.ch.should_not_send or state["in_queue"]:
            return False
        await self.bot.ch.put_queue(command, wait=False)
        # put_queue returns None both when it queues and when it refuses a command.
        if not state["in_queue"]:
            return False
        self.sell_lastran = time.monotonic()
        return True

    async def emergency_sell(self, message):
        settings = getattr(self.animal_setting, "emergencySell", None)
        if not self.emergency_enabled():
            return
        # Even an invalid/custom configuration must never sell above Rare.
        arguments = " ".join(
            code
            for code in ("c", "u", "r")
            if RARITY_MAP[code] in settings.rarities
        )
        if not arguments:
            return
        async with self._sale_lock:
            if message.id in self._emergency_message_ids:
                return
            self._emergency_message_ids.append(message.id)
            now = time.monotonic()
            if (
                self._emergency_lastran is not None
                and now - self._emergency_lastran < settings.retryCooldown
            ):
                return
            command = {
                "cmd_name": "sell",
                "cmd_arguments": arguments,
                "prefix": True,
                "checks": False,
                "id": "sell",
                "economy_action": "hunt-sale",
                "economy_channel": message.channel.id,
                "economy_deadline": now + BALANCE_CHECK_INTERVAL + 10,
            }
            if await self.enqueue_sale(command):
                self._emergency_lastran = self.sell_lastran
                await self.bot.log(
                    f"Low Cowoncy: queued emergency animal sale ({arguments})",
                    "#afaf87",
                )

    @tasks.loop(seconds=2)
    async def initiate_loop(self):
        await self.check_surplus_balance()
        choices = ["sell", "sac"]
        self.bot.random.shuffle(choices)
        for cmd in choices:
            if cmd == "sac" and self.surplus_enabled():
                continue
            if not getattr(self, f"{cmd}_settings").enabled:
                # skip disabled ones
                continue
            last_ran = self.__dict__[f"{cmd}_lastran"]
            cd = self.animal_setting.get_cd()
            gap = time.monotonic() - last_ran
            if last_ran == 0 or gap > cd:
                cmd_data = self.get_command(cmd)
                if cmd_data:
                    await self.bot.sleep_till([10, 15])
                    if cmd == "sell":
                        async with self._sale_lock:
                            # An emergency sale may have reset the timer while asleep.
                            if time.monotonic() - self.sell_lastran > cd:
                                await self.enqueue_sale(cmd_data)
                    else:
                        async with self._sale_lock:
                            if self.sac_settings.enabled and not self.surplus_enabled():
                                if await self.bot.ch.put_queue(cmd_data, wait=False):
                                    self.sac_lastran = time.monotonic()

            # To prevent sell and sac being send right after
            await self.bot.sleep_till([1, 2])

    async def cog_load(self):
        # start loop, cog will stay awake due to the necessity to calculate value
        self.initiate_loop.start()

    async def cog_unload(self):
        # this shouldn't get removed since its supposed to run.
        await self.bot.ch.remove_queue(id="sell")
        await self.bot.ch.remove_queue(id="sac")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.bot.cm or message.channel.id != self.bot.cm.id:
            return
        if message.author.id == self.bot.user.id:
            kind = self.request_kind(message.content)
            if kind and (not self._last_request or message.id > self._last_request[1]):
                timeout = bot_control.settings_for(self.bot).get("responseTimeout", 20)
                self._last_request = (kind, message.id, message.channel.id, time.monotonic() + timeout)
                if self._surplus_balance and message.id > self._surplus_balance[1]:
                    self._surplus_balance = None
            return
        if message.author.id != self.bot.owo_bot_id:
            return

        content = normalize_economy_content(message.content)
        money_error = INSUFFICIENT_MONEY.search(content)
        if money_error:
            if (
                self.reply_matches_request(message, "hunt")
                and not NON_HUNT_COST.search(content[money_error.start():])
                and is_economy_message_for_account(self.bot, message, content[:money_error.start()])
            ):
                self._last_request = None
                invalidate_wallet(self.bot, message.id)
                await self.emergency_sell(message)
            return
        balance = CASH_BALANCE.search(content)
        if balance:
            if self.reply_matches_request(message, "cash") and is_economy_message_for_account(self.bot, message, content[:balance.start()]):
                self._last_request = None
                self._surplus_balance = None
                await self.sacrifice_surplus_animals(message, int(balance[1].replace(",", "")))
            return
        if not is_economy_message_for_account(self.bot, message, content):
            return

        if (
            message.channel.id == self.bot.cm.id
            and message.author.id == self.bot.owo_bot_id
        ):
            if (
                "for a total of **<:cowoncy:416043450337853441>"
                in message.content.lower()
            ):
                await self.bot.ch.remove_queue(id="sell")

                if self.bot.settings_dict.cashCheck:
                    try:
                        self.bot.update_cash(
                            int(
                                re.search(
                                    r"for a total of \*\*<:cowoncy:\d+> ([\d,]+)",
                                    message.content,
                                )
                                .group(1)
                                .replace(",", "")
                            )
                        )
                    except Exception:
                        await self.bot.log(
                            "failed to fetch cowoncy from sales", "#af0087"
                        )

            elif (
                "sacrificed" in message.content
                and "for a total of" in message.content.lower()
            ):
                await self.bot.ch.remove_queue(id="sac")

            elif "you don't have enough animals! >:c" in message.content.lower():
                # May want to improve this later..
                await self.bot.ch.remove_queue(id=self.get_last_ran())


async def setup(bot):
    await bot.add_cog(Sell(bot))
