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

        arg = self.get_cmd_argument(name)
        if not arg:
            return None

        base = {
            "cmd_name": name,
            "cmd_arguments": arg,
            "prefix": True,
            # Sales wait for their next cooldown instead of response retries.
            "checks": name != "sell",
            "id": name,
        }
        return base

    def get_last_ran(self):
        return "sell" if self.sell_lastran >= self.sac_lastran else "sac"

    @staticmethod
    def normalize_content(content):
        content = re.sub(r"<a?:cowoncy:\d+>", "cowoncy", content, flags=re.I)
        content = re.sub(r"[*`~]", "", content).replace("\u2019", "'")
        return " ".join(content.casefold().split())

    def is_for_account(self, message, text):
        if re.search(rf"(?<!\d){self.bot.user.id}(?!\d)", text):
            return True
        names = (
            self.bot.get_nick(message),
            getattr(self.bot.user, "display_name", ""),
            getattr(self.bot.user, "name", ""),
        )
        return any(
            re.search(
                rf"(?<!\w){re.escape(self.normalize_content(name))}(?!\w)", text
            )
            for name in names
            if name and name.strip()
        )

    async def enqueue_sale(self, command):
        state = self.bot.ch.cmds_state["sell"]
        if self.bot.ch.should_not_send or state["in_queue"]:
            return False
        await self.bot.ch.put_queue(command)
        # put_queue returns None both when it queues and when it refuses a command.
        if not state["in_queue"]:
            return False
        self.sell_lastran = time.monotonic()
        return True

    async def emergency_sell(self, message):
        settings = getattr(self.animal_setting, "emergencySell", None)
        if not settings or not settings.enabled:
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
            }
            if await self.enqueue_sale(command):
                self._emergency_lastran = self.sell_lastran
                await self.bot.log(
                    f"Low Cowoncy: queued emergency animal sale ({arguments})",
                    "#afaf87",
                )

    @tasks.loop(seconds=2)
    async def initiate_loop(self):
        choices = ["sell", "sac"]
        self.bot.random.shuffle(choices)
        for cmd in choices:
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
                        await self.bot.ch.put_queue(cmd_data)
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
        if (
            message.channel.id != self.bot.cm.id
            or message.author.id != self.bot.owo_bot_id
        ):
            return

        content = self.normalize_content(message.content)
        money_error = INSUFFICIENT_MONEY.search(content)
        if money_error:
            if (
                not re.search(r"\b(?:wp|weapons?|shards?)\b", content)
                and self.is_for_account(message, content[: money_error.start()])
            ):
                await self.emergency_sell(message)
            return
        if not self.is_for_account(message, content):
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
