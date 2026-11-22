import unittest
from types import SimpleNamespace

import discord

from utils.weapon_equipment import (
    TeamSlot,
    WeaponCandidate,
    extract_message_text,
    parse_inventory_page,
    parse_team_slots,
    parse_weapon_inventory,
)


def weapon_row(weapon_id="A1B2", rarity="common", quality="18", suffix=""):
    return f"`{weapon_id}` <:{rarity}:416520037713838081><:sword:111> **Short Sword** {quality}%{suffix}"


PET_STATS = """Lvl 3 `[100/1081]`
<:hp:531620120410456064> `506` <:wp:531620120976687114> `0`
<:att:531616155450998794> `103` <:mag:531616156231139338> `103`
<:pr:531616156222488606> `21%` <:mr:531616156226945024> `21%`
"""


class InventoryTests(unittest.TestCase):
    def parse(self, text, allowed=None):
        return parse_weapon_inventory(text, allowed or {"common", "uncommon"})

    def test_source_style_rows_across_embed_text(self):
        text = "These weapons belong to <@123456789012345678>\n" + "\n".join([
            weapon_row(), weapon_row("C123", "uncommon", "35"),
            weapon_row("Z9", "rare", "50"),
        ])
        self.assertEqual(self.parse(text), [
            WeaponCandidate("A1B2", "common", 18),
            WeaponCandidate("C123", "uncommon", 35),
        ])

    def test_equipped_weapon_is_never_available(self):
        self.assertEqual(self.parse(weapon_row(suffix=" ➤ 🐶 Dog")), [])

    def test_duplicate_equipped_row_blocks_other_copy(self):
        self.assertEqual(self.parse(weapon_row() + "\n" + weapon_row(suffix=" ➤ 🐶 Dog")), [])

    def test_identical_duplicates_are_deduplicated(self):
        self.assertEqual(len(self.parse(weapon_row() + "\n" + weapon_row())), 1)

    def test_conflicting_duplicates_are_rejected(self):
        self.assertEqual(self.parse(weapon_row() + "\n" + weapon_row(quality="19")), [])

    def test_high_tiers_never_used_even_if_requested(self):
        self.assertEqual(self.parse(weapon_row(rarity="rare", quality="50"), {"rare"}), [])

    def test_rank_quality_disagreement_is_rejected(self):
        self.assertEqual(self.parse(weapon_row(rarity="rare", quality="18")), [])

    def test_common_uncommon_boundary(self):
        self.assertEqual(self.parse(weapon_row(quality="20"))[0].rarity, "common")
        self.assertEqual(self.parse(weapon_row(rarity="uncommon", quality="40"))[0].rarity, "uncommon")
        self.assertEqual(self.parse(weapon_row(rarity="uncommon", quality="40.1")), [])

    def test_selected_rarity_only(self):
        self.assertEqual(self.parse(weapon_row("U1", "uncommon", "35"), {"common"}), [])

    def test_quality_without_rank_can_be_inferred(self):
        self.assertEqual(self.parse("`A1` <:sword:111> **Sword** 21%"), [WeaponCandidate("A1", "uncommon", 21)])

    def test_unknown_and_malformed_rows_are_rejected(self):
        for text in ["Nothing useful", "`A1` <:common:111> 10%", weapon_row("TOOLONG1234"),
                     weapon_row("0"), weapon_row(quality="bad"), weapon_row(quality="-5"),
                     "`A1` **Sword** 10% 20%", "`ABC-12` **Sword** 10%"]:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), [])

    def test_lowercase_id_is_normalized(self):
        self.assertEqual(self.parse(weapon_row("a1b2"))[0].weapon_id, "A1B2")


class TeamTests(unittest.TestCase):
    def test_numbered_source_fields(self):
        text = "Player's Team\n[1] 🐶 **Dog**\n" + PET_STATS
        text += "`ABC123` <:common:111><:sword:222> 12%\n[2] none\n"
        text += "*`owo team add {animal} 2`*\n[3] 🐱 **Cat**\n" + PET_STATS
        text += "Current Streak: 0 | Highest Streak: 0 | Page 1/2 ⭐"
        self.assertEqual(parse_team_slots(text), [
            TeamSlot(1, True, "ABC123"), TeamSlot(2, False, None), TeamSlot(3, True, None)
        ])

    def test_zero_wp_with_weapon_is_still_equipped(self):
        text = "[1] 🐶 **Dog**\n" + PET_STATS + "`ABC123` <:common:111> 18%"
        self.assertEqual(parse_team_slots(text), [TeamSlot(1, True, "ABC123")])

    def test_wp_zero_alone_is_not_an_unarmed_slot(self):
        self.assertEqual(parse_team_slots("[1] Dog\nWP 0"), [])

    def test_unknown_equipment_text_is_not_assumed_missing(self):
        for extra in ["Weapon: unreadable", "`BAD-ID` sword 12%", "Something unexpected"]:
            with self.subTest(extra=extra):
                self.assertEqual(parse_team_slots("[1] 🐶 **Dog**\n" + PET_STATS + extra), [])

    def test_ambiguous_multiple_weapon_ids_are_rejected(self):
        text = "[1] 🐶 **Dog**\n" + PET_STATS + "`A1` sword\n`B2` sword"
        self.assertEqual(parse_team_slots(text), [])

    def test_duplicate_conflicting_slot_is_rejected(self):
        text = "[1] none\n[1] 🐶 **Dog**\n" + PET_STATS
        self.assertEqual(parse_team_slots(text), [])

    def test_markdown_heading_and_plain_stat_labels(self):
        text = "### [2] 🐶 **Dog**\nLvl 2 [0/1000]\nHP 500 WP 0\nATT 100 MAG 100\nPR 20% MR 20%"
        self.assertEqual(parse_team_slots(text), [TeamSlot(2, True, None)])

    def test_inventory_is_not_a_team(self):
        self.assertEqual(parse_team_slots(weapon_row()), [])

    def test_final_team_slot_ignores_v2_page_button_label(self):
        text = "[3] :pig2: **pig**\n" + PET_STATS + "1/1"
        self.assertEqual(parse_team_slots(text), [TeamSlot(3, True, None)])


class PageAndTextTests(unittest.TestCase):
    def test_page_bounds_and_ambiguity(self):
        self.assertEqual(parse_inventory_page("Page 1/2 | Sorting by id"), (1, 2))
        self.assertEqual(parse_inventory_page("PAGE 2 / 20"), (2, 20))
        self.assertEqual(parse_inventory_page("1/1"), (1, 1))
        self.assertEqual(parse_inventory_page("Header\n2 / 3\nFooter"), (2, 3))
        self.assertEqual(parse_inventory_page("Page 1/2\n1/2"), (1, 2))
        for text in ["", "Page 0/2", "Page 3/2", "Page 1/2\nPage 2/2", "1/2\n2/2", "0/2", "3/2",
                     "Lvl 14 `[14,609/39,416]`", "`14609/39416`", "WP 14/39", "HP 2 / 3"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_inventory_page(text))

    def test_production_v2_inventory_and_pagination(self):
        raw = {"content": "", "embeds": [], "components": [{
            "type": 17,
            "components": [
                {"type": 9, "components": [{"type": 10, "content": "## 🗡️ <@123456789012345678>'s Weapons"}]},
                {"type": 10, "content": "\n".join([
                    "`G863V0` <:uncommon:416520056269176842><:ugaxe:618389128077377547><:ucritical:572285186322989057> **Glacial Axe** 32.5%",
                    weapon_row("RARE01", "rare", "59.2"),
                    weapon_row("RARE02", "rare", "56.6"),
                    weapon_row("RARE03", "rare", "50.6"),
                ])},
                {"type": 1, "components": [
                    {"type": 2, "custom_id": "paged_prev", "disabled": False},
                    {"type": 2, "custom_id": "noop", "disabled": True, "label": "1/1"},
                    {"type": 2, "custom_id": "paged_next", "disabled": False},
                ]},
            ],
        }]}
        text = extract_message_text(raw)
        self.assertIn("<@123456789012345678>'s Weapons", text)
        self.assertEqual(parse_inventory_page(text), (1, 1))
        self.assertEqual(parse_weapon_inventory(text, {"common", "uncommon"}), [
            WeaponCandidate("G863V0", "uncommon", 32.5)
        ])

    def test_native_page_button_label(self):
        raw = SimpleNamespace(components=[SimpleNamespace(children=[
            SimpleNamespace(label="2/3", disabled=True, custom_id="noop")
        ])])
        self.assertEqual(parse_inventory_page(extract_message_text(raw)), (2, 3))

    def test_raw_nested_components_and_embed_fields(self):
        message = {
            "content": "Root text",
            "embeds": [{"title": "Inventory", "author": {"name": "Player's weapons"},
                        "description": weapon_row(), "fields": [{"name": "[1] Dog", "value": PET_STATS}],
                        "footer": {"text": "Page 1/2"}}],
            "components": [{"type": 17, "components": [{"type": 9, "components": [{"content": "Nested text"}]}]}],
        }
        text = extract_message_text(message)
        for expected in ["Root text", "Inventory", "Player's weapons", "[1] Dog", "Lvl 3", "Page 1/2", "Nested text"]:
            self.assertIn(expected, text)

    def test_native_component_shapes(self):
        component = SimpleNamespace(children=[SimpleNamespace(text="Native text")])
        message = SimpleNamespace(content="", embeds=[SimpleNamespace(description="Body", fields=[], footer=SimpleNamespace(text="Page 1/1"))], components=[component])
        self.assertEqual(extract_message_text(message), "Body\nPage 1/1\nNative text")

    def test_native_discord_embed_proxies_keep_every_slot_and_owner(self):
        embed = discord.Embed.from_dict({
            "author": {"name": "fixture-player's team"},
            "description": "`owo team add {animal} {pos}` Add an animal to your team",
            "fields": [
                {"name": "[1] :dog2: **dog**", "value": PET_STATS, "inline": True},
                {"name": "[2] :cow2: **cow**", "value": PET_STATS, "inline": True},
                {"name": "[3] :pig2: **pig**", "value": PET_STATS, "inline": True},
            ],
            "footer": {"text": "Current Streak: 0 | Highest Streak: 0 | Page 1/2 ⭐"},
        })
        message = SimpleNamespace(content="", embeds=[embed], components=[])
        for _ in range(20):
            text = extract_message_text(message)
            self.assertIn("fixture-player's team", text)
            self.assertEqual(parse_team_slots(text), [
                TeamSlot(1, True, None), TeamSlot(2, True, None), TeamSlot(3, True, None)
            ])

    def test_cycles_and_shared_nodes_are_safe(self):
        child = {"content": "once"}
        root = {"components": [child, child]}
        root["components"].append(root)
        self.assertEqual(extract_message_text(root), "once")

    def test_no_arbitrary_serialization_or_sensitive_attributes(self):
        message = SimpleNamespace(content="Visible", token="SECRET", headers={"Authorization": "SECRET"})
        self.assertEqual(extract_message_text(message), "Visible")


if __name__ == "__main__":
    unittest.main()
