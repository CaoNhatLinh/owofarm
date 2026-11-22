"""Conservative, role-based equipment planning (not a battle simulator)."""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from utils.weapon_equipment import _ROW, _QUALITY, _RANK, _rarity_for_quality, _valid_id, _SLOT


@dataclass(frozen=True)
class Gear:
    weapon_id: str
    name: str
    quality: float
    equipped: bool = False
    favorite: bool = False


# Scaling attributes verified against the upstream weapon implementations.
# Unknown weapons remain untouched, including when selling surplus equipment.
ROLES = {
    "great sword": "att", "bow": "att", "poison dagger": "att",
    "glacial axe": "att", "healing staff": "mag", "spirit staff": "mag",
    "defender's aegis": "tank",
    "flame staff": "mag", "energy staff": "mag", "vampiric staff": "mag",
    "absorption wand": "mag", "leech scythe": "att", "resurrection staff": "mag",
    "arcane scepter": "mag", "purity staff": "hybrid",
}


def weapon_role(gear):
    name = gear.name.casefold()
    return next((role for suffix, role in ROLES.items() if name.endswith(suffix)), None)


def parse_gear(text):
    """All rarity rows, including equipped gear. None means an ambiguous scan."""
    found = {}
    for line in text.splitlines():
        match = _ROW.fullmatch(line)
        if not match:
            if re.match(r"^\s*`[A-Za-z0-9]+`\s+<", line):
                return None
            continue
        wid, body = match.groups()
        name = re.search(r"\*\*([^*\n]+)\*\*", body)
        qualities = _QUALITY.findall(body[name.end():] if name else "")
        if not _valid_id(wid) or not name or len(qualities) != 1:
            return None
        quality = float(qualities[0])
        if not 0 <= quality <= 100:
            return None
        ranks = {r.lower().replace("mythic", "mythical") if r.lower() == "mythic" else r.lower()
                 for r in _RANK.findall(body)}
        if ranks and ranks != {_rarity_for_quality(quality)}:
            return None
        wid = wid.upper()
        gear = Gear(wid, name[1], quality, "➤" in body or bool(re.search(r"\b(equipped|wielding)\b", body, re.I)),
                    bool(re.search(r"[⭐🌟★]|<a?:\w*(?:star|fav)\w*:\d+>|\bfavorit", body, re.I)))
        if wid in found and found[wid] != gear:
            return None
        found[wid] = gear
    return list(found.values())


def team_stats(text):
    result = {}
    matches = list(_SLOT.finditer(text))
    for i, match in enumerate(matches):
        body = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        body = re.sub(r"<a?:(hp|wp|att|str|mag|pr|mr):\d+>", r" \1 ", body, flags=re.I)
        values = {name.lower().replace("str", "att"): float(value.replace(",", ""))
                  for name, value in re.findall(r"\b(hp|wp|att|str|mag|pr|mr)\b\s*`?([\d,]+(?:\.\d+)?)", body, re.I)}
        if {"hp", "wp", "att", "mag", "pr", "mr"} <= values.keys():
            result[int(match[1])] = values
    return result


def role_score(gear, stats):
    role = weapon_role(gear)
    if role is None:
        return None
    if role == "tank":
        base = stats["hp"] / 4 / max(.05, 1 - min(95, (stats["pr"] + stats["mr"]) / 2) / 100)
    elif role == "hybrid":
        base = (stats["att"] + stats["mag"]) / 2
    else:
        base = stats[role]
    # Quality includes passives; WP favours pets able to sustain skills.
    return base * (1 + gear.quality / 100) * (1 + min(stats["wp"], 1000) / 5000)


def plan_equipment(slots, stats, gear):
    """Maximum total role score for up to three pets, with unique weapon IDs.

    Retain unrecognized/favorite equipment. Limit candidates per slot to three:
    with three pets, any lower candidate is dominated by three better choices.
    """
    by_id = {item.weapon_id: item for item in gear}
    active = [s for s in slots if s.has_pet]
    if not active or any(s.position not in stats for s in active):
        return None
    equipped = {s.weapon_id for s in active if s.weapon_id}
    if not equipped <= by_id.keys():
        return None
    options = []
    for slot in active:
        current = by_id.get(slot.weapon_id)
        if current and (current.favorite or weapon_role(current) is None):
            choices = [(current.weapon_id, 0)]
        else:
            choices = []
            for item in gear:
                if item.equipped and item.weapon_id not in equipped:
                    continue  # Gear on other teams is protected.
                score = role_score(item, stats[slot.position])
                if score is not None and not item.favorite:
                    choices.append((item.weapon_id, score))
            choices.sort(key=lambda pair: (-pair[1], pair[0] != slot.weapon_id, pair[0]))
            choices = choices[:3] + [(None, 0)]
        options.append((slot.position, choices))
    best = None
    def search(i, selected, total, unchanged):
        nonlocal best
        if i == len(options):
            key = (total, unchanged)
            if best is None or key > best[0]:
                best = (key, dict(selected))
            return
        position, choices = options[i]
        for wid, score in choices:
            if wid is None or wid not in selected.values():
                selected[position] = wid
                search(i + 1, selected, total + score, unchanged + (wid == active[i].weapon_id))
                del selected[position]
    search(0, {}, 0, 0)
    return best[1] if best else None


def first_zoo_pet(text):
    """First displayed animal with a positive count; ignore headings/zero stock."""
    emojis = json.loads((Path(__file__).parent / "data" / "emojis.json").read_text(encoding="utf-8"))
    tokens = sorted(emojis, key=len, reverse=True)
    pattern = re.compile("(" + "|".join(re.escape(t) for t in tokens) + r")\s*([⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉\d,]+)")
    for match in pattern.finditer(text):
        count = match[2].translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉", "01234567890123456789")).replace(",", "")
        if int(count) > 0:
            name = emojis[match[1]]["name"]
            if re.fullmatch(r"[A-Za-z0-9_]+", name):
                return name
    return None
