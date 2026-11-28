import random
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.customcommands import CustomCommands
from utils.config_models import settings


class CommandCooldownTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(settings, "_command_random", random.Random(19)))

    def test_ten_second_minimum_varies_up_to_twenty(self):
        values = [settings.get_command_cd([10, 11]) for _ in range(100)]
        self.assertTrue(all(10 <= value <= 20 for value in values))
        self.assertTrue(any(value > 19 for value in values))
        self.assertGreater(len(set(values)), 90)

    def test_fifteen_second_minimum_can_exceed_previous_narrow_range(self):
        values = [settings.get_command_cd([15, 17]) for _ in range(100)]
        self.assertTrue(all(15 <= value <= 25 for value in values))
        self.assertTrue(any(value > 24 for value in values))

    def test_wider_configured_range_is_preserved(self):
        values = [settings.get_command_cd([10, 60]) for _ in range(100)]
        self.assertTrue(all(10 <= value <= 60 for value in values))
        self.assertTrue(any(value > 59 for value in values))

    def test_short_and_long_minimums_remain_floors(self):
        for minimum, maximum in ((0.5, 1), (3, 6), (300, 310)):
            with self.subTest(minimum=minimum):
                values = [settings.get_command_cd([minimum, minimum + 0.1]) for _ in range(100)]
                self.assertTrue(all(minimum <= value <= maximum for value in values))

    def test_command_cooldowns_keep_existing_validation(self):
        for invalid in (None, [], [10], [20, 10], [10, 10], (10, 11)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                settings.get_command_cd(invalid)

    def test_repeating_command_families_use_variable_intervals(self):
        models = [
            settings.Command(dict(enabled=True, cooldown=[10, 11])),
            settings.GambleItem(dict(enabled=True, startValue=10, multiplierOnLose=2, cooldown=[10, 11])),
            settings.ReactionBot(dict(huntAndBattle=True, owo=True, prayAndCurse=True, cooldown=[10, 11])),
            settings.ShopCommand(dict(enabled=True, cooldown=[10, 11], itemsToBuy={
                f"{name}Ring": False for name, _ in settings.RING_PRICES
            })),
            settings.Animal(dict(
                sell=dict(enabled=True, rarity={}), sac=dict(enabled=False, rarity={}), cooldown=[10, 11],
            )),
            settings.CustomCommand(dict(enabled=True, command="owo hunt", cooldown=10)),
        ]
        for model in models:
            with self.subTest(model=type(model).__name__):
                values = [model.get_cd() for _ in range(100)]
                self.assertTrue(all(10 <= value <= 20 for value in values))
                self.assertTrue(any(value > 11 for value in values))

    def test_global_random_seed_does_not_reset_command_intervals(self):
        state = random.getstate()
        self.addCleanup(random.setstate, state)
        random.seed(5)
        first = settings.get_command_cd([10, 11])
        random.seed(5)
        second = settings.get_command_cd([10, 11])
        self.assertNotEqual(first, second)

    def test_general_check_sleep_and_giveaway_timers_keep_configured_ranges(self):
        autoquest = settings.AutoQuest(dict(
            enabled=True, helpChannel=dict(postInHelpChannel=False, channelId=123),
            helpOthers=False, enableCommandsToCompleteQuest=False, checkCooldown=[10, 11],
        ))
        giveaway = settings.Giveaway(dict(
            enabled=True, messageRangeToCheck=10, cooldown=[10, 11], channelsToJoin=[],
        ))
        sleep = settings.Sleep(dict(
            enabled=True, frequencyPercentage=10, checkTime=[10, 11], sleepTime=[10, 11],
        ))
        upgrader = settings.HuntbotUpgrader(dict(
            enabled=True, sleeptime=[10, 11],
            traits=dict.fromkeys(settings.HUNTBOT_TRAITS, True),
            weights=dict.fromkeys(settings.HUNTBOT_TRAITS, 1),
        ))
        with patch.object(settings.random, "uniform", side_effect=lambda low, high: high):
            self.assertEqual(settings.get_cd([10, 11]), 11)
            self.assertEqual(autoquest.get_cd(), 11)
            self.assertEqual(giveaway.get_cd(), 11)
            self.assertEqual(sleep.get_check_time(), 11)
            self.assertEqual(sleep.get_sleep_time(), 11)
            self.assertEqual(upgrader.get_cd(), 11)


class CustomCommandPacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_custom_interval_is_sampled_once_after_each_run(self):
        command = settings.CustomCommand(dict(enabled=True, command="owo hunt", cooldown=10))
        command.get_cd = Mock(side_effect=(11, 20, 12))
        bot = NS(
            ch=NS(put_queue=AsyncMock()),
            settings_dict=NS(customCommands=NS(commands=[command], approximate_minimum_cooldown=lambda: 1)),
        )
        cog = CustomCommands(bot)
        now = [100.0]
        with patch("core.cogs.customcommands.time.monotonic", side_effect=lambda: now[0]), patch(
            "core.cogs.customcommands.asyncio.sleep", new=AsyncMock(),
        ):
            await cog.command_handler.coro(cog)
            self.assertEqual(bot.ch.put_queue.await_count, 1)
            self.assertEqual(command.get_cd.call_count, 1)
            for current in (105, 109, 110, 111):
                now[0] = current
                await cog.command_handler.coro(cog)
            self.assertEqual(command.get_cd.call_count, 1)
            self.assertEqual(bot.ch.put_queue.await_count, 1)

            now[0] = 111.1
            await cog.command_handler.coro(cog)
            self.assertEqual(command.get_cd.call_count, 2)
            self.assertEqual(bot.ch.put_queue.await_count, 2)
            self.assertEqual(cog.cmd_tracker[0]["cooldown"], 20)
            now[0] = 131
            await cog.command_handler.coro(cog)
            self.assertEqual(bot.ch.put_queue.await_count, 2)
            now[0] = 131.2
            await cog.command_handler.coro(cog)
            self.assertEqual(bot.ch.put_queue.await_count, 3)
            self.assertEqual(command.get_cd.call_count, 3)


if __name__ == "__main__":
    unittest.main()
