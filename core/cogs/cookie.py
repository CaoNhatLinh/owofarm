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
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone

from discord.ext import commands
from discord.utils import time_snowflake

from core.cogs._BASE import BaseCog
from utils import bot_control

_POLL_SECONDS = 2
_REPLY_TIMEOUT = 20
_COOKIE_SENT = re.compile(
    r"\*\*<a:cookieeat:423020737364885525> \| <@!?(\d+)>\*\*! "
    r"You got a (?:lemon )?cookie from \*\*<@!?(\d+)>\*\*! \*nom nom nom c:<\*"
)
_COOKIE_WAIT = re.compile(
    r"\*\*🚫 \| (.+)\*\*, Nu! You need to wait \*\*"
    r"(?:[01]?\d|2[0-3])H [0-5]?\dM [0-5]?\dS\*\*"
)


@dataclass(frozen=True)
class _Target:
    channel_id: int
    recipient_id: int
    prefix: str
    ping: bool


@dataclass
class _Attempt:
    target: _Target
    command: str
    reply: asyncio.Future
    after_id: int | None = None
    sent_id: int | None = None


class Cookie(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self._task = None
        self._attempt = None
        self._last_attempt = 0

    @property
    def settings(self):
        return self.bot.settings_dict.commands.cookie

    def _target(self):
        channel = getattr(self.bot, "cm", None)
        user = self.bot.user
        settings = self.settings
        recipient = str(settings.user_id)
        if not settings.enabled or channel is None or user is None:
            return None
        if not re.fullmatch(r"[0-9]{1,20}", recipient):
            return None
        recipient_id = int(recipient)
        if not 0 < recipient_id < 1 << 64 or recipient_id == user.id:
            return None
        if channel.id != self.bot._configured_dashboard_channel():
            return None
        return _Target(channel.id, recipient_id, self.bot.settings_dict.prefix, settings.ping_user)

    def _can_send(self, target):
        return (
            self._target() == target
            and self.bot.is_ready()
            and not self.bot.response_guard.channel_error
            and not self.bot.ch.should_not_send
        )

    async def _run(self):
        await self.bot.wait_until_ready()
        await self.bot.log("Đã bật gửi cookie hằng ngày.")
        self._last_attempt = await self.bot.db.fetch_cmd_lastran_time("cookie") or 0
        while True:
            if not self.bot.should_run(self._last_attempt):
                await asyncio.sleep(max(1, self.bot.calc_time()))
                continue
            target = self._target()
            if target is None or not self._can_send(target) or not self.bot.response_guard.ready:
                await asyncio.sleep(_POLL_SECONDS)
                continue
            await self.bot.sleep_till(self.bot.settings_dict.cooldowns.moderateCooldown)
            if self._can_send(target) and await self._send_cookie(target):
                continue
            await asyncio.sleep(_POLL_SECONDS)

    def _record_attempt(self):
        # This stamp prevents reissuing an uncertain delivery on restart.
        self._last_attempt = self.bot.time_in_seconds()
        self.bot.db.update_cmd_lastran_time("cookie")

    async def _send_cookie(self, target):
        alias = self.bot.alias["cookie"]["normal"]
        recipient = f"<@{target.recipient_id}>" if target.ping else str(target.recipient_id)
        attempt = _Attempt(target, f"{target.prefix}{alias} {recipient}", asyncio.get_running_loop().create_future())
        self._attempt = attempt

        def can_send():
            if not self._can_send(target):
                return False
            # The normal transport checks again immediately before Discord sends.
            attempt.after_id = time_snowflake(datetime.now(timezone.utc))
            return True

        try:
            try:
                sent = await self.bot.send(
                    attempt.command, channel=self.bot.cm, expect_response=True, automation_check=can_send,
                )
            except asyncio.CancelledError:
                if attempt.after_id is not None:
                    self._record_attempt()
                raise
            except Exception:
                if attempt.after_id is None:
                    return False
                self._record_attempt()
                await self.bot.log("Chưa xác nhận được lượt gửi cookie hôm nay.")
                return True
            if not sent:
                return False
            self._record_attempt()
            result = await self._wait_reply(attempt)
            if result == "sent":
                await self.bot.log("Đã gửi cookie hằng ngày.")
            elif result == "cooldown":
                await self.bot.log("Cookie hôm nay đã được sử dụng.")
            elif self._target() == target:
                await self.bot.log("Chưa xác nhận được lượt gửi cookie hôm nay.")
            return True
        finally:
            attempt.reply.cancel()
            self._attempt = None

    async def _wait_reply(self, attempt):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _REPLY_TIMEOUT
        while self._target() == attempt.target and bot_control.running_for(self.bot):
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            done, _ = await asyncio.wait({attempt.reply}, timeout=min(_POLL_SECONDS, remaining))
            if done:
                return attempt.reply.result()
        return None

    async def cog_load(self):
        if self.settings.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run())

    async def cog_unload(self):
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    @commands.Cog.listener()
    async def on_message(self, message):
        attempt = self._attempt
        if (attempt is None or attempt.reply.done() or attempt.after_id is None
                or message.channel.id != attempt.target.channel_id or message.id < attempt.after_id
                or self._target() != attempt.target):
            return
        if message.author.id == self.bot.user.id and message.content == attempt.command:
            if attempt.sent_id is None:
                attempt.sent_id = message.id
            return
        if message.author.id != self.bot.owo_bot_id or attempt.sent_id is None or message.id <= attempt.sent_id:
            return
        reference = getattr(getattr(message, "reference", None), "message_id", None)
        if reference is not None and reference != attempt.sent_id:
            return

        success = _COOKIE_SENT.fullmatch(message.content)
        if success and (int(success[1]), int(success[2])) == (attempt.target.recipient_id, self.bot.user.id):
            attempt.reply.set_result("sent")
            return
        cooldown = _COOKIE_WAIT.fullmatch(message.content)
        if cooldown and self._owns_cooldown(message, cooldown[1], reference):
            attempt.reply.set_result("cooldown")

    def _owns_cooldown(self, message, sender_name, reference):
        guild = getattr(message, "guild", None)
        if not guild or sender_name != self.bot.get_nick(message):
            return False
        if reference is not None:
            return True
        return not any(
            member.id != self.bot.user.id and member.display_name == sender_name
            for member in guild.members
        )


async def setup(bot):
    await bot.add_cog(Cookie(bot))
