"""Independent hunt/battle switches, including queued retries and direct sends."""
import asyncio
from utils import bot_control

FARMS = ("hunt", "battle")


def enabled(command):
    return bot_control.get_settings().get(command + "Enabled", True) if command in FARMS else True


def command_kind(message, prefix, aliases):
    for candidate in sorted({prefix, "owo ", "uwu "}, key=len, reverse=True):
        if not message.startswith(candidate):
            continue
        parts = message[len(candidate):].split()
        if not parts:
            continue
        for kind, names in (("hunt", {"hunt", "h", "catch"}), ("battle", {"battle", "b"})):
            names.update(v.casefold() for v in aliases.get(kind, {}).values() if isinstance(v, str))
            if parts[0].casefold() in names:
                return kind
    return None


def command_allowed(message, prefix, aliases):
    return enabled(command_kind(message, prefix, aliases))


def apply_flags(bot):
    commands = getattr(bot.settings_dict, "commands", None)
    if commands:
        for kind in FARMS:
            getattr(commands, kind).enabled = enabled(kind)


async def sync(bot):
    if not hasattr(bot.settings_dict, "commands"):
        return
    from utils.gambling_control import discard
    apply_flags(bot)
    previous = getattr(bot, "_farm_switches", {})
    current = {kind: enabled(kind) for kind in FARMS}
    reaction = bot.settings_dict.cooldowns.reactionBot.huntAndBattle
    for kind, state in current.items():
        if not state:
            if previous.get(kind) is not False:
                await discard(bot, kind)
            continue
        if reaction:
            extension = "core.cogs.reactionbot"
            if extension not in bot.extensions:
                await bot.load_extension(extension)
            elif previous.get(kind) is False:
                cog = bot.get_cog("Reactionbot")
                if cog:
                    asyncio.create_task(cog.send_cmd(kind))
        else:
            extension = "core.cogs." + kind
            if extension not in bot.extensions:
                await bot.load_extension(extension)
            elif previous.get(kind) is False:
                cog = bot.get_cog(kind.title())
                if cog:
                    cmd = dict(cog.cmd, removed=False)
                    asyncio.create_task(bot.ch.put_queue(cmd))
    bot._farm_switches = current
