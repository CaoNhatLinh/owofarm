import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.huntbot import Huntbot, HuntbotPanel, _remaining


def status_embed(name="Acc Uno", account_id=1):
    return NS(
        author=NS(name=f"{name}'s HuntBot", icon_url=f"https://cdn.discordapp.com/avatars/{account_id}/sample.png"),
        fields=[
            NS(name="Efficiency - `25/H`", value="`Lvl 0 [0/10]`"),
            NS(name="Cost - `10 cowoncy`", value="`Lvl 0 [0/1000]`"),
            NS(name="Animal Essence - `10`", value="`Current Max Autohunt: 125 animals, 0 essence, and 0 xp for 1,250 cowoncy`"),
        ],
    )


class HuntbotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100
        self.config = {"huntbotEnabled": True, "huntbotMax": True, "huntbotUpgradeEnabled": False}
        upgrader = NS(get_enabled_traits=lambda: ["efficiency"], get_cd=lambda: 10, weights=NS(efficiency=4))
        self.bot = NS(
            cm=NS(id=8), user=NS(id=1), owo_bot_id=99,
            settings_dict=NS(prefix="o", commands=NS(huntbot=NS(cashToSpend=130, upgrader=upgrader))),
            stats=NS(balance=501, has_updated_balance=True),
            response_guard=NS(ready=True), ch=NS(should_not_send=False),
            get_nick=lambda _: "Acc Uno", update_cash=Mock(), log=AsyncMock(),
            alias={"huntbot": {"normal": "ah"}, "cash": {"normal": "cash"}, "upgrade": {"normal": "upg"}},
            misc={"command_info": {kind: {"log_color": "#000"} for kind in ("huntbot", "cash", "upgrade")}},
        )
        self.bot.send = AsyncMock(side_effect=self.allow_send)
        self.cog = Huntbot(self.bot)
        for target, value in [
            ("core.cogs.huntbot.monotonic", lambda: self.now),
            ("core.cogs.huntbot.bot_control.settings_for", lambda _: self.config),
            ("core.cogs.huntbot.bot_control.running_for", lambda _: True),
        ]:
            change = patch(target, side_effect=value)
            change.start()
            self.addCleanup(change.stop)

    def allow_send(self, _text, _color, *, automation_check, **_):
        return automation_check()

    def sent_commands(self):
        return [call.args[0] for call in self.bot.send.await_args_list]

    async def receive(self, content="", *, embeds=(), message_id=10, author=99):
        await self.cog.on_message(NS(
            author=NS(id=author), content=content, embeds=embeds, channel=self.bot.cm,
            guild=NS(id=7), id=message_id,
        ))

    async def wait_for_huntbot_wallet(self):
        await self.cog.step()
        await self.receive(embeds=[status_embed()])
        await self.cog.step()
        self.assertEqual(self.sent_commands(), ["oah", "ocash"])

    async def test_team_readiness_and_disabled_switch_hold_all_huntbot_actions(self):
        self.config["teamSetupEnabled"] = True
        await self.cog.step()
        self.bot.send.assert_not_awaited()
        self.assertEqual(self.bot.response_guard.huntbot_status["state"], "waiting-team")
        self.bot._team_setup_ready = True
        self.config["huntbotEnabled"] = False
        await self.cog.step()
        self.bot.send.assert_not_awaited()
        self.config["huntbotEnabled"] = True
        await self.cog.step()
        self.assertEqual(self.sent_commands(), ["oah"])

    async def test_max_spend_uses_owned_cash_panel_balance_and_rounding(self):
        await self.wait_for_huntbot_wallet()
        await self.receive("Acc Uno Two, you currently have **__2,000 cowoncy!__**")
        await self.cog.step()
        self.assertEqual(self.sent_commands(), ["oah", "ocash"])
        await self.receive("Acc Uno, you currently have **__2,000 cowoncy!__**")
        await self.cog.step()
        self.assertEqual(self.sent_commands()[-1], "oah 500")
        self.assertEqual(self.bot.response_guard.huntbot_status["maxCost"], 1250)

    async def test_unknown_or_insufficient_wallet_does_not_spend(self):
        await self.wait_for_huntbot_wallet()
        await self.receive("Acc Uno, you currently have **__8 cowoncy!__**")
        await self.cog.step()
        self.assertEqual(self.sent_commands(), ["oah", "ocash"])
        self.assertEqual(self.bot.response_guard.huntbot_status["state"], "balance")
        self.assertEqual(self.bot.response_guard.huntbot_status["amount"], 0)

    async def test_max_stake_never_exceeds_the_current_owo_cap(self):
        self.bot.stats.balance = 1_000_000
        await self.wait_for_huntbot_wallet()
        await self.receive("Acc Uno, you currently have **__1,000,000 cowoncy!__**")
        await self.cog.step()
        self.assertEqual(self.sent_commands()[-1], "oah 1250")

    async def test_accepted_manual_challenge_clears_notice_without_submitting_a_password(self):
        await self.wait_for_huntbot_wallet()
        await self.receive("Acc Uno, you currently have **__500 cowoncy!__**")
        await self.cog.step()
        await self.receive("Acc Uno, Here is your password! Use the command `owo autohunt 500 {password}`")
        self.assertEqual(self.bot.response_guard.huntbot_captcha, {"guildId": "7", "channelId": "8", "messageId": "10", "amount": 500})
        self.now += 900
        await self.cog.step()
        self.assertEqual(self.sent_commands(), ["oah", "ocash", "oah 500"])
        successful_hunt = (
            "**<:huntbot:123> |** `BEEP BOOP. `**`Acc Uno`**`, YOU SPENT 500 cowoncy`\n"
            "**<:blank:427371936482328596> |** `I WILL BE BACK IN 1H5M WITH 50 ANIMALS,`\n"
            "**<:blank:427371936482328596> |** `500 ESSENCE, AND 320 EXPERIENCE`"
        )
        await self.receive(successful_hunt.replace("Acc Uno", "Acc Uno2"), message_id=11)
        self.assertIsNotNone(self.bot.response_guard.huntbot_captcha)
        await self.receive(successful_hunt, message_id=12)
        await self.receive(successful_hunt, message_id=12)
        self.assertIsNone(self.bot.response_guard.huntbot_captcha)
        self.assertEqual(self.bot.response_guard.huntbot_status["state"], "hunting")
        self.assertEqual(self.cog.active_until, self.now + 3900)
        self.bot.update_cash.assert_called_once_with(500, reduce=True)

    async def test_upgrade_only_when_enabled_and_confirms_new_limits_for_next_stake(self):
        self.config["huntbotUpgradeEnabled"] = True
        await self.cog.step()
        await self.receive(embeds=[status_embed()])
        await self.cog.step()
        self.assertEqual(self.sent_commands(), ["oah", "oupg efficiency 10"])
        await self.receive("Acc Uno, You successfully upgraded `efficiency` with **10 Animal Essence**.")
        await self.cog.step()
        self.assertEqual(self.sent_commands(), ["oah", "oupg efficiency 10"])
        self.now += 10
        await self.cog.step()
        self.assertEqual(self.sent_commands(), ["oah", "oupg efficiency 10", "oah"])

    async def test_toggle_cancels_stale_max_stake_before_transport(self):
        await self.wait_for_huntbot_wallet()
        await self.receive("Acc Uno, you currently have **__500 cowoncy!__**")

        def switched_budget(_text, _color, *, automation_check, **_):
            self.config["huntbotMax"] = False
            self.assertFalse(automation_check())
            return False

        self.bot.send.side_effect = switched_budget
        await self.cog.step()
        self.now += 3
        self.bot.send.side_effect = self.allow_send
        await self.cog.step()
        self.assertEqual(self.sent_commands()[-1], "oah 130")


class HuntbotPanelTests(unittest.TestCase):
    def test_panel_counts_only_the_time_and_rejects_missing_prices(self):
        fields = status_embed().fields
        active = NS(name="HUNTBOT is currently hunting!", value="`I WILL BE BACK IN 1H 5M`\n`99% DONE | 100 ANIMALS CAPTURED`")
        panel = HuntbotPanel.parse([*fields, active])
        self.assertEqual((panel.max_cost, panel.cost, panel.essence, panel.remaining), (1250, 10, 10, 3900))
        self.assertEqual(_remaining("1D2H3M"), 93780)
        self.assertIsNone(HuntbotPanel.parse([]).max_cost)
