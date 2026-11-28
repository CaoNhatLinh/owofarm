import unittest
from types import SimpleNamespace as NS

from utils.command_timing import command_timing


class CommandTimingTests(unittest.TestCase):
    def make_bot(self, *, prefix="o"):
        return NS(
            settings_dict=NS(prefix=prefix, commands=NS(), gamble=NS()),
            misc={"command_info": {}}, alias={},
        )

    def test_builtin_aliases_share_canonical_keys_and_ignore_arguments(self):
        bot = self.make_bot()
        cases = (
            ("oh 123", "hunt", 15), ("o catch", "hunt", 15),
            ("ob", "battle", 15), ("ofight 456", "battle", 15),
            ("owo", "owo", 10), ("uwu", "owo", 10),
            ("owo hunt", "hunt", 15), ("uwu catch", "hunt", 15),
            ("ocf 10 heads", "coinflip", 15), ("oflip 200 tails", "coinflip", 15),
            ("os 20", "slots", 15), ("obj 1000", "blackjack", 15),
            ("ouse 51 52", "gems", 5), ("oequip 51", "gems", 5),
            ("oweapon abc 1", "weapons", 5), ("ow 2", "weapons", 5),
            ("oweapons", "weapons", 5), ("obuy 1", "shop", 4),
            ("opray 123", "pray", 300), ("ocurse 456", "pray", 300),
            ("oah 100", "huntbot", 1), ("oupgrade efficiency 10", "upgrade", 1),
            ("omystery 1", "mystery", 0), ("omystery 200", "mystery", 0),
        )
        for message, key, minimum in cases:
            with self.subTest(message=message):
                self.assertEqual(command_timing(bot, message), (key, minimum))

    def test_configured_prefix_is_matched_before_shorter_prefixes(self):
        for prefix, message in (("owo ", "owo hunt"), ("!", "!hunt"), ("owo", "owohunt"), ("XY ", "xy hunt")):
            with self.subTest(prefix=prefix):
                self.assertEqual(command_timing(self.make_bot(prefix=prefix), message), ("hunt", 15))

    def test_configured_alias_strings_and_nested_lists_are_flattened(self):
        bot = self.make_bot()
        bot.alias = {
            "hunt": {"normal": "searchpets", "shortform": "sp", "alias": ["catchpets", "search"]},
            "use": {"normal": "activategems", "alias": ["gemup"]},
            "curse": {"normal": "hex", "alias": ["jinx"]},
            "customverb": "cv",
        }
        for message, key in (("osearchpets", "hunt"), ("osp", "hunt"), ("ocatchpets", "hunt"),
                             ("oSEARCH", "hunt"), ("ogemup", "gems"), ("ohex", "pray"),
                             ("ojinx", "pray"), ("ocv 10", "customverb")):
            with self.subTest(message=message):
                self.assertEqual(command_timing(bot, message)[0], key)

    def test_largest_configured_or_metadata_floor_wins(self):
        bot = self.make_bot()
        bot.misc["command_info"] = {"hunt": {"basecd": 12}, "shop": {"basecd": 4}, "coinflip": {"basecd": 15}}
        bot.settings_dict.commands = NS(hunt=NS(cooldown=[20, 25]), shop=NS(cooldown=[10, 20]))
        bot.settings_dict.gamble.coinflip = NS(cooldown=[16, 18])
        self.assertEqual(command_timing(bot, "oh"), ("hunt", 20))
        self.assertEqual(command_timing(bot, "obuy 1"), ("shop", 10))
        self.assertEqual(command_timing(bot, "ocf 100 h"), ("coinflip", 16))
        bot.misc["command_info"]["hunt"]["basecd"] = 30
        self.assertEqual(command_timing(bot, "oh"), ("hunt", 30))

    def test_pray_and_curse_use_the_largest_shared_floor(self):
        bot = self.make_bot()
        bot.settings_dict.commands = NS(pray=NS(cooldown=[310, 400]), curse=NS(cooldown=[350, 400]))
        for message in ("opray 123", "ocurse 456"):
            self.assertEqual(command_timing(bot, message), ("pray", 350))

    def test_periodic_sales_and_upgrade_schedules_are_not_command_minimums(self):
        bot = self.make_bot()
        bot.settings_dict.animal = NS(cooldown=[7200, 7201])
        bot.settings_dict.commands.huntbot = NS(upgrader=NS(sleeptime=[100, 200]))
        self.assertEqual(command_timing(bot, "osell cw"), ("sell", 1))
        self.assertEqual(command_timing(bot, "osac c"), ("sac", 1))
        self.assertEqual(command_timing(bot, "oupgrade efficiency 1"), ("upgrade", 1))
        self.assertEqual(command_timing(bot, "ohuntbot 100"), ("huntbot", 1))

    def test_actual_verb_keeps_inventory_and_team_timers_separate(self):
        bot = self.make_bot()
        for message, expected in (("ozoo", ("zoo", 45)), ("oteam", ("team", 3)),
                                  ("oinventory", ("inv", 10)), ("oweapon", ("weapons", 5))):
            self.assertEqual(command_timing(bot, message), expected)

    def test_matching_active_custom_commands_raise_the_floor(self):
        bot = self.make_bot()
        bot.settings_dict.customCommands = NS(enabled=True, commands=[
            NS(enabled=True, command="owo hunt", cooldown=40),
            NS(enabled=True, command="omystery 1", cooldown=12),
            NS(enabled=True, command="hello world", cooldown=30),
            NS(enabled=False, command="oh", cooldown=100),
        ])
        self.assertEqual(command_timing(bot, "owo hunt"), ("hunt", 40))
        self.assertEqual(command_timing(bot, "omystery 1"), ("mystery", 12))
        self.assertEqual(command_timing(bot, "  hello   WORLD "), ("custom:hello world", 30))
        self.assertEqual(command_timing(bot, "oh"), ("hunt", 15))
        bot.settings_dict.customCommands.enabled = False
        self.assertEqual(command_timing(bot, "owo hunt"), ("hunt", 15))
        self.assertEqual(command_timing(bot, "hello world"), (None, 0))

    def test_plain_chat_and_sparse_bots_are_safe(self):
        for message in ("hello there", "hunt", "", " ", None):
            with self.subTest(message=message):
                self.assertEqual(command_timing(NS(), message), (None, 0))
        self.assertEqual(command_timing(NS(), "oh"), ("hunt", 15))
        self.assertEqual(command_timing(NS(), "oflip 10"), ("coinflip", 15))
        self.assertEqual(command_timing(NS(), "osomething 10"), ("something", 0))

    def test_malformed_optional_cooldowns_do_not_escape_as_nan_or_negative(self):
        bot = self.make_bot()
        bot.misc["command_info"] = {"unknown": {"basecd": float("nan")}}
        bot.settings_dict.commands = NS(unknown=NS(cooldown=[float("inf"), 20]),
                                       other=NS(cooldown=[-10, 20]))
        self.assertEqual(command_timing(bot, "ounknown"), ("unknown", 0))
        self.assertEqual(command_timing(bot, "oother"), ("other", 0))


if __name__ == "__main__":
    unittest.main()
