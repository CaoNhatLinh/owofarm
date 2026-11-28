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
# any later version.

import re
from dataclasses import dataclass, field
from time import monotonic, time

from discord.ext import commands, tasks

from core.cogs._BASE import BaseCog
from utils import bot_control
from utils.config_models.settings import HUNTBOT_TRAITS
from utils.huntbot.hbCalc import allocate_essence


REPLY_TIMEOUT = 45
BALANCE_RECHECK = 60
DETAIL_MAX_AGE = 120
MAX_UPGRADES_PER_HUNT = len(HUNTBOT_TRAITS)
SPENT_OWNER = re.compile(r"^.+?\|\s*BEEP BOOP\.\s+(?P<name>.+?),\s*YOU SPENT\b", re.I)


def _amount(value):
    return int(value.replace(",", ""))


def _remaining(text):
    units = {"D": 86400, "H": 3600, "M": 60}
    amounts = re.findall(r"(\d+)\s*([DHM])(?=\d|\b)", text.upper())
    return sum(int(quantity) * units[unit] for quantity, unit in amounts)


def _shape_stake(budget, balance, max_cost, cost):
    if not (cost and max_cost):
        return 0
    available = min(budget, balance, max_cost)
    return max(0, available // cost * cost)


@dataclass
class HuntbotPanel:
    max_cost: int | None = None
    cost: int | None = None
    remaining: int | None = None
    essence: int | None = None
    levels: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, fields):
        panel = cls()
        for field in fields:
            name = field.name.casefold()
            if "huntbot is currently hunting" in name:
                panel.remaining = max(60, _remaining(field.value.splitlines()[0])) if field.value else 60
            elif "animal essence" in name:
                essence = re.search(r"`([\d,]+)`", field.name)
                maximum = re.search(r"Current Max Autohunt:.*?for\s+([\d,]+)\s+cowoncy", field.value, re.I | re.S)
                panel.essence = _amount(essence[1]) if essence else None
                panel.max_cost = _amount(maximum[1]) if maximum else None
            else:
                trait = next((candidate for candidate in HUNTBOT_TRAITS if re.search(fr"\b{candidate}\b", name)), None)
                if trait is None and "experience" in name:
                    trait = "exp"
                if trait is None:
                    continue
                if trait == "cost":
                    cost = re.search(r"`([\d,]+)\b", field.name)
                    panel.cost = _amount(cost[1]) if cost else None
                level = re.search(r"Lvl\s+(\d+)\s+\[(MAX|[\d,]+/\s*[\d,]+)\]", field.value, re.I)
                if level:
                    progress = level[2].split("/", 1)[0]
                    panel.levels[trait] = (int(level[1]), 0 if progress.upper() == "MAX" else _amount(progress))
        return panel


class Huntbot(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.action_at = 0
        self.active_until = 0
        self.pending = None
        self.panel = None
        self.panel_at = 0
        self.balance = None
        self.balance_at = 0
        self.upgrade_count = 0
        self.captcha = None
        self.channel_id = None
        self.last_spent_message = None

    @property
    def settings(self):
        return self.bot.settings_dict.commands.huntbot

    async def cog_load(self):
        self.check_huntbot.start()

    async def cog_unload(self):
        self.check_huntbot.cancel()

    def _publish(self, state, amount=None):
        panel = self.panel
        wait_until = self.active_until if state == "hunting" else self.action_at
        next_attempt = None
        if wait_until and state in {"balance", "checking", "hunting", "upgrading", "unavailable"}:
            next_attempt = time() + max(0, wait_until - monotonic())
        self.bot.response_guard.huntbot_captcha = self.captcha
        self.bot.response_guard.huntbot_status = {
            "state": state,
            "maxCost": panel.max_cost if panel else None,
            "cost": panel.cost if panel else None,
            "amount": amount,
            "nextAttemptAt": next_attempt,
        }

    def _team_ready(self, config):
        return not config.get("teamSetupEnabled") or getattr(self.bot, "_team_setup_ready", False)

    def _stake(self, config):
        if (self.balance is None or self.panel is None
                or monotonic() - min(self.balance_at, self.panel_at) > DETAIL_MAX_AGE):
            return None
        stats = self.bot.stats
        # Other OwO activity can spend currency between HuntBot and the balance reply.
        balance = min(self.balance, stats.balance) if stats.has_updated_balance else self.balance
        budget = self.panel.max_cost if config.get("huntbotMax") else self.settings.cashToSpend
        return _shape_stake(budget, balance, self.panel.max_cost, self.panel.cost)

    def _upgrade(self, config):
        if (not config.get("huntbotUpgradeEnabled") or self.upgrade_count >= MAX_UPGRADES_PER_HUNT
                or self.panel is None or not self.panel.essence):
            return None
        upgrader = self.settings.upgrader
        details = {"essence": self.panel.essence}
        for trait in upgrader.get_enabled_traits():
            if trait in self.panel.levels:
                level, invested = self.panel.levels[trait]
                details[trait] = {"enabled": True, "current_level": level, "invested": invested}
        allocations = allocate_essence(details, upgrader.weights)
        return next(((trait, amount) for trait, amount in allocations.items() if amount), None)

    def _can_send(self, request, channel, prefix):
        config = bot_control.settings_for(self.bot)
        if (not config.get("huntbotEnabled") or not self._team_ready(config) or self.captcha is not None
                or self.bot.ch.should_not_send or self.pending is not request or self.bot.cm.id != channel.id
                or config.get("prefix", prefix) != prefix):
            return False
        action, amount = request
        if action == "start":
            return self.active_until <= monotonic() and self._stake(config) == amount
        if action == "upgrade":
            return (self.active_until <= monotonic() and self.panel is not None
                    and monotonic() - self.panel_at <= DETAIL_MAX_AGE
                    and config.get("huntbotUpgradeEnabled", False))
        return True

    async def _request(self, action, arguments="", amount=None):
        channel = self.bot.cm
        command = {"cash": "cash", "upgrade": "upgrade"}.get(action, "huntbot")
        state = {"cash": "balance", "upgrade": "upgrading", "start": "ready"}.get(action, "checking")
        request = (action, amount)
        self.pending = request
        self.action_at = monotonic() + REPLY_TIMEOUT
        self._publish(state, amount)
        name = self.bot.alias[command]["normal"]
        prefix = self.bot.settings_dict.prefix
        try:
            sent = await self.bot.send(
                f"{prefix}{name} {arguments}".rstrip(),
                self.bot.misc["command_info"][command]["log_color"],
                channel=channel, expect_response=True,
                automation_check=lambda: self._can_send(request, channel, prefix),
            )
        except Exception:
            if self.pending is request:
                self.pending = None
                self.panel = None
            raise
        if not sent and self.pending is request:
            self.pending = None
            self.action_at = monotonic() + 3

    @tasks.loop(seconds=1)
    async def check_huntbot(self):
        try:
            await self.step()
        except Exception as exc:
            self.action_at = monotonic() + REPLY_TIMEOUT
            await self.bot.log(f"HuntBot: chưa thể gửi lệnh ({type(exc).__name__}).", "#c25560")

    async def step(self):
        config = bot_control.settings_for(self.bot)
        channel = self.bot.cm
        if not config.get("huntbotEnabled"):
            self.pending = None
            self.panel = None
            self.action_at = 0
            self._publish("disabled")
            return
        if self.captcha is not None:
            self._publish("captcha")
            return
        if not self._team_ready(config):
            self._publish("waiting-team")
            return
        if channel is None or not bot_control.running_for(self.bot):
            self._publish("paused")
            return
        if self.channel_id != channel.id:
            self.channel_id = channel.id
            self.panel = None
            self.pending = None
            self.action_at = 0

        now = monotonic()
        if now < self.active_until:
            self._publish("hunting")
            return
        if now < self.action_at or self.bot.ch.should_not_send or not self.bot.response_guard.ready:
            return
        if self.pending is not None:
            self.pending = None
            self.panel = None
        if self.active_until:
            self.active_until = 0
            self.upgrade_count = 0
            self.panel = None
        if self.panel is None or now - self.panel_at > DETAIL_MAX_AGE:
            await self._request("status")
            return
        if not self.panel.max_cost or not self.panel.cost:
            self.panel = None
            self.action_at = now + REPLY_TIMEOUT
            self._publish("unavailable")
            return
        upgrade = self._upgrade(config)
        if upgrade is not None:
            trait, essence = upgrade
            await self._request("upgrade", f"{trait} {essence}")
            return
        stake = self._stake(config)
        if stake is None:
            await self._request("cash")
        elif stake == 0:
            self.balance = None
            self.action_at = now + BALANCE_RECHECK
            self._publish("balance", 0)
        else:
            await self._request("start", str(stake), stake)

    def _own_message(self, message):
        first_line = message.content.partition("\n")[0]
        plain = re.sub(r"[*`~]", "", first_line)
        spent = SPENT_OWNER.match(plain)
        if spent:
            header = spent["name"].strip()
        else:
            header = first_line.split("**,", 1)[0] if "**," in first_line else first_line.partition(",")[0]
            header = header.split("|", 1)[-1].strip(" *`~_")
        mentioned = re.findall(r"<@!?(\d+)>", header)
        if mentioned:
            return str(self.bot.user.id) in mentioned
        names = (self.bot.get_nick(message), getattr(self.bot.user, "display_name", None), getattr(self.bot.user, "name", None))
        return header.casefold() in {
            (re.sub(r"[*`~]", "", name).strip() if spent else name.strip(" *`~_")).casefold()
            for name in names if name
        }

    def _own_panel(self, message, embed):
        nick = self.bot.get_nick(message)
        author = embed.author
        if not author or not author.name:
            return False
        avatar = re.search(r"(?:users|avatars)/(\d+)/", str(getattr(author, "icon_url", "")))
        if avatar:
            return avatar[1] == str(self.bot.user.id) and any(
                "current max autohunt" in field.value.casefold() for field in embed.fields
            )
        return bool(nick and author.name.casefold() == f"{nick}'s HuntBot".casefold())

    def _observe_active(self, duration):
        self.captcha = None
        self.pending = None
        self.active_until = monotonic() + max(60, duration)
        self._publish("hunting")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.bot.cm or message.author.id != self.bot.owo_bot_id:
            return
        challenge_channel = self.captcha and self.captcha["channelId"]
        if message.channel.id != self.bot.cm.id and str(message.channel.id) != challenge_channel:
            return
        if not bot_control.settings_for(self.bot).get("huntbotEnabled") and self.captcha is None:
            return

        if self._own_message(message):
            content = message.content.casefold()
            challenged = any(marker in content for marker in ("here is your password", "please include your password", "wrong password"))
            if challenged and "{password}" in content:
                was_pending = self.captcha is not None
                amount = re.search(r"(?:autohunt|huntbot|\bhb|\bah)\s+([\d,]+)\s+\{password\}", content)
                self.captcha = {
                    "guildId": str(message.guild.id), "channelId": str(message.channel.id),
                    "messageId": str(message.id), "amount": _amount(amount[1]) if amount else None,
                }
                self.pending = None
                self._publish("captcha")
                if not was_pending:
                    await self.bot.log("HuntBot đang chờ bạn nhập mã xác minh trong Discord.", "#afaf87")
                return

            spent = re.search(r"you spent\s+([\d,]+)\s+cowoncy", content)
            timer = re.search(r"(?:back in|return in|time to be back:)\s*((?:\d+\s*[dhm]\s*)+)", content)
            if spent and (timer or "animals" in content):
                if self.last_spent_message == message.id:
                    return
                self.last_spent_message = message.id
                self.bot.update_cash(_amount(spent[1]), reduce=True)
                self.balance = None
                self._observe_active(_remaining(timer[1]) if timer else 0)
                return

            if "you successfully upgraded" in content:
                if self.pending and self.pending[0] == "upgrade":
                    self.upgrade_count += 1
                    self.pending = None
                self.panel = None
                self.action_at = monotonic() + self.settings.upgrader.get_cd()
                return

            cash = re.search(r"you currently have[^\d]*([\d,]+)\s+cowoncy", content)
            if cash:
                self.balance = _amount(cash[1])
                self.balance_at = monotonic()
                if self.pending and self.pending[0] == "cash":
                    self.pending = None
                    self.action_at = monotonic()
                return

            if self.pending and self.pending[0] == "start" and "don't have enough cowoncy" in content:
                self.pending = None
                self.balance = None
                self.action_at = monotonic() + BALANCE_RECHECK
                self._publish("balance", 0)
                return

        for embed in message.embeds:
            if not self._own_panel(message, embed):
                continue
            self.panel = HuntbotPanel.parse(embed.fields)
            self.panel_at = monotonic()
            if self.panel.remaining is not None:
                self._observe_active(self.panel.remaining)
            elif self.pending and self.pending[0] == "status":
                self.pending = None
                self.action_at = monotonic()
            return


async def setup(bot):
    await bot.add_cog(Huntbot(bot))
