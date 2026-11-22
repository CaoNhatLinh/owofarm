import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from utils import rare_catches as catches


class RareCatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "catches.sqlite"

    def test_multiple_species_and_repeated_catches(self):
        text = "**player** you found:\n<a:gfox:1> <a:gfox:1> <a:glitchzebra:2> <:gspider:3> 🐝"
        self.assertEqual(catches.parse_catch(text), {"gfox": 2, "glitchzebra": 1, "gspider": 1})
        self.assertEqual(catches.parse_catch("player caught :glion: **x3**"), {"glion": 3})
        self.assertEqual(catches.parse_catch("player zoo :glion:"), {})
        self.assertEqual(catches.parse_catch("<:gfox:1> you found: 🐝"), {})
        self.assertEqual(catches.parse_catch("player you found:\n🐝\nYour team <:gfox:1> <:glion:2> gained XP"), {})
        self.assertEqual(catches.parse_catch("player caught <:gfox:1>\nTeam <:gfox:1> <:glion:2> gained XP"), {"gfox": 1})
        self.assertEqual(catches.parse_catch("player **you found:**\n<:gfox:1>\nTeam <:glion:2> gained XP"), {"gfox": 1})

    def test_native_and_raw_and_edit_do_not_duplicate(self):
        catches.record("1", "100", {"gfox": 2}, self.path)
        catches.record("1", "100", {"gfox": 2}, self.path)
        catches.record("1", "100", {"gfox": 2, "glion": 1}, self.path)
        catches.record("1", "101", {"gfox": 1}, self.path)
        catches.record("2", "102", {"gfox": 1}, self.path)
        data = catches.snapshot(self.path)
        self.assertEqual(data["total"], 5)
        animals = {a["name"]: a["count"] for g in data["groups"] for a in g["animals"]}
        self.assertEqual(animals["gfox"], 4)
        self.assertEqual(animals["glion"], 1)
        self.assertEqual(animals["glitchzebra"], 0)
        self.assertEqual(catches.snapshot(self.path), data)

    def test_owner_channel_author_filters(self):
        message = NS(id=10, author=NS(id=999), channel=NS(id=123), content="**player** caught <:glion:1>", embeds=[], components=[])
        self.assertEqual(catches.owned_catch(message, 1, {"player"}, 123, 999), {"glion": 1})
        self.assertEqual(catches.owned_catch(message, 1, {"play"}, 123, 999), {})
        self.assertEqual(catches.owned_catch(message, 1, {"player"}, 124, 999), {})
        self.assertEqual(catches.owned_catch(message, 1, {"player"}, 123, 998), {})
        message.content = "<@2> player caught <:glion:1>"
        self.assertEqual(catches.owned_catch(message, 1, {"player"}, 123, 999), {})
        message.content = "<@1> caught <:glion:1>"
        message.channel = None
        message.channel_id = 123
        self.assertEqual(catches.owned_catch(message, 1, set(), 123, 999), {"glion": 1})

    def test_empty_state_has_all_species_and_excludes_lower_ranks(self):
        data = catches.snapshot(self.path)
        self.assertEqual(data["total"], 0)
        self.assertEqual([g["rank"] for g in data["groups"]], list(catches.RANKS))
        self.assertTrue(all(g["animals"] for g in data["groups"]))
        catches.record("1", "100", {"bee": 4, "gfox": -1}, self.path)
        self.assertEqual(catches.snapshot(self.path)["total"], 0)


if __name__ == "__main__":
    unittest.main()
