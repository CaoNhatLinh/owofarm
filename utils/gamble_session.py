"""Account-scoped session resets and persistent losing-streak records."""
import asyncio
import re
import sqlite3
from collections import OrderedDict
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import closing
from pathlib import Path
from threading import RLock

GAMES = ("coinflip", "slots", "blackjack")
DB_PATH = Path(__file__).resolve().parent / "data" / "gamble_streaks.sqlite"
_lock = RLock()
_handlers = {}
_requests = OrderedDict()


class Streaks:
    def __init__(self, best=None, current=None):
        self.current = {game: int((current or {}).get(game, 0)) for game in GAMES}
        self.best = {game: int((best or {}).get(game, 0)) for game in GAMES}

    def record(self, game, outcome):
        previous = self.best[game]
        if outcome == "loss":
            self.current[game] += 1
            self.best[game] = max(previous, self.current[game])
        elif outcome == "win":
            self.current[game] = 0
        return self.best[game] > previous

    def reset_current(self):
        self.current = dict.fromkeys(GAMES, 0)

    def snapshot(self):
        return {game: {"current": self.current[game], "best": self.best[game]} for game in GAMES}


def ensure_schema(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS streaks (account TEXT, game TEXT, best INTEGER, current INTEGER DEFAULT 0, PRIMARY KEY(account,game))")
    if "current" not in {row[1] for row in conn.execute("PRAGMA table_info(streaks)")}:
        conn.execute("ALTER TABLE streaks ADD COLUMN current INTEGER DEFAULT 0")


def read_best(account, path=DB_PATH):
    with closing(sqlite3.connect(path)) as conn, conn:
        ensure_schema(conn)
        return dict(conn.execute("SELECT game,best FROM streaks WHERE account=?", (str(account),)))


def save_best(account, game, best, path=DB_PATH):
    read_best(account, path)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("INSERT INTO streaks (account,game,best) VALUES (?,?,?) ON CONFLICT(account,game) DO UPDATE SET best=MAX(best,excluded.best)",
                     (str(account), game, best))


def read_state(account, path=DB_PATH):
    with closing(sqlite3.connect(path)) as conn, conn:
        ensure_schema(conn)
        return {game:{"current":current or 0,"best":best}
                for game,best,current in conn.execute("SELECT game,best,current FROM streaks WHERE account=?",(str(account),))}


def save_state(account, state, path=DB_PATH):
    with closing(sqlite3.connect(path)) as conn, conn:
        ensure_schema(conn)
        for game, values in state.items():
            conn.execute("INSERT INTO streaks (account,game,best,current) VALUES (?,?,?,?) ON CONFLICT(account,game) DO UPDATE SET current=excluded.current,best=MAX(best,excluded.best)",
                         (str(account),game,values["best"],values["current"]))


async def reset_session(bot):
    from utils.gambling_control import COG_NAMES
    if not hasattr(bot, "_gamble_state_lock"):
        bot._gamble_state_lock = asyncio.Lock()
    async with bot._gamble_state_lock:
        bot.stats.gain_or_lose = 0
        bot._gamble_loss_latch = None
        bot.gamble_streaks.reset_current()
        if getattr(bot, "_persist_gamble_streaks", False):
            await asyncio.to_thread(save_state, bot.user.id, bot.gamble_streaks.snapshot())
        for game, name in COG_NAMES.items():
            cog = bot.get_cog(name)
            if not cog:
                continue
            was_exceeded = cog.exceeded_max_amount
            cog.turns_lost = 0
            cog.exceeded_max_amount = False
            for key in cog.gamble_flags:
                cog.gamble_flags[key] = False
            if was_exceeded and cog.gambling_enabled():
                starter = getattr(cog, {"coinflip":"start_cf", "slots":"start_slots", "blackjack":"send_blackjack"}[game])
                cog.start_gambling(starter(startup=True))
        # Do not clear cooldowns, completed round IDs, account balance or farm state.
        bot.response_guard.gamble_profit = 0
        bot.response_guard.gamble_loss_stopped = False
        bot.response_guard.gamble_streaks = bot.gamble_streaks.snapshot()
        bot.response_guard.tick()
        return {"profit": 0, "streaks": bot.gamble_streaks.snapshot()}


def register(account, loop, handler):
    with _lock:
        _handlers[str(account)] = (loop, handler)


def submit_reset(data):
    if not isinstance(data, dict) or set(data) != {"accountId", "requestId"}:
        raise ValueError("Yêu cầu reset không hợp lệ.")
    account, request_id = data["accountId"], data["requestId"]
    if not isinstance(account, str) or not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", request_id):
        raise ValueError("Tài khoản hoặc mã yêu cầu không hợp lệ.")
    with _lock:
        if request_id in _requests:
            previous_account, future = _requests[request_id]
            if previous_account != account:
                raise ValueError("Mã yêu cầu đã dùng cho tài khoản khác.")
        else:
            if account not in _handlers:
                raise ValueError("Tài khoản chưa kết nối. Chờ kết nối rồi thử lại.")
            loop, handler = _handlers[account]
            future = asyncio.run_coroutine_threadsafe(handler(), loop)
            _requests[request_id] = (account, future)
            while len(_requests) > 100:
                key = next(iter(_requests))
                if not _requests[key][1].done():
                    break
                _requests.pop(key)
    try:
        return future.result(timeout=8)
    except FutureTimeout:
        raise TimeoutError("Chưa nhận được kết quả reset. Bấm kiểm tra lại để tránh reset trùng.") from None
