import importlib
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.cogs.commands import Commands
from core.cogs.sell import Sell
from core.command_handler import CommandHandler
from utils import bot_control

sell_module = importlib.import_module("core.cogs.sell")
commands_module = importlib.import_module("core.cogs.commands")


class FakeBot:
    def __init__(self):
        self.user = SimpleNamespace(
            id=123456789012345678, name="account_name", display_name="Display Name"
        )
        self.cm = SimpleNamespace(id=200, guild=SimpleNamespace(id=300))
        self.owo_bot_id = 408785106942164992
        async def ready():
            pass
        self.response_guard = SimpleNamespace(wait_ready=ready, tick=lambda: None,
                                              cooling_down=False, pending=None)
        self.random = random.Random(0)
        rarity = SimpleNamespace(get_rarities=lambda: "c u")
        self.settings_dict = SimpleNamespace(
            animal=SimpleNamespace(
                sell=SimpleNamespace(enabled=True, rarity=rarity),
                sac=SimpleNamespace(enabled=False, rarity=rarity),
                emergencySell=SimpleNamespace(
                    enabled=True,
                    rarities=["common", "uncommon", "rare"],
                    retryCooldown=300.0,
                ),
                get_cd=lambda: 7201.0,
            ),
            cashCheck=True,
            prefix="owo ",
            useSlashCommands=False,
            cooldowns=SimpleNamespace(
                commandHandler=SimpleNamespace(
                    betweenCommands=[1.7, 2.7], readdingToQueue=7
                )
            ),
        )
        self.animal_rank_in_zoo = {"common": True, "uncommon": True}
        self.misc = {
            "command_info": {
                name: {"log_color": "white"} for name in ("cash", "sell", "sac")
            }
        }
        self.db = SimpleNamespace(update_cmd_db=lambda command_id: None)
        self.ch = CommandHandler(self)
        self.ch.cmd_priorities = {"cash": 1, "sell": 1, "sac": 1}
        self.logs = []
        self.sent = []
        self.cash_updates = []
        self.on_sleep = None
        self.seller = None
        self.huntbot = None

    def get_cog(self, name):
        return {"Sell": self.seller, "Huntbot": self.huntbot}.get(name)

    def get_nick(self, message):
        return "ExamplePlayer"

    async def sleep_till(self, delay):
        if self.on_sleep and delay == [10, 15]:
            callback, self.on_sleep = self.on_sleep, None
            await callback()

    async def apply_dashboard_settings(self):
        pass

    async def apply_dashboard_resume(self):
        pass

    async def log(self, message, color=None):
        self.logs.append(message)

    async def send(self, message, color, channel=None, **kwargs):
        if (check := kwargs.get("automation_check")) is not None and not check():
            return False
        self.sent.append(message)
        return True

    def update_cash(self, amount):
        self.cash_updates.append(amount)


class SellTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimpleNamespace(now=1000.0)
        self.monotonic = patch.object(
            sell_module, "time", SimpleNamespace(monotonic=lambda: self.clock.now)
        )
        self.wall_clock = patch.object(
            commands_module, "time", SimpleNamespace(time=lambda: self.clock.now)
        )
        self.monotonic.start()
        self.wall_clock.start()
        self.addCleanup(self.monotonic.stop)
        self.addCleanup(self.wall_clock.stop)
        self.bot = FakeBot()
        self.seller = Sell(self.bot)
        self.bot.seller = self.seller
        self.flags = {
            **bot_control.DEFAULTS,
            "huntEnabled": True,
            "huntEmergencySellEnabled": True,
            "zooSacrificeSurplusEnabled": False,
            "teamSetupEnabled": False,
        }
        flags_patch = patch.object(bot_control, "settings_for", return_value=self.flags)
        flags_patch.start()
        self.addCleanup(flags_patch.stop)

    def complete(self, coroutine):
        # Fake operations finish immediately, so tests need no event loop or sockets.
        try:
            coroutine.send(None)
        except StopIteration:
            return
        finally:
            coroutine.close()
        self.fail("Unexpected asynchronous suspension in offline test")

    def message(self, content=None, message_id=1, author_id=None, channel_id=None):
        return SimpleNamespace(
            id=message_id,
            content=content
            or "**🔪 | EXAMPLEPLAYER**, you don't have enough cowoncy to hunt! >:c",
            author=SimpleNamespace(
                id=self.bot.owo_bot_id if author_id is None else author_id
            ),
            channel=SimpleNamespace(
                id=self.bot.cm.id if channel_id is None else channel_id
            ),
        )

    def notify(self, *, request="owo h", message_id=1, **kwargs):
        if request:
            self.complete(self.seller.on_message(self.message(
                content=request, message_id=message_id * 10, author_id=self.bot.user.id
            )))
        self.complete(self.seller.on_message(self.message(message_id=message_id * 10 + 1, **kwargs)))

    def tick(self):
        self.complete(self.seller.initiate_loop.coro(self.seller))

    def consume(self):
        _, _, command = self.bot.ch.queue.get_nowait()
        self.bot.ch.cmds_state[command["id"]]["in_queue"] = False
        return command

    def test_periodic_sale_waits_after_startup_and_restart(self):
        for elapsed in (0, 7199, 7200, 7201):
            self.clock.now = 1000 + elapsed
            self.tick()
            self.assertTrue(self.bot.ch.queue.empty())
        self.clock.now = 8201.1
        self.tick()
        command = self.consume()
        self.assertEqual((command["cmd_name"], command["cmd_arguments"]), ("sell", "c u"))
        self.assertFalse(command["checks"])
        self.seller = Sell(self.bot)
        self.tick()
        self.assertTrue(self.bot.ch.queue.empty())
        self.assertEqual(self.seller.sac_lastran, 0)
        self.assertFalse(self.seller.get_command("sac")["checks"])

    def test_emergency_sale_bypasses_periodic_timer_and_resets_it(self):
        self.clock.now += 10
        self.notify()
        command = self.consume()
        self.assertEqual(command["cmd_name"], "sell")
        self.assertEqual(command["cmd_arguments"], "c u r")
        self.assertFalse(command["checks"])
        self.assertEqual(self.seller.sell_lastran, self.clock.now)
        self.clock.now += 7199
        self.tick()
        self.assertTrue(self.bot.ch.queue.empty())
        self.clock.now += 3
        self.tick()
        self.assertEqual(self.consume()["cmd_arguments"], "c u")

    def test_known_money_patterns_and_account_identifiers(self):
        cases = [
            "**EXAMPLEPLAYER**, you don't have enough money!",
            "**display name**, you do not have enough cash to hunt!",
            "**ACCOUNT_NAME**, you have insufficient cowoncy!",
            "<@!123456789012345678>, not enough cowoncy!",
            "123456789012345678: insufficient money!",
            "**ExamplePlayer**, you don’t have enough <:cowoncy:416043450337853441>!",
        ]
        for index, content in enumerate(cases):
            with self.subTest(content=content):
                self.clock.now += 301
                self.notify(content=content, message_id=index + 1)
                self.assertEqual(self.consume()["cmd_arguments"], "c u r")

    def test_unrelated_or_ambiguous_messages_do_not_sell(self):
        cases = [
            {"author_id": 999},
            {"channel_id": 999},
            {"content": "**OtherPlayer**, you don't have enough cowoncy!"},
            {"content": "**OtherExamplePlayer**, you don't have enough cowoncy!"},
            {"content": "**OtherPlayer**, you don't have enough money to help ExamplePlayer!"},
            {"content": "**ExamplePlayer**, something went wrong!"},
            {"content": "**ExamplePlayer**, you don't have enough animals! >:c"},
            {"content": "**ExamplePlayer**, you don't have enough WP!"},
            {"content": "**ExamplePlayer**, you don't have enough weapon shards. Your cowoncy is low."},
            {"content": "**ExamplePlayer**, you don't have enough cowoncy for this weapon!"},
        ]
        for index, kwargs in enumerate(cases):
            with self.subTest(kwargs=kwargs):
                self.notify(message_id=index + 1, **kwargs)
                self.assertTrue(self.bot.ch.queue.empty())

    def test_duplicate_and_repeated_errors_are_rate_limited(self):
        self.notify(message_id=1)
        self.consume()
        for elapsed, message_id in ((7, 2), (299, 3)):
            self.clock.now = 1000 + elapsed
            self.notify(message_id=message_id)
            self.assertTrue(self.bot.ch.queue.empty())
        self.clock.now = 1400
        self.notify(message_id=1)
        self.assertTrue(self.bot.ch.queue.empty())
        self.notify(message_id=4)
        self.assertEqual(self.consume()["cmd_arguments"], "c u r")

    def test_emergency_sale_never_uses_higher_rarities_or_sacrifice(self):
        self.bot.settings_dict.animal.emergencySell.rarities += ["epic", "legendary"]
        self.notify()
        command = self.consume()
        self.assertEqual(command["cmd_arguments"], "c u r")
        self.assertEqual(command["cmd_name"], "sell")
        self.assertEqual(self.seller.sac_lastran, 0)

    def test_disabled_or_empty_emergency_settings_do_not_sell(self):
        self.flags["huntEmergencySellEnabled"] = False
        self.notify()
        self.flags["huntEmergencySellEnabled"] = True
        self.bot.settings_dict.animal.emergencySell.rarities = ["epic"]
        self.notify(message_id=2)
        self.assertTrue(self.bot.ch.queue.empty())

    def test_pending_sale_does_not_record_an_emergency_success(self):
        self.complete(self.bot.ch.put_queue(self.seller.get_command("sell")))
        self.clock.now = 1500
        self.notify()
        self.assertEqual(self.bot.ch.queue.qsize(), 1)
        self.assertEqual(self.seller.sell_lastran, 1000)
        self.assertIsNone(self.seller._emergency_lastran)
        self.consume()
        self.notify(message_id=2)
        self.assertEqual(self.consume()["cmd_arguments"], "c u r")

    def test_refused_queue_does_not_record_an_emergency_success(self):
        async def refuse(command, **kwargs):
            return None

        self.bot.ch.put_queue = refuse
        self.clock.now = 1500
        self.notify()
        self.assertEqual(self.seller.sell_lastran, 1000)
        self.assertIsNone(self.seller._emergency_lastran)
        self.assertFalse(self.bot.logs)

    def test_captcha_pause_prevents_emergency_sale(self):
        self.bot.ch.command_handler_status.captcha = True
        self.notify()
        self.assertTrue(self.bot.ch.queue.empty())
        self.assertIsNone(self.seller._emergency_lastran)

    def test_emergency_during_periodic_delay_prevents_duplicate(self):
        self.clock.now = 8202

        async def trigger_emergency():
            await self.seller.on_message(self.message(content="owo h", author_id=self.bot.user.id))
            await self.seller.on_message(self.message(message_id=2))

        self.bot.on_sleep = trigger_emergency
        self.tick()
        self.assertEqual(self.bot.ch.queue.qsize(), 1)
        self.assertEqual(self.consume()["cmd_arguments"], "c u r")

    def test_no_sale_retry_when_owo_response_is_missing(self):
        commands = Commands(self.bot)
        self.notify()
        self.complete(commands.send_commands.coro(commands))
        self.assertEqual(self.bot.sent, ["owo sell c u r"])
        self.assertFalse(self.bot.ch.checks)
        for elapsed in (8, 30, 299):
            self.clock.now = 1000 + elapsed
            self.complete(commands.monitor_checks.coro(commands))
            self.assertTrue(self.bot.ch.queue.empty())

    def test_existing_sale_confirmation_still_updates_cash(self):
        self.notify(
            content="**🔪 | exampleplayer** sold **<:common:416520037713838081>x9** "
            "for a total of **<:cowoncy:416043450337853441> 30**"
        )
        self.assertEqual(self.bot.cash_updates, [30])
        self.assertTrue(self.bot.ch.queue.empty())

    def test_unrelated_requests_and_stale_hunt_responses_cannot_trigger_emergency_sale(self):
        self.notify(request="owo cf 200")
        self.notify(request="owo hb", message_id=2)
        self.notify(request="owo buy 1", message_id=3)
        self.notify(request=None, message_id=4)
        self.complete(self.seller.on_message(self.message(
            content="owo h", message_id=50, author_id=self.bot.user.id
        )))
        self.clock.now += self.flags["responseTimeout"] + 1
        self.notify(request=None, message_id=5)
        self.assertTrue(self.bot.ch.queue.empty())

    def test_surplus_requires_fresh_owned_balance_and_more_than_threshold(self):
        def cash_reply(amount, **kwargs):
            self.notify(content=f"**EXAMPLEPLAYER**, you currently have **__{amount}__ cowoncy!**", **kwargs)

        cash_reply("6,000", request="owo cash")
        self.assertTrue(self.bot.ch.queue.empty())
        self.flags["zooSacrificeSurplusEnabled"] = True
        cash_reply("6,000", request="owo h", message_id=2)
        cash_reply("5,000", request="owo cash", message_id=3)
        self.notify(request="owo cash", message_id=4, content="**OtherPlayer**, you currently have **__6,000__ cowoncy!**")
        self.assertTrue(self.bot.ch.queue.empty())
        cash_reply("5,001", request="owo cash", message_id=5)
        command = self.consume()
        self.assertEqual((command["cmd_name"], command["cmd_arguments"]), ("sac", "all"))
        self.assertFalse(command["checks"])
        self.assertTrue(self.seller.allows_queued_command(command))
        cash_reply("5,001", request=None, message_id=5)
        self.assertTrue(self.bot.ch.queue.empty())
        self.clock.now += sell_module.BALANCE_CHECK_INTERVAL + 11
        self.assertFalse(self.seller.allows_queued_command(command))

    def test_surplus_waits_for_team_and_paces_balance_checks(self):
        self.flags.update(zooSacrificeSurplusEnabled=True, teamSetupEnabled=True)
        self.tick()
        self.assertTrue(self.bot.ch.queue.empty())
        self.bot._team_setup_ready = True
        self.bot.huntbot = SimpleNamespace(pending=("start", 5000))
        self.tick()
        self.assertTrue(self.bot.ch.queue.empty())
        self.bot.huntbot.pending = None
        self.bot.response_guard.huntbot_captcha = {"messageId": "123"}
        self.tick()
        self.assertTrue(self.bot.ch.queue.empty())
        self.bot.response_guard.huntbot_captcha = None
        self.tick()
        self.assertEqual(self.consume()["id"], "cash")
        self.tick()
        self.assertTrue(self.bot.ch.queue.empty())
        self.clock.now += sell_module.BALANCE_CHECK_INTERVAL
        self.tick()
        self.assertEqual(self.consume()["id"], "cash")

    def test_legacy_sacrifice_is_not_retried_and_respects_a_changed_mode(self):
        self.bot.settings_dict.animal.sac.enabled = True
        counted = []
        self.bot.db.update_cmd_db = counted.append
        commands = Commands(self.bot)
        self.tick()
        self.assertEqual(self.bot.ch.queue.qsize(), 1)
        self.flags["zooSacrificeSurplusEnabled"] = True
        self.complete(commands.send_commands.coro(commands))
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(counted, [])
        self.assertFalse(self.bot.ch.checks)

        self.flags["zooSacrificeSurplusEnabled"] = False
        self.bot.settings_dict.animal.sell.enabled = False
        self.bot.ch.cmds_state["global"]["last_ran"] = self.clock.now
        self.clock.now += 7300
        self.tick()
        self.complete(commands.send_commands.coro(commands))
        self.assertEqual(self.bot.sent, ["owo sac c u"])
        self.assertEqual(counted, ["sac"])
        self.assertFalse(self.bot.ch.checks)
        self.tick()
        self.assertTrue(self.bot.ch.queue.empty())

    def test_queued_surplus_rechecks_setting_balance_and_channel_before_sending(self):
        self.flags["zooSacrificeSurplusEnabled"] = True
        commands = Commands(self.bot)
        self.notify(request="owo cash", content="**ExamplePlayer**, you currently have **__5,500__ cowoncy!**")
        self.flags["zooSacrificeSurplusEnabled"] = False
        self.complete(commands.send_commands.coro(commands))
        self.assertEqual(self.bot.sent, [])
        self.flags["zooSacrificeSurplusEnabled"] = True
        self.notify(request="owo cash", content="**ExamplePlayer**, you currently have **__5,600__ cowoncy!**", message_id=2)
        self.clock.now += 6
        self.bot.stats = SimpleNamespace(has_updated_balance=True, balance=5000)
        self.complete(commands.send_commands.coro(commands))
        self.assertEqual(self.bot.sent, [])
        self.notify(request="owo cash", content="**ExamplePlayer**, you currently have **__6,000__ cowoncy!**", message_id=3)
        self.clock.now += 6
        self.bot.stats.balance = 6000
        self.bot.cm.id += 1
        self.complete(commands.send_commands.coro(commands))
        self.assertEqual(self.bot.sent, [])
        self.notify(request="owo cash", content="**ExamplePlayer**, you currently have **__6,000__ cowoncy!**", message_id=4)
        self.clock.now += 6
        self.complete(commands.send_commands.coro(commands))
        self.assertEqual(self.bot.sent, ["owo sac all"])
        self.assertEqual(self.seller.sac_lastran, self.clock.now)
        self.tick()
        self.assertTrue(self.bot.ch.queue.empty())


if __name__ == "__main__":
    unittest.main()
