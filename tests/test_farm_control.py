import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from utils import bot_control, farm_control, gambling_control
from test_weapons_runtime import make_bot
from core.command_handler import CommandHandler


class FarmSettingsTests(unittest.TestCase):
    def test_switches_independent_strict_and_persistent(self):
        for key in ("huntEnabled","battleEnabled"):
            for bad in (0,1,"true",None):
                with self.assertRaises(ValueError):bot_control.validate_settings({key:bad})
        previous=bot_control.get_settings()
        try:
            with tempfile.TemporaryDirectory() as folder,patch.object(bot_control,"SETTINGS_PATH",Path(folder)/"dashboard.json"):
                bot_control.update_settings({"huntEnabled":False,"battleEnabled":True})
                import json
                saved=json.loads(bot_control.SETTINGS_PATH.read_text())
                self.assertFalse(saved["huntEnabled"])
                self.assertTrue(saved["battleEnabled"])
                self.assertEqual(bot_control.validate_settings(saved),saved)
        finally:
            bot_control._settings.clear();bot_control._settings.update(previous)

    def test_aliases_prefix_spaces_and_other_commands(self):
        config={**bot_control.DEFAULTS,"huntEnabled":False,"battleEnabled":True}
        aliases={"hunt":{"normal":"searchpets"},"battle":{"normal":"fight"}}
        with patch.object(bot_control,"get_settings",return_value=config):
            for command in ("oh","o h","ohunt","ocatch","osearchpets","owo hunt"):
                self.assertFalse(gambling_control.command_allowed(command,"o",aliases),command)
            for command in ("ob","ofight","ohb","ohuntbot","ocf 200","osell c"):
                self.assertTrue(farm_control.command_allowed(command,"o",aliases),command)
            config["huntEnabled"]=True;config["battleEnabled"]=False
            self.assertTrue(gambling_control.command_allowed("owo h","owo ",aliases))
            self.assertFalse(gambling_control.command_allowed("owo b","owo ",aliases))


class FarmRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_farm_cannot_reenter_real_queue(self):
        previous=bot_control.is_running();bot_control.set_running(True)
        client=NS(misc={"command_info":{"hunt":{},"battle":{}}},response_guard=NS(cooling_down=False),log=AsyncMock())
        handler=CommandHandler(client);handler.cmd_priorities={"hunt":1,"battle":2}
        try:
            with patch.object(bot_control,"get_settings",return_value={**bot_control.DEFAULTS,"huntEnabled":False}):
                await handler.put_queue({"id":"hunt"})
                await handler.put_queue({"id":"battle"})
            self.assertEqual(handler.queue.qsize(),1)
            self.assertEqual(handler.queue.get_nowait()[2]["id"],"battle")
            self.assertFalse(handler.cmds_state["hunt"]["in_queue"])
        finally:
            bot_control.set_running(previous)

    async def test_off_discards_only_its_queue_and_on_resumes_once(self):
        bot=make_bot()
        bot.settings_dict.commands=NS(hunt=NS(enabled=True),battle=NS(enabled=True))
        bot.settings_dict.cooldowns=NS(reactionBot=NS(huntAndBattle=False))
        bot.extensions={"core.cogs.hunt":object(),"core.cogs.battle":object()}
        hunt=NS(cmd=dict(id="hunt",cmd_name="h",removed=False))
        bot.get_cog=lambda name:hunt if name=="Hunt" else None
        bot._farm_switches=dict(hunt=True,battle=True)
        bot.ch.cmds_state["hunt"]={"in_queue":True}
        bot.ch.queue.put_nowait((1,1,{"id":"hunt"}))
        bot.ch.queue.put_nowait((2,2,{"id":"battle"}))
        bot.ch.checks=[{"id":"hunt"},{"id":"battle"}]
        config={**bot_control.DEFAULTS,"huntEnabled":False}
        with patch.object(bot_control,"get_settings",return_value=config):
            await farm_control.sync(bot)
            self.assertEqual(bot.ch.queue.qsize(),1)
            self.assertEqual(bot.ch.checks,[{"id":"battle"}])
            self.assertFalse(bot.settings_dict.commands.hunt.enabled)
            bot.ch.put_queue=AsyncMock()
            config["huntEnabled"]=True
            await farm_control.sync(bot);await asyncio.sleep(0)
            await farm_control.sync(bot);await asyncio.sleep(0)
            bot.ch.put_queue.assert_awaited_once_with(hunt.cmd)

    async def test_enabling_missing_cog_loads_just_that_extension(self):
        bot=NS(settings_dict=NS(commands=NS(hunt=NS(enabled=False),battle=NS(enabled=False)),cooldowns=NS(reactionBot=NS(huntAndBattle=False))),extensions={"core.cogs.hunt":object()},load_extension=AsyncMock())
        with patch.object(bot_control,"get_settings",return_value=bot_control.DEFAULTS):
            await farm_control.sync(bot)
        bot.load_extension.assert_awaited_once_with("core.cogs.battle")
