"""Dashboard switch for automatically consuming new gems."""
from utils import bot_control


def enabled():
    return bot_control.get_settings().get("gemsEnabled", True)


def command_allowed(message, prefix, aliases):
    if enabled():
        return True
    names = {"use"}
    names.update(v.casefold() for v in aliases.get("use", {}).values() if isinstance(v, str))
    for candidate in sorted({prefix, "owo ", "uwu "}, key=len, reverse=True):
        if not message.startswith(candidate):
            continue
        parts = message[len(candidate):].split()
        if parts and parts[0].casefold() in names:
            return not any(part.isascii() and part.isdigit() and 51 <= int(part) <= 85 for part in parts[1:])
    return True


def apply_flags(bot):
    auto_use = getattr(bot.settings_dict, "autoUse", None)
    if auto_use and hasattr(auto_use, "gems"):
        auto_use.gems.enabled = enabled()


async def sync(bot):
    auto_use = getattr(bot.settings_dict, "autoUse", None)
    if not auto_use or not hasattr(auto_use, "gems"):
        return
    apply_flags(bot)
    state = enabled()
    if not state and getattr(bot, "_gems_enabled", None) is not False:
        from utils.gambling_control import discard
        await discard(bot, "gems")
        cog = bot.get_cog("Gems")
        if cog:
            waiting = cog.inventory_check or bool(cog.cache_gems_in_use)
            cog.inventory_check = False
            cog.cache_gems_in_use = {}
            cog.already_checked = False
            if waiting:
                await bot.ch.set_stat(True)
        bot.hunt_disabled = False
    elif state and bot.settings_dict.commands.hunt.enabled and "core.cogs.gems" not in bot.extensions:
        await bot.load_extension("core.cogs.gems")
    bot._gems_enabled = state
