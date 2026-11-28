import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from utils import bot_control
from utils.response_guard import ResponseGuard
from website import website


class Clock:
    def __init__(self): self.now = 100
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


def message(text="Player, caught a pet", author=408, channel=99, mid=200, **kwargs):
    return NS(content=text, author=NS(id=author), channel=NS(id=channel), id=mid,
              embeds=[], components=[], **kwargs)


class GuardTests(unittest.TestCase):
    def setUp(self):
        bot_control.set_running(True)
        self.clock = Clock()
        self.config = dict(bot_control.DEFAULTS)
        self.guard = ResponseGuard("test", self.clock, lambda: dict(self.config))

    def tearDown(self): bot_control.set_running(True)

    def unanswered(self):
        self.guard.expect(99, min_id=100)
        self.guard.sent(NS(id=100))
        self.clock.advance(self.config["responseTimeout"])
        self.guard.tick()

    def test_three_consecutive_timeouts_rest_ten_minutes_then_retry(self):
        for count in range(1, 4):
            self.unanswered()
            self.assertEqual(self.guard.misses, count)
            self.assertEqual(self.guard.cooling_down, count == 3)
        self.clock.advance(599)
        self.assertFalse(self.guard.ready)
        self.clock.advance(1)
        self.assertTrue(self.guard.ready)
        self.assertEqual(self.guard.misses, 0)
        self.unanswered()
        self.assertEqual(self.guard.misses, 1)

    def test_only_expired_requests_are_counted_and_not_counted_twice(self):
        self.guard.expect(99, min_id=100)
        self.clock.advance(19)
        self.assertFalse(self.guard.ready)
        self.assertEqual(self.guard.misses, 0)
        self.clock.advance(1)
        for _ in range(5): self.guard.tick()
        self.assertEqual(self.guard.misses, 1)

    def test_ack_resets_consecutive_failure_count(self):
        self.unanswered(); self.unanswered()
        self.guard.expect(99, min_id=100)
        self.assertTrue(self.guard.observe(message(), 42, {"Player"}, 408))
        self.assertEqual(self.guard.misses, 0)
        self.assertTrue(self.guard.ready)

    def test_foreign_old_or_wrong_channel_messages_do_not_ack(self):
        self.guard.expect(99, min_id=100)
        for item in [message(author=1), message(channel=8), message(mid=1),
                     message("<@7> Player, hello"), message("Other user's reply"),
                     message("<@42>", reference=NS(message_id=9))]:
            self.assertFalse(self.guard.observe(item, 42, {"Player"}, 408))
        self.assertIsNotNone(self.guard.pending)

    def test_native_embed_and_component_responses_are_accepted(self):
        self.guard.expect(99, min_id=100)
        native = message("")
        native.embeds = [NS(title="", description="", author=NS(name="Player's team"), fields=[], footer=None)]
        self.assertTrue(self.guard.observe(native, 42, {"Player"}, 408))
        self.guard.expect(99, min_id=100)
        raw = message("")
        raw.components = [{"type":10,"content":"<@42>'s weapons"}]
        self.assertTrue(self.guard.observe(raw, 42, {"Player"}, 408))

    def test_toggle_off_cancels_current_rest_and_pending_requests(self):
        for _ in range(3): self.unanswered()
        self.config["restEnabled"] = False
        self.assertTrue(self.guard.ready)
        self.assertEqual(self.guard.misses, 0)
        self.guard.expect(99)
        self.assertIsNone(self.guard.pending)
        self.config["restEnabled"] = True
        self.assertTrue(self.guard.ready)

    def test_configurable_threshold_timeout_and_rest(self):
        self.config.update(failureThreshold=2, responseTimeout=10, restMinutes=2)
        self.unanswered(); self.unanswered()
        self.assertTrue(self.guard.cooling_down)
        self.clock.advance(120)
        self.assertTrue(self.guard.ready)

    def test_disabling_rest_keeps_manual_operations_serialized(self):
        self.guard.expect(99, min_id=100, manual=True)
        self.config["restEnabled"] = False
        self.assertFalse(self.guard.ready)
        self.assertTrue(self.guard.observe(message(), 42, {"Player"}, 408))

        self.guard.expect(99, min_id=100, manual=True)
        self.assertFalse(self.guard.ready)
        self.clock.advance(20)
        self.assertTrue(self.guard.ready)
        self.assertEqual(self.guard.misses, 0)

    def test_manual_pause_is_not_a_missing_response(self):
        self.guard.expect(99, min_id=100)
        bot_control.set_running(False)
        self.clock.advance(30)
        self.guard.tick()
        bot_control.set_running(True)
        self.assertTrue(self.guard.ready)
        self.assertEqual(self.guard.misses, 0)

    def test_manual_request_still_tracks_timeout_while_farm_is_paused(self):
        bot_control.set_running(False)
        self.guard.expect(99,min_id=100,manual=True)
        self.guard.tick()
        self.assertIsNotNone(self.guard.pending)
        self.clock.advance(20)
        self.guard.tick()
        self.assertEqual(self.guard.misses,1)
        self.assertIsNone(self.guard.pending)
        self.assertFalse(bot_control.is_running())

    def test_cancelled_or_untracked_send_is_not_a_failure(self):
        self.guard.expect(99, min_id=100)
        self.guard.cancel()
        self.clock.advance(100)
        self.assertTrue(self.guard.ready)
        self.assertEqual(self.guard.misses, 0)


class SettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch_path = patch.object(bot_control, "SETTINGS_PATH", Path(self.temp.name) / "settings.json")
        self.patch_path.start()
        self.previous = bot_control.get_settings()
        self.old = dict(bot_control.DEFAULTS)
        bot_control._settings.clear(); bot_control._settings.update(self.old)
        self.old_password = website.password
        website.password = "test"
        self.client = website.app.test_client()
        self.headers = {"password":"test"}

    def tearDown(self):
        bot_control._settings.clear(); bot_control._settings.update(self.previous)
        website.password = self.old_password
        self.patch_path.stop(); self.temp.cleanup()

    def test_settings_apply_immediately_and_are_saved_atomically(self):
        response = self.client.patch("/api/settings", headers=self.headers,
            json=dict(restEnabled=False, restMinutes=15, failureThreshold=4, messageInterval=7.5, owoEnabled=False))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(bot_control.get_settings()["restEnabled"])
        self.assertEqual(bot_control.get_settings()["messageInterval"], 7.5)
        self.assertIn('"restMinutes": 15', bot_control.SETTINGS_PATH.read_text())
        self.assertFalse(bot_control.SETTINGS_PATH.with_suffix(".json.tmp").exists())
        self.assertEqual(self.client.get("/api/settings", headers=self.headers).json["settings"], response.json["settings"])

    def test_reject_unknown_invalid_and_unauthenticated_settings(self):
        self.assertEqual(self.client.patch("/api/settings", json={"restEnabled":False}, environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code,403)
        for data in [None, [], {}, {"restEnabled":"false"}, {"failureThreshold":1.5},
                     {"restMinutes":0}, {"restMinutes":121}, {"messageInterval":2},
                     {"messageInterval":float("nan")}, {"anything":123}]:
            self.assertEqual(self.client.patch("/api/settings", headers=self.headers, json=data).status_code, 400)
        self.assertEqual(bot_control.get_settings(), self.old)

    def test_failed_disk_write_keeps_previous_runtime_settings(self):
        with patch("utils.bot_control.os.replace", side_effect=OSError):
            response = self.client.patch("/api/settings", headers=self.headers, json={"owoEnabled":False})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(bot_control.get_settings(), self.old)

    def test_prefix_keeps_all_spaces_in_configuration_and_commands(self):
        from core.cogs.commands import Commands
        for prefix in ["o", "owo ", " o "]:
            response = self.client.patch("/api/settings", headers=self.headers, json={"prefix":prefix})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["settings"]["prefix"], prefix)
            fake = NS(bot=NS(settings_dict=NS(prefix=prefix)))
            self.assertEqual(Commands.construct_command(fake, {"cmd_name":"h", "prefix":True}, None), prefix + "h")

    def test_prefix_rejects_empty_control_characters_and_mentions(self):
        for prefix in ["", "  ", "o\n", "<@42>", "a"*26, 123]:
            self.assertEqual(self.client.patch("/api/settings", headers=self.headers, json={"prefix":prefix}).status_code, 400)

    def test_channel_is_checked_before_it_is_saved(self):
        with patch("utils.bot_control.validate_channel") as validate:
            response = self.client.patch("/api/settings", headers=self.headers, json={"channelId":"123456789012345678"})
            self.assertEqual(response.status_code, 200)
            validate.assert_called_once_with("123456789012345678")
        previous = bot_control.get_settings()
        with patch("utils.bot_control.validate_channel", side_effect=ValueError("Không có quyền gửi tin")):
            response = self.client.patch("/api/settings", headers=self.headers, json={"channelId":"1572118634254569503"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(bot_control.get_settings(), previous)

    def test_channel_rejects_malformed_ids(self):
        for value in [123456789012345678, "abc", "123", "1"*21, "１２３４５６７８９０１２３４５６７８"]:
            self.assertEqual(self.client.patch("/api/settings", headers=self.headers, json={"channelId":value}).status_code, 400)

    def test_gem_order_can_be_saved_and_invalid_values_are_rejected(self):
        for order in ["high_to_low","low_to_high"]:
            response=self.client.patch("/api/settings",headers=self.headers,json={"gemOrder":order})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json["settings"]["gemOrder"],order)
            self.assertIn(order,bot_control.SETTINGS_PATH.read_text())
        for order in ["highest",None,True,[],{}]:
            self.assertEqual(self.client.patch("/api/settings",headers=self.headers,json={"gemOrder":order}).status_code,400)


class SchedulerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_after_rest_requeues_enabled_hunt_when_its_check_was_lost(self):
        from core.cogs.commands import Commands
        from core.command_handler import CommandHandler

        config = {**bot_control.DEFAULTS, "failureThreshold": 4, "restMinutes": 5, "battleEnabled": False}
        now = [1000]
        guard = ResponseGuard("scheduler-recovery", lambda: now[0], lambda: config)
        hunt = NS(cmd={"id": "hunt", "cmd_name": "h", "checks": True})
        battle = NS(cmd={"id": "battle", "cmd_name": "b", "checks": True})
        bot = NS(response_guard=guard, misc={"command_info": {"hunt": {}, "battle": {}}},
                 get_cog={"Hunt": hunt, "Battle": battle}.get,
                 stats=NS(gain_or_lose=0), gamble_streaks=NS(snapshot=lambda: {}), hunt_disabled=False,
                 settings_dict=NS(cooldowns=NS(commandHandler=NS(readdingToQueue=7))),
                 apply_dashboard_resume=AsyncMock(return_value=False), apply_dashboard_settings=AsyncMock(),
                 log=AsyncMock())
        bot.ch = CommandHandler(bot)
        bot.ch.cmd_priorities = {"hunt": 1, "battle": 2}
        manager = Commands(bot)
        bot_control.set_running(True)
        with patch.object(bot_control, "get_settings", return_value=config):
            for _ in range(4):
                guard.expect(99)
                now[0] += config["responseTimeout"]
                await manager.monitor_checks.coro(manager)
            self.assertTrue(guard.cooling_down)
            self.assertTrue(bot.ch.queue.empty())
            now[0] += 299
            await manager.monitor_checks.coro(manager)
            self.assertTrue(bot.ch.queue.empty())
            now[0] += 1
            # Recovery waits for independently blocked sends even after the timer expires.
            bot.ch.command_handler_status.sleep = True
            await manager.monitor_checks.coro(manager)
            self.assertTrue(bot.ch.queue.empty())
            bot.ch.command_handler_status.sleep = False
            await manager.monitor_checks.coro(manager)
            await manager.monitor_checks.coro(manager)
            self.assertEqual(bot.ch.queue.qsize(), 1)
            self.assertEqual(bot.ch.queue.get_nowait()[2]["id"], "hunt")
            self.assertEqual(bot.ch.checks, [])


class SenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_hunt_aliases_share_cooldown_without_delaying_battle(self):
        now = [1000]
        fake = NS(_outgoing_lock=asyncio.Lock(), response_guard=NS(ready=True), alias={},
                  settings_dict=NS(prefix="o", commands=NS(hunt=NS(cooldown=[15, 17]), battle=NS(cooldown=[15, 17]))),
                  _wait_for_send_slot=AsyncMock(return_value=True), _send_unlocked=AsyncMock(return_value=NS(id=200)))
        with patch("utils.farm_control.monotonic", side_effect=lambda: now[0]):
            self.assertTrue(await self.Client.send(fake, "oh"))
            now[0] += 5
            self.assertFalse(await self.Client.send(fake, "ohunt"))
            self.assertTrue(await self.Client.send(fake, "ob"))
            now[0] += 2
            self.assertFalse(await self.Client.send(fake, "oh"))
            now[0] += 8
            self.assertTrue(await self.Client.send(fake, "oh"))
        self.assertEqual([call.args[0] for call in fake._send_unlocked.await_args_list], ["oh", "ob", "oh"])

    async def test_hunt_and_battle_disabled_during_wait_are_not_sent(self):
        from utils.gamble_pacing import GamblePacing
        for command,key in (("oh","huntEnabled"),("ob","battleEnabled")):
            config={**bot_control.DEFAULTS}
            async def wait(*args,**kwargs):
                config[key]=False
                return True
            fake=NS(_outgoing_lock=asyncio.Lock(),gamble_pacing=GamblePacing(),settings_dict=NS(prefix="o"),alias={},response_guard=NS(ready=True),_wait_for_send_slot=wait,_send_unlocked=AsyncMock())
            with patch.object(bot_control,"get_settings",return_value=config):
                self.assertFalse(await self.Client.send(fake,command))
            fake._send_unlocked.assert_not_awaited()

    async def test_retry_in_send_waits_for_game_cooldown(self):
        from utils.gamble_pacing import GamblePacing
        now=[0.0]; gate=GamblePacing(clock=lambda:now[0])
        gate.sent("blackjack")
        fake=NS(gamble_pacing=gate,cm_slowmode_cd=0,response_guard=NS(last_sent=0,cooling_down=False),
                ch=NS(command_handler_status=NS(captcha=False)))
        async def advance(delay): now[0]+=delay
        config={**bot_control.DEFAULTS,"blackjackEnabled":True}
        with patch("asyncio.sleep",side_effect=advance), patch.object(bot_control,"get_settings",return_value=config):
            self.assertTrue(await self.Client._wait_for_send_slot(fake,game="blackjack"))
        self.assertGreaterEqual(now[0],10)

    async def test_old_dequeued_retry_is_cancelled_when_its_round_finishes(self):
        from utils.gamble_pacing import GamblePacing
        gate=GamblePacing()
        async def wait(*args,**kwargs):
            gate.finish("blackjack",123)
            return True
        fake=NS(_outgoing_lock=asyncio.Lock(),gamble_pacing=gate,settings_dict=NS(prefix="o"),alias={},
                response_guard=NS(ready=True),_wait_for_send_slot=wait,_send_unlocked=AsyncMock())
        self.assertFalse(await self.Client.send(fake,"obj 200"))
        fake._send_unlocked.assert_not_awaited()

    async def asyncSetUp(self):
        # Importing core.client initializes the platform UI/loader. Compile the
        # actual send methods without those application startup side effects.
        import ast
        tree = ast.parse(Path("core/client.py").read_text(encoding="utf-8"))
        client = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MyClient")
        methods = [node for node in client.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name in {"send", "_send_unlocked", "_wait_for_send_slot", "apply_dashboard_settings", "apply_dashboard_resume"}]
        definition = ast.ClassDef(name="Sender", bases=[], keywords=[], body=methods, decorator_list=[])
        namespace = dict(asyncio=asyncio, bot_control=bot_control,
                         global_settings_dict=NS(silentMessage=False, typingIndicator=False))
        import os, traceback
        namespace.update(os=os,traceback=traceback)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])), "core/client.py", "exec"), namespace)
        self.Client = namespace["Sender"]
        bot_control.set_running(True)
        self.addCleanup(bot_control.set_running,True)

    async def test_spacing_applies_to_every_send_even_without_response_tracking(self):
        fake = NS(response_guard=NS(last_sent=time.monotonic(), cooling_down=False),
            ch=NS(command_handler_status=NS(captcha=False)), cm_slowmode_cd=0)
        waited=[]
        async def sleep(delay):
            waited.append(delay)
            fake.response_guard.last_sent -= delay
        with patch("asyncio.sleep", side_effect=sleep), patch("utils.bot_control.get_settings", return_value={"messageInterval":4}):
            self.assertTrue(await self.Client._wait_for_send_slot(fake))
        self.assertGreaterEqual(sum(waited), 3.9)

    async def test_cooldown_blocks_direct_send_even_with_bypass(self):
        fake=NS(response_guard=NS(last_sent=0, cooling_down=True), ch=NS(command_handler_status=NS(captcha=False)))
        self.assertFalse(await self.Client._wait_for_send_slot(fake, bypass=True))

    async def test_no_response_pending_blocks_sends_before_network(self):
        fake=NS(_outgoing_lock=asyncio.Lock(), response_guard=NS(ready=False),
                _wait_for_send_slot=AsyncMock(), _send_unlocked=AsyncMock())
        self.assertFalse(await self.Client.send(fake, "oh"))
        fake._send_unlocked.assert_not_awaited()

    async def test_disabled_owo_is_not_sent_even_if_already_dequeued(self):
        fake=NS(_outgoing_lock=asyncio.Lock(), _send_unlocked=AsyncMock())
        with patch("utils.bot_control.get_settings", return_value={"owoEnabled":False}):
            self.assertFalse(await self.Client.send(fake, "owo"))
        fake._send_unlocked.assert_not_awaited()

    async def test_automation_rechecks_permission_just_before_sending(self):
        channel = NS(id=99, send=AsyncMock())
        guard = ResponseGuard("queued-automation-test", channel_id=99)
        fake = NS(
            _outgoing_lock=asyncio.Lock(), response_guard=guard, cm=channel,
            ch=NS(command_handler_status=NS(captcha=False)), misc={"console": {"disableCommandSendLog": True}},
            settings_dict=NS(prefix="o", misspell=NS(enabled=True)), alias={},
            wait_until_ready=AsyncMock(), _wait_for_send_slot=AsyncMock(return_value=True),
        )
        fake._send_unlocked = lambda *args, **kwargs: self.Client._send_unlocked(fake, *args, **kwargs)
        check = iter((True, False))
        sent = await self.Client.send(fake, "ohuntbot 500", expect_response=True, automation_check=lambda: next(check))
        self.assertFalse(sent)
        self.assertIsNone(guard.pending)
        channel.send.assert_not_awaited()

    async def test_manual_send_works_while_farm_is_stopped_without_starting_it(self):
        bot_control.set_running(False)
        channel=NS(id=99,send=AsyncMock(return_value=NS(id=200)))
        guard=ResponseGuard("manual-send-test")
        fake=NS(_outgoing_lock=asyncio.Lock(),response_guard=guard,cm=channel,cm_slowmode_cd=0,
            ch=NS(command_handler_status=NS(captcha=False,sleep=False),put_queue=AsyncMock()),
            settings_dict=NS(prefix="o",misspell=NS(enabled=True)),alias={},misc={"console":{"disableCommandSendLog":False}},
            wait_until_ready=AsyncMock(),log=AsyncMock())
        fake._wait_for_send_slot=lambda *args,**kwargs:self.Client._wait_for_send_slot(fake,*args,**kwargs)
        fake._send_unlocked=lambda *args,**kwargs:self.Client._send_unlocked(fake,*args,**kwargs)
        self.assertTrue(await self.Client.send(fake,"osell cw",manual=True,expect_response=True))
        channel.send.assert_awaited_once_with("osell cw",silent=False)
        fake.ch.put_queue.assert_not_awaited()
        self.assertFalse(bot_control.is_running())
        guard.tick()
        self.assertTrue(guard.pending["manual"])
        self.assertTrue(guard.observe(message("Player, You sold all your Common weapons",mid=201),42,{"Player"},408))
        self.assertFalse(await self.Client.send(fake,"oh"))
        self.assertEqual(channel.send.await_count,1)

    async def test_manual_send_still_blocks_captcha_while_farm_is_stopped(self):
        bot_control.set_running(False)
        fake=NS(response_guard=NS(last_sent=0,cooling_down=False),
            ch=NS(command_handler_status=NS(captcha=True,sleep=False)))
        self.assertFalse(await self.Client._wait_for_send_slot(fake,manual=True))
        self.assertTrue(fake.ch.command_handler_status.captcha)
        self.assertFalse(bot_control.is_running())

    async def test_prefix_and_channel_are_applied_without_restart(self):
        guard = ResponseGuard("apply-test")
        guard.misses = 2
        fake = NS(settings_dict=NS(prefix="o",gamble=NS(**{g:NS(enabled=False) for g in ("coinflip","slots","blackjack")})), extensions={}, cm=NS(id=99), _initial_channel_id=99,
            _outgoing_lock=asyncio.Lock(), response_guard=guard, get_cog=lambda _: None,
            _dashboard_channels={"123456789012345678":NS(id=123456789012345678, slowmode_delay=7)})
        config = {**bot_control.DEFAULTS, "prefix":"owo ", "channelId":"123456789012345678"}
        with patch("utils.bot_control.get_settings", return_value=config):
            await self.Client.apply_dashboard_settings(fake)
        self.assertEqual(fake.settings_dict.prefix, "owo ")
        self.assertEqual(fake.cm.id, 123456789012345678)
        self.assertEqual(fake.cm_slowmode_cd, 7)
        self.assertEqual(guard.misses, 0)
        self.assertEqual(guard.channel_id, "123456789012345678")

    async def test_explicit_start_clears_old_captcha_and_response_waits(self):
        guard=ResponseGuard("resume-test")
        guard.misses=4; guard.rest_until=guard.clock()+600
        guard.captcha=True
        status=NS(captcha=True,sleep=True)
        captcha=NS(reset_waiting=AsyncMock(side_effect=lambda: setattr(status,"captcha",False)))
        fake=NS(response_guard=guard,ch=NS(command_handler_status=status),
                get_cog=lambda _:captcha,log=AsyncMock())
        bot_control.set_running(False); bot_control.set_running(True)
        await self.Client.apply_dashboard_resume(fake)
        self.assertFalse(status.captcha)
        self.assertTrue(status.sleep)
        self.assertEqual(guard.misses,0)
        self.assertEqual(guard.rest_until,0)
        self.assertEqual(guard.resume_generation,bot_control.get_resume_generation())
        captcha.reset_waiting.assert_awaited_once()
        status.captcha=True  # A later challenge must remain blocked.
        await self.Client.apply_dashboard_resume(fake)
        self.assertTrue(status.captcha)
        self.assertEqual(captcha.reset_waiting.await_count,1)

    async def test_explicit_start_preserves_an_inflight_manual_request(self):
        guard = ResponseGuard("manual-resume-test", settings=lambda: {**bot_control.DEFAULTS, "restEnabled": True})
        status = NS(captcha=False)
        fake = NS(response_guard=guard, ch=NS(command_handler_status=status), get_cog=lambda _: None, log=AsyncMock())
        bot_control.set_running(False)
        guard.expect(99, min_id=100, manual=True)
        pending = guard.pending
        bot_control.set_running(True)
        self.assertTrue(await self.Client.apply_dashboard_resume(fake))
        self.assertIsNotNone(pending)
        self.assertIs(guard.pending, pending)
        self.assertFalse(guard.ready)

    async def test_manual_resume_cancels_previous_captcha_timer(self):
        import ast
        from unittest.mock import Mock
        source=ast.parse(Path("core/cogs/captcha.py").read_text(encoding="utf-8"))
        cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=="Captcha")
        methods=[n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name in {"reset_waiting","kill_code"}]
        exit_mock=Mock()
        namespace=dict(asyncio=asyncio,os=NS(_exit=exit_mock))
        exec(compile(ast.fix_missing_locations(ast.Module(body=methods,type_ignores=[])),"core/cogs/captcha.py","exec"),namespace)
        status=NS(captcha=True)
        fake=NS(_challenge_epoch=5,bot=NS(ch=NS(command_handler_status=status)),
                kill_task=NS(cancel=Mock()),captcha_site_opened=True,handle_solves=AsyncMock())
        await namespace["reset_waiting"](fake)
        self.assertEqual(fake._challenge_epoch,6)
        self.assertFalse(status.captcha)
        fake.kill_task.cancel.assert_called_once()
        status.captcha=True
        with patch("asyncio.sleep",new=AsyncMock()):
            await namespace["kill_code"](fake,5)
        exit_mock.assert_not_called()


if __name__ == "__main__": unittest.main()
