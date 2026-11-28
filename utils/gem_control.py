"""Dashboard switch for automatically consuming new gems."""
from utils import bot_control


def enabled(bot=None):
    return bot_control.settings_for(bot).get("gemsEnabled", True)


def allowed_rarities(settings):
    rarities = bot_control.GEM_RARITIES
    limit = settings.get("gemSkipAtOrAbove", "none")
    return rarities if limit == "none" else rarities[:rarities.index(limit)]


def command_allowed(message, prefix, aliases, bot=None):
    settings = bot_control.settings_for(bot)
    allowed = allowed_rarities(settings) if settings.get("gemsEnabled", True) else ()
    rarities = bot_control.GEM_RARITIES
    if allowed == rarities:
        return True
    aliases = aliases.get("use", {})
    names = {"use", "equip"}
    names.update(v.casefold() for v in (*aliases.values(), *aliases.get("alias", [])) if isinstance(v, str))
    message = message.casefold()
    for candidate in sorted({prefix.casefold(), "owo", "uwu"}, key=len, reverse=True):
        if not message.startswith(candidate):
            continue
        parts = message[len(candidate):].split()
        if parts and parts[0].casefold() in names:
            ids = (int(part) for part in parts[1:] if part.isascii() and part.isdigit())
            # OwO assigns each seven-ID gem type block from Common to Fabled.
            return all(rarities[(gem_id - 51) % 7] in allowed for gem_id in ids if 51 <= gem_id <= 85)
    return True


def apply_flags(bot):
    auto_use = getattr(bot.settings_dict, "autoUse", None)
    if auto_use and hasattr(auto_use, "gems"):
        auto_use.gems.enabled = enabled(bot)


async def sync(bot):
    auto_use = getattr(bot.settings_dict, "autoUse", None)
    if not auto_use or not hasattr(auto_use, "gems"):
        return
    apply_flags(bot)
    config = bot_control.settings_for(bot)
    state = config.get("gemsEnabled", True) and bool(allowed_rarities(config))
    if not state and getattr(bot, "_gems_enabled", None) is not False:
        from utils.gambling_control import discard
        await discard(bot, "gems")
        await discard(bot, "inv")
        cog = bot.get_cog("Gems")
        if cog:
            cog.clear_inventory_request()
            cog.use_pending_until = 0
            cog.pending_use_ids = ()
            cog.inventory_refresh_at = 0
        was_hunt_disabled = getattr(bot, "hunt_disabled", False)
        bot.hunt_disabled = False
        if was_hunt_disabled:
            restore = getattr(bot.get_cog("Commands"), "restore_farm_checks", None)
            if restore:
                await restore()
    elif state and bot.settings_dict.commands.hunt.enabled and "core.cogs.gems" not in bot.extensions:
        await bot.load_extension("core.cogs.gems")
    bot._gems_enabled = state
