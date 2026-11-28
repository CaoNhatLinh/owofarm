import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.cogs.gems import Gems, gem_tiers
from utils import bot_control, gem_control, gambling_control


class GemSwitchTests(unittest.IsolatedAsyncioTestCase):
    def test_switch_is_strict_boolean_and_blocks_only_gem_consumption(self):
        self.assertEqual(bot_control.validate_settings({"gemsEnabled": False}), {"gemsEnabled": False})
        with self.assertRaises(ValueError):
            bot_control.validate_settings({"gemsEnabled": "false"})
        with patch.object(bot_control, "get_settings", return_value={"gemsEnabled": False}):
            self.assertFalse(gambling_control.enabled("gems"))
            for command in ("ouse 51 65", "ouse 085", "owo use 71"):
                self.assertFalse(gem_control.command_allowed(command, "o", {}))
            for command in ("ouse 50", "ouse 100", "oh", "oinv"):
                self.assertTrue(gem_control.command_allowed(command, "o", {}))
            self.assertFalse(gem_control.command_allowed("x! consume 57", "x! ", {"use":{"normal":"consume"}}))

    def test_live_use_guard_applies_the_new_cap_only_to_selected_account(self):
        account = NS(_dashboard_account_id="100000000000000001")
        with self.assertRaises(ValueError):
            bot_control.validate_settings({"gemSkipAtOrAbove": "invalid"})
        scope_overrides = {account._dashboard_account_id: {"gemSkipAtOrAbove": "mythical"}}
        with patch.object(bot_control, "_settings", dict(bot_control.DEFAULTS)), \
                patch.object(bot_control, "_account_settings", scope_overrides):
            for command in ("ouse 55", "ouse 54 070", "owo use 85", "ouse 62", "OwO EQUIP 055", "OwOeQuIp 055"):
                self.assertFalse(gem_control.command_allowed(command, "o", {}, account))
                self.assertTrue(gem_control.command_allowed(command, "o", {}))
            for command in ("ouse 54 68 75 82", "ouse 50", "ouse 100", "oinv"):
                self.assertTrue(gem_control.command_allowed(command, "o", {}, account))
            self.assertFalse(gem_control.command_allowed("oconsume 55", "o", {"use": {"alias": ["consume"]}}, account))

    async def test_common_cap_never_requests_inventory_or_pauses_hunt(self):
        bot = NS(alias={name: {"normal": name} for name in ("use", "inv")},
                 ch=NS(put_queue=AsyncMock(return_value=True)), stats=NS(no_gem=False),
                 get_nick=lambda _: "Player", channel_id=1, owo_bot_id=2,
                 hunt_disabled=False, log=AsyncMock())
        cog = Gems(bot)
        reply = NS(id=10, content="Player spent 5 cowoncy and caught a fox", channel=NS(id=1), author=NS(id=2))
        config = {**bot_control.DEFAULTS, "gemSkipAtOrAbove": "common"}
        with patch.object(bot_control, "get_settings", return_value=config):
            await cog.on_message(reply)
            await cog.use_gems({}, full=True)
        bot.ch.put_queue.assert_not_awaited()
        bot.log.assert_not_awaited()
        self.assertFalse(bot.hunt_disabled)

    async def test_common_cap_releases_old_gem_stock_hunt_stop_only_once(self):
        gems = NS(clear_inventory_request=Mock(), use_pending_until=20)
        commands = NS(restore_farm_checks=AsyncMock())
        bot = NS(settings_dict=NS(autoUse=NS(gems=NS(enabled=True))),
                 get_cog={"Gems": gems, "Commands": commands}.get,
                 _gems_enabled=True, hunt_disabled=True)
        config = {**bot_control.DEFAULTS, "gemSkipAtOrAbove": "common"}
        with patch.object(bot_control, "get_settings", return_value=config), \
                patch("utils.gambling_control.discard", new_callable=AsyncMock):
            await gem_control.sync(bot)
            await gem_control.sync(bot)
        self.assertFalse(bot.hunt_disabled)
        self.assertTrue(bot.settings_dict.autoUse.gems.enabled)
        commands.restore_farm_checks.assert_awaited_once()
        gems.clear_inventory_request.assert_called_once()

    async def test_disabled_cog_does_not_inspect_inventory_or_queue_gems(self):
        bot = NS(alias={name:{"normal":name} for name in ("use", "inv")}, ch=NS(put_queue=AsyncMock()))
        cog = Gems(bot)
        with patch.object(bot_control, "get_settings", return_value={"gemsEnabled": False}):
            await cog.use_gems({})
            await cog.on_message(NS())
        bot.ch.put_queue.assert_not_awaited()

    async def test_disable_clears_pending_gems_and_inventory_once(self):
        cog = NS(clear_inventory_request=Mock(), use_pending_until=20)
        bot = NS(settings_dict=NS(autoUse=NS(gems=NS(enabled=True))), get_cog=lambda _:cog,
                 ch=NS(set_stat=AsyncMock()), hunt_disabled=True)
        with patch.object(bot_control, "get_settings", return_value={"gemsEnabled": False}), patch("utils.gambling_control.discard", new_callable=AsyncMock) as discard:
            await gem_control.sync(bot)
            await gem_control.sync(bot)
        self.assertEqual([item.args for item in discard.await_args_list], [(bot, "gems"), (bot, "inv")])
        cog.clear_inventory_request.assert_called_once_with()
        self.assertEqual(cog.use_pending_until, 0)
        bot.ch.set_stat.assert_not_awaited()
        self.assertFalse(bot.hunt_disabled)

    async def test_inventory_timeout_frees_gem_request_without_stopping_farm(self):
        bot = NS(alias={name: {"normal": name} for name in ("use", "inv")},
                 ch=NS(put_queue=AsyncMock(return_value=True), set_stat=AsyncMock()),
                 stats=NS(no_gem=False), get_nick=lambda _: "Player", channel_id=1, owo_bot_id=2)
        cog = Gems(bot)
        def result(message_id):
            return NS(id=message_id, content="Player spent 5 cowoncy and caught a fox", channel=NS(id=1), author=NS(id=2))
        with patch.object(bot_control, "get_settings", return_value=bot_control.DEFAULTS), patch("core.cogs.gems.time.monotonic") as clock:
            clock.return_value = 0
            await cog.on_message(result(1))
            self.assertTrue(cog.inventory_check)
            clock.return_value = 5
            await cog.on_message(result(2))
            bot.ch.put_queue.assert_awaited_once_with(cog.inv_cmd, priority=True, wait=False)
            clock.return_value = 60
            await cog.on_message(result(3))
        self.assertEqual(bot.ch.put_queue.await_count, 2)
        self.assertFalse(cog.inv_cmd["checks"])
        bot.ch.set_stat.assert_not_awaited()

    async def test_exhausted_icon_replenishes_only_its_type_and_stale_replies_do_not_repeat(self):
        queued = []

        async def enqueue(command, **kwargs):
            queued.append(command.get("cmd_arguments", "").strip())
            return True

        gems = NS(tiers=dict.fromkeys(gem_tiers, True),
                  gemsToUse={"huntGem": True, "empoweredGem": True, "luckyGem": True, "specialGem": True},
                  dynamicSpecialGem=False)
        bot = NS(settings_dict=NS(autoUse=NS(gems=gems)),
                 alias={name: {"normal": name} for name in ("use", "inv")},
                 ch=NS(put_queue=enqueue), stats=NS(no_gem=False), get_nick=lambda _: "Player",
                 hunt_disabled=False, channel_id=1, owo_bot_id=2)
        cog = Gems(bot)

        async def message(mid, content):
            await cog.on_message(NS(id=mid, content=content, channel=NS(id=1), author=NS(id=2)))

        def hunt(lucky_remaining):
            return ("**🌱 | Player**, hunt is empowered by <:cgem1:11>`[10/25]` <:cgem3:12>`[15/50]` "
                    f"<:ugem4:13>`[{lucky_remaining}/100]` <:cstar:14>`[25/50]` !\nYou found: 🦊")

        with patch.object(bot_control, "get_settings", return_value=bot_control.DEFAULTS):
            await message(10, hunt(0))
            await message(11, "**====== Player's Inventory ======**\n"
                              "`051`<:cgem1:11>³ `065`<:cgem3:12>⁵ `073`<:ugem4:13>³ `079`<:cstar:14>⁸")
            self.assertEqual(queued, ["", "73"])
            await message(12, hunt(0))  # A Hunt sent just before the gem use replied.
            await message(13, "**Player**, you activated a(n) **Uncommon Lucky Gem**!")
            await message(12, hunt(0))  # Stale Hunt received a second time after activation.
            await message(14, hunt(99))
            self.assertEqual(queued, ["", "73"])
            await message(15, hunt(0))  # New expiration can replenish the same type again.
            self.assertEqual(queued, ["", "73", "73"])

    async def test_partial_activation_debits_only_confirmed_stock_and_ignores_other_accounts(self):
        gems = NS(tiers=dict.fromkeys(gem_tiers, True), gemsToUse={"huntGem": True, "empoweredGem": True,
                  "luckyGem": False, "specialGem": False}, dynamicSpecialGem=False)
        bot = NS(settings_dict=NS(autoUse=NS(gems=gems)), alias={name: {"normal": name} for name in ("use", "inv")},
                 ch=NS(put_queue=AsyncMock(return_value=True)), stats=NS(no_gem=False), get_nick=lambda _: "Player",
                 hunt_disabled=False, channel_id=1, owo_bot_id=2)
        cog = Gems(bot)

        async def message(mid, content="", embeds=()):
            await cog.on_message(NS(id=mid, content=content, embeds=embeds, channel=NS(id=1), author=NS(id=2)))

        with patch.object(bot_control, "get_settings", return_value=bot_control.DEFAULTS):
            await message(10, "PlayerTwo spent 5 cowoncy and caught a fox")
            await message(10, "**🌱 | Player Two** spent 5 cowoncy and caught a fox")
            bot.ch.put_queue.assert_not_awaited()
            await message(11, "Player spent 5 cowoncy and caught a fox")
            await message(12, embeds=[NS(description="**Player's Inventory**\n`051`<:cgem1:11>⁰³ `065`<:cgem3:12>⁰²")])
            self.assertEqual(bot.ch.put_queue.await_args.args[0]["cmd_arguments"], "51 65")
            self.assertEqual(cog.available_gems["common"]["051"], 3)
            self.assertEqual(cog.available_gems["common"]["065"], 2)
            await message(14, "Player spent 5 cowoncy and caught a fox")  # Delivered ahead of the activation reply.
            reply = ("**✨ | Player**, you activated the following gems:\n"
                     "**<:cgem1:11> |** A(n) **Common Hunting Gem!**\n"
                     "**🚫 |** you already have an active Empowering gem or you do not own this gem!")
            await message(13, reply)
            await message(13, reply)
            self.assertEqual(cog.available_gems["common"]["051"], 2)
            self.assertEqual(cog.available_gems["common"]["065"], 2)
            self.assertEqual(cog.inventory_refresh_at, 0)
            self.assertEqual(cog.use_pending_until, 0)

    async def test_enable_loads_gems_after_starting_disabled(self):
        bot = NS(settings_dict=NS(autoUse=NS(gems=NS(enabled=False)), commands=NS(hunt=NS(enabled=True))),
                 extensions={}, load_extension=AsyncMock())
        with patch.object(bot_control, "get_settings", return_value={"gemsEnabled": True}):
            await gem_control.sync(bot)
        self.assertTrue(bot.settings_dict.autoUse.gems.enabled)
        bot.load_extension.assert_awaited_once_with("core.cogs.gems")
