"""Run one friendly battle series for the two opted-in accounts at startup."""

import asyncio
from threading import Event, Lock

import discord

from core.battle_messages import accept_button, is_battle_result
from utils import bot_control, farm_control


class BattleStopped(Exception):
    pass


async def on_loop(loop, operation):
    if loop is asyncio.get_running_loop():
        return await operation
    try:
        future = asyncio.run_coroutine_threadsafe(operation, loop)
    except RuntimeError:
        operation.close()
        raise
    return await asyncio.wrap_future(future)


def player_names(client, channel):
    member = channel.guild.me
    return {
        name for user in (member, client.user)
        for name in (getattr(user, "nick", None), getattr(user, "global_name", None),
                     getattr(user, "display_name", None), getattr(user, "name", None))
        if name
    }


class StartupBattles:
    ROUNDS = 3
    WAIT_TO_SEND = 90
    WAIT_FOR_RESULT = 120

    def __init__(self, account_ids):
        self.account_ids = tuple(account_ids)
        self._ready = {}
        self._started = False
        self._lock = Lock()

    async def join(self, client):
        await client.wait_until_ready()
        account_id = str(client.user.id)
        with self._lock:
            if self._started or account_id not in self.account_ids:
                return
            self._ready[account_id] = (client, asyncio.get_running_loop())
            if len(self._ready) < 2:
                return
            self._started = True
            (first, first_loop), (second, second_loop) = (self._ready[key] for key in self.account_ids)
        await on_loop(first_loop, self._play(first, second, second_loop))

    def _playing_allowed(self, first, second):
        for client in (first, second):
            status = client.ch.command_handler_status
            if (not client.is_ready() or not bot_control.running_for(client)
                    or not farm_control.enabled("battle", client) or status.captcha or status.sleep
                    or not bot_control.get_account_overrides(str(client.user.id)).get("startupFriendlyBattles")):
                return False
        return True

    async def _play(self, first, second, second_loop):
        scope = (first.cm.id, second.cm.id, first.settings_dict.prefix)

        def allowed():
            return self._playing_allowed(first, second) and (first.cm.id, second.cm.id, first.settings_dict.prefix) == scope

        confirmed = 0
        try:
            await asyncio.wait_for(self._wait_for_teams(first, second, allowed), self.WAIT_TO_SEND)
            channel, receiver_channel = await asyncio.wait_for(self._shared_channel(first, second, second_loop), 30)
            sender_names = player_names(first, channel)
            receiver_names = player_names(second, receiver_channel)
            for _ in range(self.ROUNDS):
                await self._round(first, second, second_loop, channel, receiver_channel,
                                  sender_names, receiver_names, allowed)
                confirmed += 1
                await first.log(f"Đấu giao hữu khi khởi động · {confirmed}/{self.ROUNDS} trận đã có kết quả.")
        except BattleStopped as exc:
            await first.log(f"Đấu giao hữu kết thúc ở {confirmed}/{self.ROUNDS} trận. {exc}")
        except (TimeoutError, discord.DiscordException, RuntimeError):
            await first.log(f"Đấu giao hữu kết thúc ở {confirmed}/{self.ROUNDS} trận. Chưa nhận đủ phản hồi để tiếp tục.")

    async def _wait_for_teams(self, first, second, allowed):
        while allowed():
            if all(not bot_control.settings_for(client)["teamSetupEnabled"] or getattr(client, "_team_setup_ready", False)
                   for client in (first, second)):
                return
            await asyncio.sleep(.25)
        raise BattleStopped("Một tài khoản đang tạm dừng hoặc chưa sẵn sàng.")

    async def _shared_channel(self, first, second, second_loop):
        # The initiating account keeps the prefix of its configured guild.
        guild_id = first.cm.guild.id
        for channel_id in dict.fromkeys((first.cm.id, second.cm.id)):
            try:
                channel = await first._validate_dashboard_channel(str(channel_id))
                if channel.guild.id != guild_id:
                    continue
                receiver_channel = await on_loop(second_loop, self._receiver_channel(second, channel_id))
            except ValueError:
                continue
            return channel, receiver_channel
        raise BattleStopped("Hai tài khoản cần quyền gửi trong cùng một kênh.")

    async def _receiver_channel(self, client, channel_id):
        channel = await client._validate_dashboard_channel(str(channel_id))
        member = channel.guild.me or await channel.guild.fetch_member(client.user.id)
        if not channel.permissions_for(member).read_message_history:
            raise ValueError("Thiếu quyền đọc lời mời đấu giao hữu.")
        return channel

    async def _round(self, first, second, second_loop, channel, receiver_channel,
                     sender_names, receiver_names, allowed):
        prefix = first.settings_dict.prefix
        command = f"{prefix}b <@{second.user.id}> -display=compact"
        match = dict(channel_id=channel.id, owo_id=first.owo_bot_id,
                     sender_names=sender_names, receiver_names=receiver_names)
        invitation_filter = dict(**match, sender_id=first.user.id, receiver_id=second.user.id)
        invite, command_id = await asyncio.wait_for(
            self._invite(first, command, channel, invitation_filter, allowed), self.WAIT_TO_SEND,
        )
        result_after = max(invite.id, discord.utils.time_snowflake(discord.utils.utcnow()))
        accepting = Event()

        def completed(message):
            return accepting.is_set() and is_battle_result(message, after_id=result_after, sender_id=first.user.id, **match)

        results = [asyncio.ensure_future(first.wait_for("message", check=completed)),
                   asyncio.ensure_future(first.wait_for("message_edit", check=lambda _, after: completed(after)))]
        try:
            await asyncio.wait_for(on_loop(second_loop, self._accept(
                second, receiver_channel, invite.id, {**invitation_filter, "after_id": command_id}, allowed, accepting,
            )), self.WAIT_TO_SEND)
            done, _ = await asyncio.wait(results, timeout=self.WAIT_FOR_RESULT, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise BattleStopped("OwO chưa xác nhận kết quả trận vừa gửi.")
            for result in done:
                result.result()
        finally:
            for result in results:
                result.cancel()
            await asyncio.gather(*results, return_exceptions=True)

    async def _invite(self, client, command, channel, match, allowed):
        prefix = client.settings_dict.prefix
        while allowed() and client.settings_dict.prefix == prefix:
            if not client.response_guard.ready or farm_control.cooldown_remaining(client, "battle"):
                await asyncio.sleep(.25)
                continue
            floor = discord.utils.time_snowflake(discord.utils.utcnow())
            command_id = None

            def invited(message):
                nonlocal command_id
                if (message.author.id == client.user.id and message.channel.id == channel.id
                        and message.id > floor and message.content == command):
                    command_id = message.id
                return command_id is not None and accept_button(message, after_id=command_id, **match) is not None

            waiter = asyncio.ensure_future(client.wait_for("message", check=invited))
            try:
                sent = await client.send(command, channel=channel,
                                         automation_check=lambda: allowed() and client.settings_dict.prefix == prefix)
                if sent:
                    client.db.update_cmd_db("battle")
                    invitation = await asyncio.wait_for(waiter, bot_control.settings_for(client)["responseTimeout"])
                    return invitation, command_id
            finally:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            await asyncio.sleep(.25)
        raise BattleStopped("Một tài khoản đã dừng hoặc tiền tố lệnh đã đổi.")

    async def _accept(self, client, channel, invitation_id, match, allowed, accepting):
        while allowed():
            async with client._outgoing_lock:
                if (client.response_guard.ready and await client._wait_for_send_slot(channel=channel)
                        and client.response_guard.ready and allowed()):
                    invitation = await channel.fetch_message(invitation_id)
                    button = accept_button(invitation, **match)
                    if button is None:
                        raise BattleStopped("Lời mời giao hữu không còn hợp lệ.")
                    if allowed() and client.response_guard.ready:
                        accepting.set()
                        try:
                            await button.click()
                        except discord.InvalidData:
                            # A missing interaction acknowledgement can still leave a completed battle.
                            pass
                        return
            await asyncio.sleep(.25)
        raise BattleStopped("Một tài khoản đã dừng trước khi chấp nhận lời mời.")
