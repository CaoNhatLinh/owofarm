"""Persistent catch totals, independent of inventory sales and session restarts."""

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from utils.weapon_equipment import extract_message_text

DB_PATH = Path(__file__).resolve().parent / "data" / "rare_catches.sqlite"
RANKS = ("legendary", "gem", "distorted", "fabled", "hidden")
LABELS = ("Legendary", "Gem", "Distorted", "Fabled", "Hidden")
with (Path(__file__).resolve().parent / "data" / "emojis.json").open(encoding="utf-8") as file:
    CATALOG = {data["name"]: data for data in json.load(file).values()
               if data["rank"] in RANKS}
EMOJI = re.compile(r"<a?:(\w+):\d+>|(?<!<):([\w]+):")


def parse_catch(text):
    # Only the result after the hunt marker, never an inventory or quoted nickname.
    marker = re.search(r"\byou found\s*:|\bcaught\b", text, re.I)
    if not marker:
        return {}
    # Hunt's following lines award XP to the team and repeat equipped pet
    # emojis. Only the first result line contains animals just caught.
    lines = [line.strip() for line in text[marker.end():].splitlines()
             if line.strip(" *`_|\t\r")]
    if not lines:
        return {}
    caught_line = lines[0]
    result = {}
    for match in EMOJI.finditer(caught_line):
        name = match.group(1) or match.group(2)
        data = CATALOG.get(name)
        if not data:
            continue
        tail = caught_line[match.end():]
        quantity = re.match(r"\s*(?:\*\*)?[x×]([\d,]+)", tail)
        count = int(quantity.group(1).replace(",", "")) if quantity else 1
        if count > 0:
            result[name] = result.get(name, 0) + count
    return result


def owned_catch(message, owner_id, names, channel_id, owo_id):
    if getattr(getattr(message, "author", None), "id", None) != owo_id:
        return {}
    channel = getattr(getattr(message, "channel", None), "id", None) or getattr(message, "channel_id", None)
    if str(channel) != str(channel_id):
        return {}
    text = extract_message_text(message)
    marker = re.search(r"\byou found\s*:|\bcaught\b", text, re.I)
    if not marker:
        return {}
    header = text[:marker.start()]
    mentions = re.findall(r"<@!?(\d+)>", header)
    plain = re.sub(r"[*~`]", "", header).casefold()
    owned = str(owner_id) in mentions if mentions else any(
        re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", plain)
        for name in names if name)
    return parse_catch(text) if owned else {}


@contextmanager
def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS catches (account TEXT, message TEXT, animal TEXT, count INTEGER, PRIMARY KEY(account,message,animal))")
            yield conn
    finally:
        conn.close()


def record(account, message_id, counts, path=DB_PATH):
    if not message_id or not counts:
        return
    with connect(path) as conn:
        for name, count in counts.items():
            if name not in CATALOG or not isinstance(count, int) or count <= 0:
                continue
            # Native + raw gateway deliveries and edits represent the same catch.
            conn.execute("INSERT INTO catches VALUES (?,?,?,?) ON CONFLICT(account,message,animal) DO UPDATE SET count=MAX(count,excluded.count)",
                         (str(account), str(message_id), name, count))


def snapshot(path=DB_PATH):
    with connect(path) as conn:
        rows = conn.execute("SELECT animal,SUM(count) FROM catches GROUP BY animal").fetchall()
    counts = dict(rows)
    groups = []
    for rank, label in zip(RANKS, LABELS):
        animals = [{"name": name, "count": counts.get(name, 0)}
                   for name, data in CATALOG.items() if data["rank"] == rank]
        animals.sort(key=lambda item: (-item["count"], item["name"]))
        groups.append({"rank": rank, "label": label, "total": sum(a["count"] for a in animals), "animals": animals})
    return {"total": sum(g["total"] for g in groups), "groups": groups}
