"""Resolve command aliases and minimum intervals at the outgoing boundary."""

import math
from collections.abc import Mapping


BUILTIN_MINIMUMS = {
    "cash": 5, "hunt": 15, "battle": 15, "gems": 5, "weapons": 5,
    "inv": 10, "zoo": 45, "team": 3, "owo": 10, "lootbox": 5,
    "crate": 5, "huntbot": 1, "coinflip": 15, "slots": 15, "blackjack": 15,
    "pray": 300, "quest": 5, "cookie": 5, "daily": 5, "lottery": 5,
    "level": 15, "sell": 1, "sac": 1, "shop": 4, "upgrade": 1,
    "army": 60, "piku": 60, "pup": 60, "run": 60, "action": 5,
}

BUILTIN_ALIASES = {
    "cash": ("cash", "money", "currency", "cowoncy", "credit", "balance"),
    "hunt": ("hunt", "h", "catch"),
    "battle": ("battle", "b", "fight"),
    "owo": ("owo", "uwu"),
    "sac": ("sac", "sacrifice", "essence", "sc"),
    "lottery": ("lottery", "bet", "lotto"),
    "cookie": ("cookie", "rep"),
    "shop": ("shop", "market", "buy"),
    "huntbot": ("huntbot", "autohunt", "hb", "ah"),
    "zoo": ("zoo", "z"),
    "gems": ("gems", "use", "equip"),
    "weapons": ("weapon", "weapons", "w", "weap"),
    "team": ("team", "tm", "squad"),
    "lootbox": ("lootbox", "lb"),
    "crate": ("crate", "wc"),
    "coinflip": ("coinflip", "cf", "coin", "flip"),
    "slots": ("slots", "s", "slot"),
    "blackjack": ("blackjack", "bj"),
    "inv": ("inv", "inventory"),
    "upgrade": ("upgrade", "upg"),
    "quest": ("quest", "q"),
    "pray": ("pray", "curse"),
}


def _get(source, key, default=None):
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _names(value):
    if isinstance(value, str):
        yield value.casefold()
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _names(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _names(item)


def _canonical(name):
    name = name.casefold()
    for canonical, names in BUILTIN_ALIASES.items():
        if name in names:
            return canonical
    return name


def _seconds(value):
    if isinstance(value, bool):
        return 0.0
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def _cooldown_minimum(configuration):
    cooldown = _get(configuration, "cooldown", ())
    if not isinstance(cooldown, (list, tuple)) or not cooldown:
        return 0.0
    return _seconds(cooldown[0])


def _custom_minimum(configuration, message):
    custom = _get(configuration, "customCommands")
    if _get(custom, "enabled", True) is False:
        return 0.0
    commands = _get(custom, "commands", ())
    if not isinstance(commands, (list, tuple)):
        return 0.0
    normalized = " ".join(message.split()).casefold()
    return max((
        _seconds(_get(command, "cooldown"))
        for command in commands
        if _get(command, "enabled", False)
        and isinstance(_get(command, "command"), str)
        and " ".join(_get(command, "command").split()).casefold() == normalized
    ), default=0.0)


def command_timing(bot, message):
    """Return a shared command key and its minimum; plain chat has no key."""
    if not isinstance(message, str) or not message.strip():
        return None, 0.0
    message = message.strip()
    folded = message.casefold()
    configuration = _get(bot, "settings_dict")
    custom_minimum = _custom_minimum(configuration, message)
    if folded in {"owo", "uwu"}:
        key = "owo"
    else:
        prefix = _get(configuration, "prefix", "o")
        prefixes = {"owo ", "uwu "}
        if isinstance(prefix, str) and prefix:
            prefixes.add(prefix.casefold())
        verb = None
        for candidate in sorted(prefixes, key=len, reverse=True):
            if folded.startswith(candidate):
                parts = folded[len(candidate):].split()
                if parts:
                    verb = parts[0]
                    break
        if verb is None:
            return ("custom:" + " ".join(folded.split()), custom_minimum) if custom_minimum else (None, 0.0)
        key = _canonical(verb)
        aliases = _get(bot, "alias", {})
        if isinstance(aliases, Mapping):
            for canonical, names in aliases.items():
                if isinstance(canonical, str) and verb in _names(names):
                    key = _canonical(canonical)
                    break

    info = _get(_get(bot, "misc"), "command_info", {})
    base = _seconds(_get(_get(info, key), "basecd", BUILTIN_MINIMUMS.get(key, 0)))
    commands = _get(configuration, "commands")
    command_names = ("pray", "curse") if key == "pray" else ("lvlGrind" if key == "level" else key,)
    minimum = max(base, custom_minimum, *(
        _cooldown_minimum(_get(commands, name)) for name in command_names
    ))
    if key in {"coinflip", "slots", "blackjack"}:
        minimum = max(minimum, _cooldown_minimum(_get(_get(configuration, "gamble"), key)))
    return key, minimum
