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

cmd = {"cmd_name": "daily", "prefix": True, "checks": True, "id": "daily"}
DAILY_REWARD = re.compile(r"Here is your daily \*\*<:cowoncy:\d+> ([\d,]+)")


class Daily(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self._next_daily = None
        self._last_daily_reply = 0

    @property
    def cooldowns(self):
        return self.bot.settings_dict.cooldowns

    async def start_daily(self, *, after_reply=False):
        if after_reply or not self.bot.should_run(await self.bot.db.fetch_cmd_lastran_time("daily")):
            await asyncio.sleep(self.bot.calc_time())  # Wait until the next Pacific midnight.
            await self.bot.sleep_till(self.cooldowns.moderateCooldown)
        else:
            await self.bot.sleep_till(self.cooldowns.briefCooldown)
        await self.bot.ch.put_queue(cmd, priority=True)

    def schedule_daily(self, *, after_reply=False):
        if self._next_daily is None or self._next_daily.done():
            self._next_daily = asyncio.create_task(self.start_daily(after_reply=after_reply))

    async def cog_load(self):
        if not self.bot.settings_dict.daily:
            try:
                asyncio.create_task(self.bot.unload_cog("core.cogs.daily"))
            except ExtensionNotLoaded:
                pass
        else:
            self.schedule_daily()

    async def cog_unload(self):
        if self._next_daily is not None:
            self._next_daily.cancel()
        await self.bot.ch.remove_queue(id="daily")

    @commands.Cog.listener()
    async def on_message(self, message):
        nick = self.bot.get_nick(message)

        if (message.channel.id != self.bot.cm.id or message.author.id != self.bot.owo_bot_id
                or not nick or nick not in message.content or message.id <= self._last_daily_reply):
            return
        reward = DAILY_REWARD.search(message.content)
        wait = "**⏱ |** Nu! **" in message.content and "! You need to wait" in message.content
        if not reward and not wait:
            return

        self._last_daily_reply = message.id
        self.bot.db.update_cmd_lastran_time("daily")
        if reward:
            self.bot.update_cash(int(reward[1].replace(",", "")))
        await self.bot.ch.remove_queue(id="daily")
        self.schedule_daily(after_reply=True)
        if reward and self.bot.global_settings_dict.webhook.enabled:
            await self.bot.send_webhook("daily_claim")


async def setup(bot):
    await bot.add_cog(Daily(bot))
