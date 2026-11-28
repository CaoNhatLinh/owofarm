import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.cookie import Cookie


def delivery(sender=1, recipient=2):
    return (
        f"**<a:cookieeat:423020737364885525> | <@{recipient}>**! "
        f"You got a cookie from **<@{sender}>**! *nom nom nom c:<*"
    )


def cooldown(sender="Tài Khoản"):
    return f"**🚫 | {sender}**, Nu! You need to wait **3H 21M 4S**"


class CookieTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = NS(enabled=True, user_id="2", ping_user=True)
        self.bot = NS(
            user=NS(id=1), cm=NS(id=10), owo_bot_id=99,
            settings_dict=NS(
                commands=NS(cookie=self.config), prefix="o ",
                cooldowns=NS(moderateCooldown=[3, 5]),
            ),
            alias={"cookie": {"normal": "cookie"}},
            response_guard=NS(ready=True, channel_error=""), ch=NS(should_not_send=False),
            _configured_dashboard_channel=Mock(return_value=10), is_ready=Mock(return_value=True),
            wait_until_ready=AsyncMock(), sleep_till=AsyncMock(), log=AsyncMock(),
            db=NS(fetch_cmd_lastran_time=AsyncMock(return_value=0), update_cmd_lastran_time=Mock()),
            time_in_seconds=Mock(return_value=300), should_run=Mock(side_effect=lambda stamp: stamp < 300),
            calc_time=Mock(return_value=3600), get_nick=Mock(return_value="Tài Khoản"),
        )
        self.cookie = Cookie(self.bot)
        running = patch("core.cogs.cookie.bot_control.running_for", return_value=True)
        running.start()
        self.addCleanup(running.stop)
        self.addAsyncCleanup(self.cookie.cog_unload)

    async def receive(self, text, *, author=99, message_id=102, channel=10, reference=None, members=()):
        await self.cookie.on_message(NS(
            content=text, author=NS(id=author), id=message_id, channel=NS(id=channel),
            reference=NS(message_id=reference) if reference else None, guild=NS(members=members),
        ))

    def test_uses_effective_target_and_rejects_self_and_stale_channel(self):
        self.assertEqual(self.cookie._target().recipient_id, 2)
        self.config.user_id = "1"
        self.assertIsNone(self.cookie._target())
        self.config.user_id = "2 nope"
        self.assertIsNone(self.cookie._target())
        self.config.user_id = "2"
        self.bot._configured_dashboard_channel.return_value = 11
        self.assertIsNone(self.cookie._target())

    async def test_only_exact_success_after_the_own_command_can_confirm(self):
        async def send(command, *, channel, expect_response, automation_check):
            self.assertEqual(command, "o cookie <@2>")
            self.assertEqual(channel.id, 10)
            self.assertTrue(expect_response and automation_check())
            await self.receive(delivery(), message_id=100)
            await self.receive(command, author=1, message_id=101)
            await self.receive(delivery(sender=2, recipient=1))
            await self.receive(delivery(sender=1, recipient=99))
            await self.receive(delivery(), channel=11)
            await self.receive(delivery(), author=7)
            await self.receive(delivery(), reference=100)
            self.assertFalse(self.cookie._attempt.reply.done())
            await self.receive(delivery(), reference=101)
            self.assertEqual(self.cookie._attempt.reply.result(), "sent")
            return True

        self.bot.send = AsyncMock(side_effect=send)
        with patch("core.cogs.cookie.time_snowflake", return_value=100):
            self.assertTrue(await self.cookie._send_cookie(self.cookie._target()))
        self.bot.db.update_cmd_lastran_time.assert_called_once_with("cookie")
        self.bot.log.assert_awaited_once_with("Đã gửi cookie hằng ngày.")
        self.assertIsNone(self.cookie._attempt)

    async def test_cooldown_rejects_other_names_and_an_unreferenced_duplicate_name(self):
        async def send(command, *, automation_check, **_):
            self.assertEqual(command, "o cookie 2")
            self.assertTrue(automation_check())
            await self.receive(command, author=1, message_id=101)
            await self.receive(cooldown("Tài Khoản Hai"))
            await self.receive("You can send a cookie in **3H 21M 4S**!")
            await self.receive(cooldown(), members=[NS(id=7, display_name="Tài Khoản")])
            self.assertFalse(self.cookie._attempt.reply.done())
            await self.receive(cooldown())
            self.assertEqual(self.cookie._attempt.reply.result(), "cooldown")
            return True

        self.config.ping_user = False
        self.bot.send = AsyncMock(side_effect=send)
        with patch("core.cogs.cookie.time_snowflake", return_value=100):
            await self.cookie._send_cookie(self.cookie._target())
        self.bot.log.assert_awaited_once_with("Cookie hôm nay đã được sử dụng.")

    async def test_option_change_before_transport_suppresses_old_target_without_marking_attempt(self):
        async def send(_command, *, automation_check, **_):
            self.config.user_id = "3"
            return automation_check()

        self.bot.send = AsyncMock(side_effect=send)
        self.assertFalse(await self.cookie._send_cookie(self.cookie._target()))
        self.bot.db.update_cmd_lastran_time.assert_not_called()

    async def test_one_scheduler_and_no_same_day_resend_after_uncertain_transport(self):
        attempted = asyncio.Event()

        async def send(_command, *, automation_check, **_):
            self.assertTrue(automation_check())
            attempted.set()
            raise TimeoutError

        self.bot.send = AsyncMock(side_effect=send)
        await self.cookie.cog_load()
        task = self.cookie._task
        await self.cookie.cog_load()
        self.assertIs(self.cookie._task, task)
        await asyncio.wait_for(attempted.wait(), 1)
        self.bot.db.update_cmd_lastran_time.assert_called_once_with("cookie")
        self.bot.send.assert_awaited_once()
        self.bot.log.assert_any_await("Đã bật gửi cookie hằng ngày.")
        self.bot.log.assert_any_await("Chưa xác nhận được lượt gửi cookie hôm nay.")
        await self.cookie.cog_unload()
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.cookie._attempt)

    async def test_changed_target_after_a_send_cancels_stale_reply_wait(self):
        async def send(_command, *, automation_check, **_):
            self.assertTrue(automation_check())
            self.config.user_id = "3"
            return True

        self.bot.send = AsyncMock(side_effect=send)
        self.assertTrue(await asyncio.wait_for(self.cookie._send_cookie(self.cookie._target()), 1))
        self.bot.db.update_cmd_lastran_time.assert_called_once_with("cookie")
        self.bot.log.assert_not_awaited()
        self.assertIsNone(self.cookie._attempt)
