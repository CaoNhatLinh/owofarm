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

from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded

from core.cogs._BASE import BaseCog
from utils.gambling_control import GamblingLifecycle, bet_amount
from utils import bot_control
from utils.system.notification import notify

won_pattern = r"and won <:cowoncy:\d+> ([\d,]+)"
lose_pattern = r"bet <:cowoncy:\d+> ([\d,]+)"

"""
NOTE:
fix it spamming "won nothing"
"""


class Slots(GamblingLifecycle, BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.cmd = {
            "cmd_name": self.bot.alias["slots"]["normal"],
            "cmd_arguments": None,
            "prefix": True,
            "checks": True,
            "id": "slots",
        }
        self.turns_lost = 0
        self.exceeded_max_amount = False

        self.gamble_flags = {
            "goal_reached": False,
            "amount_exceeded": False,
            "no_balance": False,
        }

    @property
    def gamble_settings(self):
        return self.bot.settings_dict.gamble

    @property
    def settings(self):
        return self.bot.settings_dict.gamble.slots

    @property
    def cooldowns(self):
        return self.bot.settings_dict.cooldowns

    async def cog_load(self):
        if not self.settings.enabled:
            try:
                asyncio.create_task(self.bot.unload_cog("core.cogs.slots"))
            except ExtensionNotLoaded:
                pass
        else:
            self.start_gambling(self.start_slots(startup=True))

    async def cog_unload(self):
        await self.stop_gambling()

    async def start_slots(self, startup=False):
        if not self.gambling_enabled():
            return
        goal_settings = self.gamble_settings.goals
        try:
            if startup:
                await self.bot.sleep_till(self.cooldowns.briefCooldown)
            else:
                await self.bot.ch.remove_queue(id="slots")
                await self.bot.sleep(self.settings.get_cd())

            amount_to_gamble = bet_amount("slots", self.turns_lost, self.bot)

            # Goal system check
            if self.profit_goal_reached():
                if not self.gamble_flags["goal_reached"]:
                    self.gamble_flags["goal_reached"] = True
                    await self.bot.log(
                        f"goal reached - {self.bot.stats.gain_or_lose}/{goal_settings.amount}, stopping slots!",
                        "#4a270c",
                    )
                    notify(
                        f"goal reached - {self.bot.stats.gain_or_lose}/{goal_settings.amount}, stopping slots!",
                        "Slots - Goal reached",
                    )

                await self.wait_for_profit_goal()
                return await self.start_slots(startup=True)
            elif self.gamble_flags["goal_reached"]:
                self.gamble_flags["goal_reached"] = False

            # Balance check
            if self.balance_blocks(amount_to_gamble):
                if not self.gamble_flags["no_balance"]:
                    self.gamble_flags["no_balance"] = True
                    message = f"Tạm dừng Máy quay. Chờ OwO xác nhận đủ {amount_to_gamble:,} cowoncy cho ván tiếp theo."
                    await self.bot.log(message, "#4a270c")
                    notify(message, "Máy quay · Kiểm tra số dư")

                await self.wait_for_balance()
                return await self.start_slots(startup=True)
            elif self.gamble_flags["no_balance"]:
                await self.bot.log(
                    "OwO đã xác nhận đủ tiền cho lượt cược Máy quay tiếp theo.",
                    "#4a270c",
                )
                self.gamble_flags["no_balance"] = False

            allottedAmount = self.gamble_settings.allottedAmount
            # Allotted value check
            if self.loss_limit_blocks(amount_to_gamble):
                if not self.gamble_flags["amount_exceeded"]:
                    self.gamble_flags["amount_exceeded"] = True
                    await self.bot.log(
                        f"Alloted value ({allottedAmount}) exceeded, stopping slots!",
                        "#4a270c",
                    )
                    notify(
                        f"Alloted value ({allottedAmount}) exceeded, stopping slots!",
                        "Slots - Alloted value exceeded",
                    )

                await self.wait_for_loss_limit()
                return await self.start_slots(startup=True)
            elif self.gamble_flags["amount_exceeded"]:
                self.gamble_flags["amount_exceeded"] = False

            if amount_to_gamble > 250000:
                await self.bot.log(
                    f"Value to gamble ({amount_to_gamble}) exceeded 250k threshold, stopping slots!",
                    "#4a270c",
                )
                notify(
                    f"Value to gamble ({amount_to_gamble}) exceeded 250k threshold, stopping slots!",
                    "Slots - Exceeded 250k limit",
                )
                self.exceeded_max_amount = True
            else:
                self.cmd["cmd_arguments"] = str(amount_to_gamble)
                if self.gambling_enabled():
                    await self.bot.ch.put_queue(self.cmd)

        except Exception as e:
            await self.bot.log(f"Error - {e}, During slots start_slots()", "#c25560")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not self.gambling_enabled():
            return
        if before.author.id != 408785106942164992:
            return
        if before.channel.id != self.bot.channel_id:
            return
        if self.exceeded_max_amount:
            return
        nick = self.bot.get_nick(before.guild.me)

        if nick not in after.content:
            return

        if "slots" in after.content.lower():
            if not any(marker in after.content.lower() for marker in ("and won nothing", "and won")):
                return
            if not await self.finish_gambling_round(after):
                return
            if "and won nothing... :c" in after.content:
                """Lose cash"""
                match = int(
                    re.search(lose_pattern, after.content).group(1).replace(",", "")
                )

                self.bot.update_cash(match, reduce=True)
                self.bot.stats.gain_or_lose -= match
                self.loss_limit_blocks(0)

                self.turns_lost += 1
                await self.record_gambling_result("loss")
                await self.bot.log(
                    f"lost {match} in slots, net profit - {self.bot.stats.gain_or_lose}",
                    "#993f3f",
                )
                await self.start_slots()
                self.bot.db.update_gamble_db("losses")
            else:
                if (
                    "<:eggplant:417475705719226369>" in after.content.lower()
                    and "and won" in after.content.lower()
                ):
                    """Didn't lose case but earned nothing"""
                    await self.record_gambling_result("tie")
                    await self.bot.log("didn't win or lose slots", "#ffafaf")
                    await self.start_slots()

                elif "and won" in after.content.lower():
                    """won cash"""
                    won_match = int(
                        re.search(won_pattern, after.content).group(1).replace(",", "")
                    )
                    lose_match = int(
                        re.search(lose_pattern, after.content).group(1).replace(",", "")
                    )
                    profit = won_match - lose_match

                    self.bot.update_cash(profit)
                    self.bot.stats.gain_or_lose += profit
                    self.loss_limit_blocks(0)
                    await self.record_gambling_result("win")

                    self.turns_lost = 0
                    await self.bot.log(
                        f"won {won_match} in slots, net profit - {self.bot.stats.gain_or_lose}",
                        "#536448",
                    )
                    await self.start_slots()
                    self.bot.db.update_gamble_db("wins")


async def setup(bot):
    await bot.add_cog(Slots(bot))
