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
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from discord.ext import tasks

from core.cogs._BASE import BaseCog


class Commands(BaseCog):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot.ch.checks = []
        self.calc_time = timedelta(0)
        self.command_times = deque(maxlen=3)
        self.updated_between_cd = False
        self.last_msg = 0
        self._was_resting = False
        self._recover_farm = False
        self._inflight_command_id = None

    @property
    def command_handler_settings(self):
        return self.bot.settings_dict.cooldowns.commandHandler

    def sleep_required(self):
        """makes sure three commands are within 5 second limit"""
        now = time.time()

        while self.command_times and now - self.command_times[0] >= 5:
            """Command has to be within 5 second limit"""
            self.command_times.popleft()

        if len(self.command_times) < 3:
            return False, 0
        else:
            wait_time = max(0, 5 - (now - self.command_times[0]))
            return True, wait_time

    async def sleep_between_commands(self, betweenCommands):
        if betweenCommands[0] > self.bot.cm_slowmode_cd:
            await self.bot.sleep_till(betweenCommands)
        else:
            await self.bot.sleep_till(self.bot.cm_slowmode_cd, cd_list=False)
            if not self.updated_between_cd:
                await self.bot.log(
                    f"Channel has a cooldown of {self.bot.cm_slowmode_cd}s, increasing delay between commands!",
                    "#8f6b09",
                )
                self.updated_between_cd = True

    def construct_command(self, data, guild_id):
        prefix = self.bot.settings_dict.prefix if data.get("prefix") else ""

        if guild_id and guild_id != self.bot.cm.guild.id:
            # Revert
            prefix = "owo "

        return f"{prefix}{data['cmd_name']} {data.get('cmd_arguments') or ''}".rstrip()

    async def start_commands(self):
        await self.bot.sleep_till(
            self.bot.global_settings_dict.account.commandsHandlerStart
        )
        await self.bot.ch.shuffle_queue()
        await self.bot.wait_until_ready()
        self.send_commands.start()
        self.monitor_checks.start()

    async def cog_load(self):
        """Run join_previous_giveaways when bot is ready"""
        asyncio.create_task(self.start_commands())

    """send commands"""

    @tasks.loop()
    async def send_commands(self):
        from utils import bot_control, farm_control
        await bot_control.wait_until_running(getattr(self.bot, "_dashboard_account_id", None))
        await self.bot.response_guard.wait_ready()
        cmd = {}
        try:
            cnf = self.command_handler_settings
            priority, _, cmd = await self.bot.ch.queue.get()
            cmd_id = cmd.get("id")
            self._inflight_command_id = cmd_id
            from utils.gambling_control import enabled
            if not enabled(cmd_id, self.bot):
                self.bot.ch.cmds_state[cmd_id]["in_queue"] = False
                return
            if cmd_id == "owo" and not bot_control.settings_for(self.bot)["owoEnabled"]:
                self.bot.ch.cmds_state[cmd_id]["in_queue"] = False
                return
            if farm_control.cooldown_remaining(self.bot, cmd_id):
                handler = self.bot.ch
                async with handler._hold_or_create_lock():
                    handler.cmds_state[cmd_id]["in_queue"] = False
                    if cmd.get("checks") and not any(item.get("id") == cmd_id for item in handler.checks):
                        handler.checks.append(cmd)
                return
            custom_channel_id = cmd.get("channel")
            channel = None

            if custom_channel_id:
                try:
                    channel = await self.bot.fetch_channel(custom_channel_id)
                except Exception as e:
                    await self.bot.log(
                        f"Error - Failed to fetch channel with id {custom_channel_id}: {e}",
                        "#c25560",
                    )

            if priority != 0:
                while (
                    time.time() - self.bot.ch.cmds_state["global"]["last_ran"]
                ) < cnf.betweenCommands[0]:
                    await self.sleep_between_commands(cnf.betweenCommands)

            sleep_req, sleep_time = self.sleep_required()
            if sleep_req:
                await self.bot.log(
                    f"sleep required by {sleep_time}s (to prevent `slow down` message)",
                    "#8f6b09",
                )
                await self.bot.sleep_till([sleep_time, sleep_time + 0.4])
                self.command_times.clear()

            """Update Command state"""
            await self.bot.ch.upd_cmd_state(cmd_id)

            send_options = {}
            automation_checks = []
            if cmd.get("automation_check") is not None:
                automation_checks.append(cmd["automation_check"])
            seller = None
            if cmd.get("economy_action"):
                seller = self.bot.get_cog("Sell")
                if not seller or not seller.allows_queued_command(cmd):
                    return
                automation_checks.append(lambda: seller.allows_queued_command(cmd))
            if automation_checks:
                if not all(check() for check in automation_checks):
                    return
                send_options["automation_check"] = lambda: all(check() for check in automation_checks)

            """Append to checks"""
            if cmd.get("checks") and cmd_id:
                in_queue = await self.bot.ch.search_checks(id=cmd_id)
                if not in_queue:
                    async with self.bot.ch._hold_or_create_lock():
                        self.bot.ch.checks.append(cmd)

            if self.bot.settings_dict.useSlashCommands and cmd.get(
                "slash_cmd_name", False
            ):
                sent = await self.bot.slashCommandSender(
                    cmd["slash_cmd_name"],
                    self.bot.misc["command_info"][cmd_id]["log_color"],
                    channel=channel,
                    **send_options,
                )
            else:
                sent = await self.bot.send(
                    self.construct_command(
                        cmd, guild_id=channel.guild.id if channel else None
                    ),
                    self.bot.misc["command_info"][cmd_id]["log_color"],
                    channel=channel,
                    expect_response=bool(cmd.get("prefix")) and cmd_id not in {"owo", "customcommand", "levelgrind"},
                    **send_options,
                )
            if sent:
                self.bot.db.update_cmd_db(cmd_id)
                self.command_times.append(time.time())
                if seller:
                    seller.economy_command_sent(cmd)

        except Exception as e:
            await self.bot.log(
                f"Error - send_commands() loop: {e}. {cmd.get('cmd_name', None)}",
                "#c25560",
            )
            await self.sleep_between_commands(cnf.betweenCommands)
        finally:
            self._inflight_command_id = None

    @tasks.loop(seconds=1)
    async def monitor_checks(self):
        from utils import bot_control, farm_control
        try:
            if await self.bot.apply_dashboard_resume():
                self._recover_farm = True
            await self.bot.apply_dashboard_settings()
            self.bot.response_guard.gamble_profit = self.bot.stats.gain_or_lose
            self.bot.response_guard.gamble_streaks = self.bot.gamble_streaks.snapshot()
            from utils.coinflip_history import get_history
            self.bot.response_guard.coinflip_auto = get_history(self.bot).snapshot(bot_control.settings_for(self.bot)["coinflipHistoryWindow"])
            from utils.coinflip_probe import get_plan
            self.bot.response_guard.coinflip_auto["probePlan"] = get_plan(self.bot).snapshot()
            from utils.gambling_control import GAMES, loss_blocked, request_wallet_check, wallet_waiting
            self.bot.response_guard.gamble_loss_stopped = loss_blocked(self.bot)
            self.bot.response_guard.captcha = self.bot.ch.command_handler_status.captcha
            self.bot.response_guard.scheduled_sleep = self.bot.ch.command_handler_status.sleep
            self.bot.response_guard.tick()
            resting = self.bot.response_guard.cooling_down
            if resting and not self._was_resting:
                settings = bot_control.settings_for(self.bot)
                await self.bot.log(
                    f"OwO không phản hồi {self.bot.response_guard.misses} lần liên tiếp; nghỉ {settings['restMinutes']} phút.",
                    "#e5bb78",
                )
            elif self._was_resting and not resting:
                self._recover_farm = True
                await self.bot.log("Đã kết thúc nghỉ do mất phản hồi; tiếp tục thử lệnh.", "#bcf36b")
            self._was_resting = resting
            delay = self.command_handler_settings.readdingToQueue
            current_time = datetime.now(timezone.utc)
            if (
                not bot_control.running_for(self.bot)
                or self.bot.response_guard.cooling_down
                or self.bot.response_guard.pending
                or not self.bot.ch.command_handler_status.state
                or self.bot.ch.command_handler_status.sleep
                or self.bot.ch.command_handler_status.captcha
                or self.bot.ch.command_handler_status.hold_handler
            ):
                self.calc_time += current_time - getattr(
                    self, "last_check_time", current_time
                )
            else:
                if self._recover_farm:
                    await self.restore_farm_checks()
                    self._recover_farm = False
                await request_wallet_check(self.bot)
                for command in self.bot.ch.checks[:]:
                    kind = command["id"]
                    cnf = self.bot.ch.cmds_state[kind]
                    if (kind != self._inflight_command_id
                            and time.time() - cnf["last_ran"] > delay and not cnf["in_queue"]
                            and (kind not in GAMES or not wallet_waiting(self.bot, kind))
                            and not farm_control.cooldown_remaining(self.bot, kind)):
                        # A concurrent pause must not block this monitor or lose the retry.
                        await self.bot.ch.put_queue(command, wait=False, retry=True)

                self.calc_time = timedelta(0)
            self.last_check_time = current_time
        except Exception as e:
            await self.bot.log(f"Error - monitor_checks(): {e}", "#c25560")

    async def restore_farm_checks(self):
        from utils.farm_control import enabled

        handler = self.bot.ch
        async with handler._hold_or_create_lock():
            for kind, cog_name in (("hunt", "Hunt"), ("battle", "Battle")):
                cog = self.bot.get_cog(cog_name)
                if not cog or not cog.cmd.get("cmd_name") or not enabled(kind, self.bot):
                    continue
                if kind == "hunt" and self.bot.hunt_disabled:
                    continue
                if not handler.cmds_state[kind]["in_queue"] and not any(cmd.get("id") == kind for cmd in handler.checks):
                    handler.checks.append(dict(cog.cmd, removed=False))


async def setup(bot):
    await bot.add_cog(Commands(bot))
