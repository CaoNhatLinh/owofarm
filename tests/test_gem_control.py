import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from core.cogs.gems import Gems
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

    async def test_disabled_cog_does_not_inspect_inventory_or_queue_gems(self):
        bot = NS(alias={name:{"normal":name} for name in ("use", "inv")}, ch=NS(put_queue=AsyncMock()))
        cog = Gems(bot)
        with patch.object(bot_control, "get_settings", return_value={"gemsEnabled": False}):
            await cog.use_gems({})
            await cog.on_message(NS())
        bot.ch.put_queue.assert_not_awaited()

    async def test_disable_clears_pending_gems_and_releases_inventory_hold_once(self):
        cog = NS(inventory_check=True, cache_gems_in_use={"pending":True}, already_checked=True)
        bot = NS(settings_dict=NS(autoUse=NS(gems=NS(enabled=True))), get_cog=lambda _:cog,
                 ch=NS(set_stat=AsyncMock()), hunt_disabled=True)
        with patch.object(bot_control, "get_settings", return_value={"gemsEnabled": False}), patch("utils.gambling_control.discard", new_callable=AsyncMock) as discard:
            await gem_control.sync(bot)
            await gem_control.sync(bot)
        discard.assert_awaited_once_with(bot, "gems")
        bot.ch.set_stat.assert_awaited_once_with(True)
        self.assertFalse(bot.hunt_disabled)
        self.assertFalse(cog.inventory_check)
        self.assertEqual(cog.cache_gems_in_use, {})

    async def test_enable_loads_gems_after_starting_disabled(self):
        bot = NS(settings_dict=NS(autoUse=NS(gems=NS(enabled=False)), commands=NS(hunt=NS(enabled=True))),
                 extensions={}, load_extension=AsyncMock())
        with patch.object(bot_control, "get_settings", return_value={"gemsEnabled": True}):
            await gem_control.sync(bot)
        self.assertTrue(bot.settings_dict.autoUse.gems.enabled)
        bot.load_extension.assert_awaited_once_with("core.cogs.gems")
