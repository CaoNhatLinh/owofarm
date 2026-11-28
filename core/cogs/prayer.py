"""Schedule the selected account's prayer through the shared command transport."""

import asyncio
import time

from discord import HTTPException
from discord.ext import tasks

from core.cogs._BASE import BaseCog
from utils import bot_control
from utils.command_timing import command_timing

PRAYER_INTERVAL = 300


class Prayer(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.next_prayer = 0.0

    def target(self):
        settings = bot_control.settings_for(self.bot)
        channel = self.bot.cm
        if (not settings["prayEnabled"] or channel is None or not self.bot.is_ready()
                or channel.id != self.bot._configured_dashboard_channel()
                or self.bot.response_guard.channel_error or self.bot.ch.should_not_send):
            return None
        message = f"{self.bot.settings_dict.prefix}pray"
        recipient = settings["prayRecipientId"]
        if recipient and recipient != str(self.bot.user.id):
            message += f" <@{recipient}>"
        return channel, message

    @tasks.loop(seconds=2)
    async def send_prayer(self):
        if time.monotonic() < self.next_prayer:
            return
        target = self.target()
        if target is None or not self.bot.response_guard.ready:
            return
        channel, message = target
        command, cooldown = command_timing(self.bot, message)
        if self.bot.response_guard.send_pacing.remaining(0, command, cooldown) > 0:
            return
        try:
            # A prayer for another user can mention only the recipient in OwO's reply.
            sent = await self.bot.send(
                message, channel=channel,
                automation_check=lambda: self.target() == target,
            )
        except (HTTPException, OSError, asyncio.TimeoutError) as exc:
            self.next_prayer = time.monotonic() + PRAYER_INTERVAL
            await self.bot.log(f"Chưa xác nhận được lượt cầu nguyện ({type(exc).__name__}).")
        else:
            if sent:
                self.next_prayer = time.monotonic() + PRAYER_INTERVAL
                self.bot.db.update_cmd_db("pray")

    async def cog_load(self):
        self.send_prayer.start()

    async def cog_unload(self):
        self.send_prayer.cancel()


async def setup(bot):
    await bot.add_cog(Prayer(bot))
