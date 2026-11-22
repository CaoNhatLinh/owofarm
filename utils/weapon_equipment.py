"""Read OwO equipment text without guessing equipment from battle WP."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class WeaponCandidate:
    weapon_id: str
    rarity: str
    quality: float


@dataclass(frozen=True)
class TeamSlot:
    position: int
    has_pet: bool
    weapon_id: str | None


_ROW = re.compile(r"^\s*`([A-Za-z0-9]{1,9})`\s+(.+)$")
_QUALITY = re.compile(r"(?<![\w.+-])(\d+(?:\.\d+)?)\s*%")
_RANK = re.compile(
    r"<a?:(common|uncommon|rare|epic|mythic|mythical|legendary|fabled):\d+>",
    re.IGNORECASE,
)
_SLOT = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\[([123])\]\s*(.*?)\s*$", re.MULTILINE
)
_EMOJI = re.compile(r"<a?:([A-Za-z0-9_]+):\d+>")
_STAT_NAMES = {"hp", "wp", "att", "str", "mag", "pr", "mr"}
_PAGE_LABEL = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$", re.MULTILINE)


def _valid_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]{1,9}", value)) and int(value, 36) > 0


def _rarity_for_quality(quality: float) -> str:
    for maximum, rarity in ((20, "common"), (40, "uncommon"), (60, "rare"),
                            (80, "epic"), (94, "mythical"), (99, "legendary")):
        if quality <= maximum:
            return rarity
    return "fabled"


def parse_weapon_inventory(
    text: str, allowed_rarities: set[str]
) -> list[WeaponCandidate]:
    """Return only unassigned Common/Uncommon rows with an explicit quality.

    Equipped rows, ambiguous duplicate IDs and rank/quality disagreements are
    excluded. Help text, team weapon lines and unknown layouts are not rows.
    """
    allowed = {str(value).strip().lower() for value in allowed_rarities}
    allowed &= {"common", "uncommon"}
    candidates: dict[str, WeaponCandidate] = {}
    blocked: set[str] = set()
    for line in text.splitlines():
        match = _ROW.fullmatch(line)
        if not match:
            continue
        weapon_id, body = match.groups()
        weapon_id = weapon_id.upper()
        if not _valid_id(weapon_id):
            continue
        if "➤" in body or re.search(r"\b(?:equipped|wielding)\b", body, re.I):
            blocked.add(weapon_id)
            continue
        name = re.search(r"\*\*[^*\n]+\*\*", body)
        qualities = _QUALITY.findall(body[name.end():] if name else "")
        if not name or len(qualities) != 1:
            blocked.add(weapon_id)
            continue
        quality = float(qualities[0])
        if not 0 <= quality <= 40:
            blocked.add(weapon_id)
            continue
        rarity = _rarity_for_quality(quality)
        ranks = {
            "mythical" if value.lower() == "mythic" else value.lower()
            for value in _RANK.findall(body)
        }
        if ranks and ranks != {rarity}:
            blocked.add(weapon_id)
            continue
        if rarity not in allowed:
            continue
        candidate = WeaponCandidate(weapon_id, rarity, quality)
        previous = candidates.get(weapon_id)
        if previous is not None and previous != candidate:
            blocked.add(weapon_id)
        else:
            candidates[weapon_id] = candidate
    return [candidate for key, candidate in candidates.items() if key not in blocked]


def _stat_line(line: str) -> set[str] | None:
    names = {name.lower() for name in _EMOJI.findall(line)}
    if names:
        if not names <= _STAT_NAMES:
            return None
        remainder = _EMOJI.sub("", line)
    else:
        names = set(re.findall(r"\b(HP|WP|ATT|STR|MAG|PR|MR)\b", line, re.I))
        names = {name.lower() for name in names}
        if not names:
            return None
        remainder = re.sub(r"\b(?:HP|WP|ATT|STR|MAG|PR|MR)\b", "", line, flags=re.I)
    if re.sub(r"[\s`*\d,.%+\-/():|]", "", remainder):
        return None
    return names


def parse_team_slots(text: str) -> list[TeamSlot]:
    """Decode confirmed numbered pet slots, omitting ambiguous sections.

    A pet is only considered unarmed when its level/stat block is understood
    and contains no unknown equipment text. WP values never determine this.
    """
    matches = list(_SLOT.finditer(text))
    slots: dict[int, TeamSlot] = {}
    blocked: set[int] = set()
    for index, match in enumerate(matches):
        position = int(match.group(1))
        header = match.group(2).strip().strip("*").strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        if header.lower() == "none":
            slot = TeamSlot(position, False, None)
        else:
            has_level = False
            stats: set[str] = set()
            weapon_ids: set[str] = set()
            unknown = False
            for raw_line in body.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if re.fullmatch(r"(?:Lvl|Level)\s+\d+(?:\s+`?\[[^\]\n]+/[^\]\n]+\]`?)?", line, re.I):
                    has_level = True
                    continue
                if re.match(r"^(?:Current Streak:|Highest Streak:|Page\s+\d+/\d+)", line, re.I):
                    continue
                page_label = _PAGE_LABEL.fullmatch(line)
                if page_label and 1 <= int(page_label[1]) <= int(page_label[2]):
                    continue
                parsed_stats = _stat_line(line)
                if parsed_stats is not None:
                    stats.update(parsed_stats)
                    continue
                weapon_match = re.match(r"^(?:Weapon\s*:\s*)?`([A-Za-z0-9]{1,9})`(?:\s|$)", line, re.I)
                if weapon_match and _valid_id(weapon_match.group(1)):
                    weapon_ids.add(weapon_match.group(1).upper())
                    continue
                if re.fullmatch(r"(?:Weapon\s*:\s*(?:None|Empty)|No weapon equipped)[.!]?", line, re.I):
                    continue
                unknown = True
            if not header or not has_level or not {"hp", "wp"} <= stats or len(stats) < 4 or unknown or len(weapon_ids) > 1:
                blocked.add(position)
                continue
            slot = TeamSlot(position, True, next(iter(weapon_ids), None))
        previous = slots.get(position)
        if previous is not None and previous != slot:
            blocked.add(position)
        else:
            slots[position] = slot
    return [slot for position, slot in sorted(slots.items()) if position not in blocked]


def parse_inventory_page(text: str) -> tuple[int, int] | None:
    pages = {(int(current), int(total)) for current, total in re.findall(r"\bPage\s+(\d+)\s*/\s*(\d+)\b", text, re.I)}
    pages.update((int(current), int(total)) for current, total in _PAGE_LABEL.findall(text))
    if len(pages) != 1:
        return None
    current, total = next(iter(pages))
    return (current, total) if 1 <= current <= total else None


def extract_message_text(message) -> str:
    """Flatten the text portions of native embeds and raw/native components."""
    output: list[str] = []
    # Embed properties create temporary proxy objects. Keep them alive for this
    # traversal so a later proxy cannot reuse an id and be mistaken for a cycle.
    seen: dict[int, object] = {}
    text_keys = ("content", "text", "title", "description", "name", "value", "label")
    child_keys = ("author", "fields", "footer", "embeds", "components", "children", "accessory")

    def get_value(node, key):
        if isinstance(node, dict):
            return node.get(key)
        try:
            return getattr(node, key, None)
        except Exception:
            return None

    def walk(node, depth=0):
        if node is None or depth > 32:
            return
        if isinstance(node, str):
            if node.strip():
                output.append(node.strip())
            return
        if isinstance(node, (bool, int, float, bytes)) or id(node) in seen:
            return
        seen[id(node)] = node
        if isinstance(node, (list, tuple)):
            for value in node:
                walk(value, depth + 1)
            return
        for key in text_keys:
            value = get_value(node, key)
            if isinstance(value, str):
                walk(value, depth + 1)
        for key in child_keys:
            walk(get_value(node, key), depth + 1)

    walk(message)
    return "\n".join(output)
