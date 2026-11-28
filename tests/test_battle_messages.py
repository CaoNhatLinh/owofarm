import unittest
from types import SimpleNamespace as NS

from core.battle_messages import accept_button, is_battle_result


SCOPE = {"channel_id": 200, "owo_id": 900, "after_id": 1000}
NAMES = {
    "sender_names": ("Acc Một", "first_account"),
    "receiver_names": ("Acc Hai", "second_account"),
}


def battle_message(title, footer, **kwargs):
    message = {
        "id": 1001,
        "author": NS(id=900),
        "channel": NS(id=200),
        "embeds": [NS(author=NS(name=title), footer=NS(text=footer))],
    }
    return NS(**(message | kwargs))


def invitation():
    button = NS(custom_id="battle_accept", disabled=False)
    other_button = NS(custom_id="battle_decline", disabled=False)
    message = battle_message(
        "Acc Hai, Acc Một challenges you to a duel!",
        "This challenge will expire in 10 minutes",
        content="<@27>",
        components=[NS(children=[button, other_button])],
    )
    message.embeds[0].author.icon_url = "https://cdn.discordapp.com/avatars/26/hash.webp"
    return message, button


class BattleInvitationTests(unittest.TestCase):
    def accept(self, message):
        return accept_button(message, **SCOPE, receiver_id=27, sender_id=26, **NAMES)

    def test_returns_exact_enabled_button_from_fresh_invitation(self):
        message, button = invitation()
        self.assertIs(self.accept(message), button)
        message.reference = NS(message_id=1000)
        self.assertIs(self.accept(message), button)
        message.embeds[0].author.icon_url = "https://cdn.discordapp.com/embed/avatars/4.png"
        self.assertIs(self.accept(message), button)

    def test_wrong_recipient_sender_room_or_reference_never_offers_click(self):
        for change in (
            {"id": 1000}, {"content": "<@26>"}, {"channel": NS(id=201)},
            {"author": NS(id=901)}, {"reference": NS(message_id=999)},
        ):
            with self.subTest(change=change):
                message, _ = invitation()
                self.assertIsNone(self.accept(NS(**(vars(message) | change))))

        message, _ = invitation()
        message.embeds[0].author.icon_url = "https://media.discordapp.net/guilds/55/users/267/avatars/hash.png"
        self.assertIsNone(self.accept(message))
        message.embeds[0].author.icon_url = "https://media.discordapp.net/guilds/55/users/26/avatars/hash.png"
        self.assertIsNotNone(self.accept(message))
        message.embeds[0].author.name = "Acc Hai, Acc Một khác challenges you to a duel!"
        self.assertIsNone(self.accept(message))

    def test_unconfirmed_duplicate_names_are_ambiguous(self):
        message, button = invitation()
        message.embeds[0].author.name = "Acc Hai, Acc Hai challenges you to a duel!"
        same_names = {"sender_names": ("Acc Hai",), "receiver_names": ("Acc Hai",)}
        self.assertIs(accept_button(message, **SCOPE, receiver_id=27, sender_id=26, **same_names), button)
        message.embeds[0].author.icon_url = None
        self.assertIsNone(accept_button(message, **SCOPE, receiver_id=27, sender_id=26, **same_names))

    def test_disabled_duplicate_completed_or_wagered_invite_is_ignored(self):
        message, button = invitation()
        message.components[0].children.append(button)
        self.assertIsNone(self.accept(message))
        message.components[0].children.pop()
        button.disabled = True
        self.assertIsNone(self.accept(message))
        button.disabled = False
        message.embeds[0].description = "`owo ab 50` to accept the battle with the bet!"
        self.assertIsNone(self.accept(message))
        message.embeds[0].description = ""
        message.embeds[0].footer.text = "The battle was accepted!"
        self.assertIsNone(self.accept(message))


class BattleResultTests(unittest.TestCase):
    def result(self, message):
        return is_battle_result(message, **SCOPE, **NAMES)

    def test_both_pair_title_orders_and_native_participant_title(self):
        self.assertTrue(self.result(battle_message("Acc Hai vs Acc Một", "Acc Hai wins!")))
        self.assertTrue(self.result(battle_message("Acc Một vs second_account", "Acc Một wins!")))
        self.assertTrue(self.result(battle_message("Acc Một goes into battle!", "Acc Hai wins!")))
        self.assertTrue(self.result(battle_message("Acc Một goes into battle!", "It's a tie in 4 turns!")))
        self.assertTrue(self.result(battle_message("Acc Hai vs Acc Một", "Battle was too long! It's a tie!")))

    def test_only_completed_new_friendly_result_counts(self):
        for title, footer in (
            ("Acc Hai, Acc Một challenges you to a duel!", "The battle was accepted!"),
            ("Acc Hai vs Acc Một", "Turn 2/3"),
            ("Acc Một goes into battle!", "You won in 3 turns! Your team gained 50 xp"),
            ("Acc Hai vs Unrelated", "Acc Hai wins!"),
            ("Acc Hai goes into battle!", "Acc Hai wins!"),
            ("Unrelated goes into battle!", "Acc Hai wins!"),
            ("Acc Hai goes into battle!", "Acc Một Junior wins!"),
            ("Acc Hai goes into battle!", "It's a tie in 4 turns! Your team gained 50 xp"),
        ):
            with self.subTest(title=title, footer=footer):
                self.assertFalse(self.result(battle_message(title, footer)))

        for change in ({"id": 1000}, {"channel": NS(id=204)}, {"author": NS(id=901)}):
            self.assertFalse(self.result(battle_message("Acc Hai vs Acc Một", "Acc Hai wins!", **change)))

    def test_intermediate_embed_is_recognized_only_after_final_edit(self):
        message = battle_message("Acc Một goes into battle!", "Turn 1/4")
        self.assertFalse(self.result(message))
        message.embeds[0].footer.text = "Acc Hai wins!"
        self.assertTrue(self.result(message))
