"""Descriptive, account-scoped side selection; never a prediction of the next flip."""
import re
import sqlite3
from collections import deque
from contextlib import closing
from fractions import Fraction
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "coinflip_history.sqlite"
WINDOW = 500
MIN_SAMPLES = 5
SIDES = ("heads", "tails")


def frequency(rows, window):
    appearances = dict.fromkeys(SIDES, 0)
    for _, side, outcome in rows:
        landed = side if outcome == "win" else ("tails" if side == "heads" else "heads")
        appearances[landed] += 1
    most_common = None if appearances["heads"] == appearances["tails"] else max(SIDES, key=appearances.get)
    return dict(total=len(rows), window=window, appearances=appearances, mostCommon=most_common)


def chosen_side(content):
    # Read what the completed round actually chose, never the current UI setting.
    text = re.sub(r"<a?:\w+:\d+>", " ", content or "")
    text = re.sub(r"[*`_]", "", text)
    match = re.search(r"\bchose\s+(heads?|tails?)\b", text, re.I)
    if not match:
        return None
    return "heads" if match[1].lower().startswith("head") else "tails"


class History:
    def __init__(self, rows=()):
        self.rows = deque(rows, maxlen=WINDOW)

    def record(self, message_id, side, outcome):
        if side not in SIDES or outcome not in ("win", "loss"):
            return False
        key = str(message_id)
        if any(row[0] == key for row in self.rows):
            return False
        self.rows.append((key, side, outcome))
        return True

    def _selection(self, window):
        rows = list(self.rows)[-window:]
        counts = {side: {"wins": 0, "losses": 0, "samples": 0} for side in SIDES}
        appearances = dict.fromkeys(SIDES, 0)
        for _, side, outcome in rows:
            counts[side]["wins" if outcome == "win" else "losses"] += 1
            counts[side]["samples"] += 1
            landed = side if outcome == "win" else ("tails" if side == "heads" else "heads")
            appearances[landed] += 1
        if any(counts[s]["samples"] < MIN_SAMPLES for s in SIDES):
            side = min(SIDES, key=lambda s: counts[s]["samples"])
            reason = "sampling"
        else:
            # Laplace smoothing avoids treating a small sample as a certainty.
            side = max(SIDES, key=lambda s: (
                Fraction(counts[s]["wins"] + 1, counts[s]["samples"] + 2),
                -counts[s]["samples"]))
            reason = "history"
        if rows and rows[-1][2] == "loss":
            # Keep the actual chosen side through a losing chain, including reloads.
            side = rows[-1][1]
            reason = "locked"
        most_common = None if appearances["heads"] == appearances["tails"] else max(SIDES, key=appearances.get)
        return dict(side=side, reason=reason, sides=counts,
                    appearances=appearances, mostCommon=most_common,
                    total=len(rows), window=window, minimumSamples=MIN_SAMPLES)

    def snapshot(self, window=WINDOW):
        if type(window) is not int or window not in (100, WINDOW):
            raise ValueError("History window must be 100 or 500")
        choices = {str(size): self._selection(size) for size in (100, WINDOW)}
        return {**choices[str(window)], "choices": choices,
                "windows": {str(size): frequency(list(self.rows)[-size:], size) for size in (100, WINDOW)}}


def ensure_schema(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS coinflip_rounds (seq INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, message TEXT NOT NULL, side TEXT NOT NULL, outcome TEXT NOT NULL, UNIQUE(account,message))")


def load(account, path=DB_PATH):
    with closing(sqlite3.connect(path)) as conn, conn:
        ensure_schema(conn)
        rows = list(conn.execute("SELECT message,side,outcome FROM coinflip_rounds WHERE account=? ORDER BY seq DESC LIMIT ?", (str(account), WINDOW)))
        return History(reversed(rows))


def save(account, message_id, side, outcome, path=DB_PATH):
    if side not in SIDES or outcome not in ("win", "loss"):
        return
    with closing(sqlite3.connect(path)) as conn, conn:
        ensure_schema(conn)
        conn.execute("INSERT OR IGNORE INTO coinflip_rounds (account,message,side,outcome) VALUES (?,?,?,?)", (str(account), str(message_id), side, outcome))
        conn.execute("DELETE FROM coinflip_rounds WHERE account=? AND seq NOT IN (SELECT seq FROM coinflip_rounds WHERE account=? ORDER BY seq DESC LIMIT ?)", (str(account), str(account), WINDOW))


def get_history(bot):
    if not hasattr(bot, "coinflip_history"):
        bot.coinflip_history = History()
    return bot.coinflip_history


def select_side(bot, mode):
    if mode in ("probe", "probe_loss", "win_switch"):
        from utils.coinflip_probe import get_plan
        return get_plan(bot).side
    if mode != "auto":
        return mode
    from utils import bot_control
    window = bot_control.get_settings()["coinflipHistoryWindow"]
    return get_history(bot)._selection(window)["side"]
