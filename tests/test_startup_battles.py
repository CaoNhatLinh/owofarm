import asyncio
import unittest
from collections import defaultdict
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import discord

from core.startup_battles import StartupBattles
from utils import bot_control


class Client:
    def __init__(self, account_id, name, channel_id):
        self.user = NS(id=account_id, name=name)
        self.cm = NS(id=channel_id, guild=NS(id=1, me=self.user))
        self.owo_bot_id = 900
        self.settings_dict = NS(prefix="o")
        self.ch = NS(command_handler_status=NS(captcha=False, sleep=False))
        self._outgoing_lock = asyncio.Lock()
        self.db = NS(update_cmd_db=Mock())
        self.response_guard = NS(ready=True)
        self.wait_until_ready = AsyncMock()
        self._wait_for_send_slot = AsyncMock(return_value=True)
        self.is_ready = lambda: True
        self.log = AsyncMock()
        self.listeners = defaultdict(list)

    def wait_for(self, event, *, check):
        future = asyncio.get_running_loop().create_future()
        self.listeners[event].append((check, future))
        return future

    def emit(self, event, *args):
        for check, future in self.listeners[event]:
            if not future.done() and check(*args):
                future.set_result(args[0] if len(args) == 1 else args)


class StartupBattlesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.first = Client(26, "Acc Một", 200)
        self.second = Client(27, "Acc Hai", 201)
        self.series = StartupBattles(("26", "27"))
        self.series.WAIT_FOR_RESULT = .05
        self.invites = {}
        self.clicked = []
        self.click_loops = []
        self.omit_result = False
        self.lose_ack = False
        self.first._validate_dashboard_channel = AsyncMock(return_value=self.first.cm)
        self.receiver_channel = NS(id=200, guild=self.second.cm.guild)
        self.receiver_channel.permissions_for = lambda _: NS(read_message_history=True)
        self.receiver_channel.fetch_message = AsyncMock(side_effect=self.invites.__getitem__)
        self.second._validate_dashboard_channel = AsyncMock(return_value=self.receiver_channel)
        self.first.send = AsyncMock(side_effect=self.send_challenge)
        self.enterContext(patch.object(bot_control, "get_account_overrides", return_value={"startupFriendlyBattles": True}))
        self.enterContext(patch.object(bot_control, "settings_for", return_value=bot_control.DEFAULTS))
        self.enterContext(patch.object(bot_control, "running_for", return_value=True))
        self.enterContext(patch("core.startup_battles.discord.utils.time_snowflake", return_value=1000))

    async def send_challenge(self, command, *, channel, automation_check):
        self.assertIs(channel, self.first.cm)
        self.assertTrue(automation_check())
        command_id = 1001 + 10 * len(self.invites)
        self.first.emit("message", NS(id=command_id, author=self.first.user, channel=channel, content=command))
        invite_id = command_id + 1
        sender_loop = asyncio.get_running_loop()

        async def click():
            self.clicked.append(invite_id)
            self.click_loops.append(asyncio.get_running_loop())
            if not self.omit_result:
                result = NS(id=invite_id + 1, author=NS(id=900), channel=channel, embeds=[
                    NS(author=NS(name="Acc Một goes into battle!"), footer=NS(text="Acc Hai wins!"))])
                sender_loop.call_soon_threadsafe(self.first.emit, "message_edit", None, result)
            if self.lose_ack:
                raise discord.InvalidData("Interaction may still have succeeded")

        invite = NS(id=invite_id, channel=channel, author=NS(id=900), content="<@27>",
                    reference=NS(message_id=command_id), embeds=[NS(
                        author=NS(name="Acc Hai, Acc Một challenges you to a duel!"),
                        footer=NS(text="This challenge will expire in 10 minutes"))],
                    components=[NS(children=[NS(custom_id="battle_accept", disabled=False, click=click)])])
        self.invites[invite_id] = invite
        self.first.emit("message", invite)
        return True

    async def test_completes_three_only_once_in_the_first_accounts_shared_channel(self):
        await self.series.join(self.second)
        self.first.send.assert_not_awaited()
        await self.series.join(self.first)
        await self.series.join(self.first)
        await self.series.join(self.second)
        self.assertEqual(self.clicked, [1002, 1012, 1022])
        self.assertEqual(self.first.send.await_count, 3)
        self.assertTrue(all(call.args == ("ob <@27> -display=compact",) for call in self.first.send.await_args_list))
        self.second._validate_dashboard_channel.assert_awaited_once_with("200")
        self.assertEqual(self.receiver_channel.fetch_message.await_count, 3)
        self.assertIn("3/3", self.first.log.await_args.args[0])

    async def test_clicks_on_receiver_loop_and_counts_result_when_ack_is_lost(self):
        self.lose_ack = True
        sender_loop = asyncio.get_running_loop()
        await self.series.join(self.first)
        await asyncio.to_thread(asyncio.run, self.series.join(self.second))
        self.assertEqual(self.first.send.await_count, 3)
        self.assertEqual(len(self.clicked), 3)
        self.assertTrue(all(loop is not sender_loop for loop in self.click_loops))
        self.assertIn("3/3", self.first.log.await_args.args[0])

    async def test_timeout_after_accept_stops_the_series_without_resending(self):
        self.omit_result = True
        await self.series.join(self.first)
        await self.series.join(self.second)
        self.first.send.assert_awaited_once()
        self.assertEqual(self.clicked, [1002])
        self.assertIn("0/3", self.first.log.await_args.args[0])

    async def test_skips_a_paused_account_before_sending(self):
        self.second.ch.command_handler_status.captcha = True
        await self.series.join(self.first)
        await self.series.join(self.second)
        self.first.send.assert_not_awaited()
        self.receiver_channel.fetch_message.assert_not_awaited()
