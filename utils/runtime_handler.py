import json
import os
import tempfile
import threading
import time
from datetime import datetime, time as datetime_time, timedelta

from utils.colors import COLORS
from utils.errors import suppress_and_log

DEFAULT_PATH = "utils/data/weekly_runtime.json"
UPDATE_INTERVAL = 15
_session_started = None


def weekly_totals(now):
    monday = now.date() - timedelta(days=now.weekday())
    return {"week": monday.isoformat(), "seconds": [0] * 7}


def _write_weekly_runtime(weekly_runtime_dict, path):
    try:
        target_dir = os.path.dirname(path)

        # This temporary file is uniquely named, preventing race conditions making the file be unavailable.
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target_dir, delete=False
        )
        tmp_path = tmp_file.name

        try:
            # Write dummy to temporary file
            json.dump(weekly_runtime_dict, tmp_file, indent=4)
            # Windows requires the file to be closed before replace
            tmp_file.close()

            os.replace(tmp_path, path)
        finally:
            # Deletion of temporary file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except OSError:
        # Incase windows locks the file (another process using it), we can silently ignore it.
        pass
    except Exception as e:
        print(f"{COLORS.BOLD_YELLOW}Weekly runtime error: {e} {COLORS.RESET}")


def load_weekly_runtime(path=DEFAULT_PATH, *, now=None):
    now = now or datetime.now()
    current = weekly_totals(now)
    try:
        with open(path, "r", encoding="utf-8") as config_file:
            stored = json.load(config_file)
    except (ValueError, OSError):
        return current
    if not isinstance(stored, dict):
        return current
    if "week" in stored:
        seconds = stored.get("seconds")
        if stored["week"] == current["week"] and isinstance(seconds, list) and len(seconds) == 7:
            current["seconds"] = [value if type(value) in (int, float) and 0 <= value <= 86400
                                  else 0 for value in seconds]
        return current

    # Older data has one first/last interval per weekday. Retain only its overlap with this week.
    day = datetime.combine(now.date() - timedelta(days=now.weekday()), datetime_time.min)
    for weekday in range(7):
        interval = stored.get(str(weekday))
        next_day = day + timedelta(days=1)
        if isinstance(interval, list) and len(interval) == 2 and all(
            type(value) in (int, float) and 0 <= value <= now.timestamp() + 86400 for value in interval
        ):
            start, end = interval
            current["seconds"][weekday] = max(0, min(end, next_day.timestamp(), now.timestamp())
                                                - max(start, day.timestamp()))
        day = next_day
    return current


def accumulate_runtime(data, now, elapsed):
    current = weekly_totals(now)
    if data["week"] != current["week"]:
        data = current
    weekday = now.weekday()
    today = min(elapsed, (now - datetime.combine(now.date(), datetime_time.min)).total_seconds())
    data["seconds"][weekday] += today
    if weekday:
        data["seconds"][weekday - 1] += elapsed - today
    return data


def session_uptime_seconds():
    return 0 if _session_started is None else max(0, int(time.monotonic() - _session_started))


@suppress_and_log("Weekly Runtime Updater")
def handle_weekly_runtime(path=DEFAULT_PATH):
    data = load_weekly_runtime(path)
    previous = time.monotonic()
    while True:
        time.sleep(UPDATE_INTERVAL)
        current = time.monotonic()
        elapsed = min(UPDATE_INTERVAL, current - previous)
        data = accumulate_runtime(data, datetime.now(), elapsed)
        _write_weekly_runtime(data, path)
        previous = current


@suppress_and_log("Weekly Runtime Update Starter")
def start_runtime_loop(path=DEFAULT_PATH):
    global _session_started
    _session_started = time.monotonic()
    loop_thread = threading.Thread(target=handle_weekly_runtime, args=(path,), daemon=True)
    loop_thread.start()
