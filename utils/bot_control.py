"""Process-wide automation switch shared by Flask and Discord threads."""

import asyncio
import json
import math
import os
from pathlib import Path
from threading import Event, RLock
from concurrent.futures import TimeoutError as FutureTimeout

_running = Event()
_running.set()
_lock = RLock()
SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "dashboard.json"
DEFAULTS = dict(restEnabled=True, failureThreshold=3, restMinutes=10,
                responseTimeout=20, messageInterval=4.0, owoEnabled=True, huntEnabled=True, battleEnabled=True,
                channelId="", prefix="o", gemOrder="low_to_high", gemsEnabled=True,
                coinflipEnabled=False, slotsEnabled=False, blackjackEnabled=False,
                coinflipBet=200, slotsBet=200, blackjackBet=200, coinflipSide="heads", coinflipHistoryWindow=500, coinflipProbeTarget="heads", coinflipSwitchStart="heads",
                coinflipDoubleOnLoss=True, slotsDoubleOnLoss=True, blackjackDoubleOnLoss=True,
                gambleGoalEnabled=True, gambleGoalAmount=30000,
                gambleLossEnabled=True, gambleLossAmount=10000)
_settings = dict(DEFAULTS)
_runtimes = {}
_channel_checkers = {}
_resume_generation = 0


def validate_settings(values):
    if not isinstance(values, dict) or not values or set(values) - DEFAULTS.keys():
        raise ValueError("Cấu hình không hợp lệ.")
    result = {}
    for key, value in values.items():
        if key in ("restEnabled", "owoEnabled", "huntEnabled", "battleEnabled", "gemsEnabled", "coinflipEnabled", "slotsEnabled", "blackjackEnabled",
                   "coinflipDoubleOnLoss", "slotsDoubleOnLoss", "blackjackDoubleOnLoss", "gambleGoalEnabled", "gambleLossEnabled"):
            if type(value) is not bool:
                raise ValueError("Công tắc phải là true hoặc false.")
        elif key in ("gambleGoalAmount", "gambleLossAmount"):
            if type(value) is not int or not 1 <= value <= 1000000000000:
                raise ValueError("Giới hạn phải là số nguyên từ 1 đến 1.000.000.000.000 cowoncy.")
        elif key in ("coinflipBet", "slotsBet", "blackjackBet"):
            if type(value) is not int or not 1 <= value <= 250000:
                raise ValueError("Tiền cược phải là số nguyên từ 1 đến 250.000 cowoncy.")
        elif key == "coinflipHistoryWindow":
            if type(value) is not int or value not in (100, 500):
                raise ValueError("Mẫu lịch sử Coinflip phải là 100 hoặc 500 ván.")
        elif key in ("coinflipProbeTarget", "coinflipSwitchStart"):
            if not isinstance(value, str) or value not in ("heads", "tails"):
                raise ValueError("Mặt cược chính phải là heads hoặc tails.")
        elif key == "coinflipSide":
            if not isinstance(value, str) or value not in ("heads", "tails", "auto", "probe", "probe_loss", "win_switch"):
                raise ValueError("Chế độ Coinflip không hợp lệ.")
        elif key == "channelId":
            if not isinstance(value, str) or (value and (not value.isascii() or not value.isdigit() or not 17 <= len(value) <= 20)):
                raise ValueError("ID kênh phải gồm 17–20 chữ số.")
        elif key == "prefix":
            if not isinstance(value, str) or not 1 <= len(value) <= 25 or not value.strip() or any(ord(c) < 32 or ord(c) > 126 for c in value) or "<@" in value:
                raise ValueError("Prefix phải có 1–25 ký tự ASCII, không chứa xuống dòng hay mention. Dấu cách được giữ nguyên.")
        elif key == "gemOrder":
            if not isinstance(value, str) or value not in ("high_to_low", "low_to_high"):
                raise ValueError("Thứ tự gem phải là high_to_low hoặc low_to_high.")
        else:
            ranges = dict(failureThreshold=(1, 10), restMinutes=(1, 120),
                          responseTimeout=(10, 90), messageInterval=(3, 60))
            low, high = ranges[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{key} phải nằm trong khoảng {low}–{high}.")
            if key != "messageInterval" and int(value) != value:
                raise ValueError(f"{key} phải là số nguyên.")
        result[key] = value
    return result


try:
    if SETTINGS_PATH.exists():
        _settings.update(validate_settings(json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))))
except (ValueError, OSError):
    pass  # Invalid saved settings never prevent starting the local dashboard.


def get_settings():
    with _lock:
        return dict(_settings)


def register_channel_checker(key, loop, checker):
    with _lock:
        _channel_checkers[str(key)] = (loop, checker)


def validate_channel(channel_id):
    with _lock:
        checkers = list(_channel_checkers.values())
    if not checkers:
        raise ValueError("Tài khoản chưa kết nối. Chờ bot kết nối rồi lưu ID kênh.")
    futures = [asyncio.run_coroutine_threadsafe(checker(channel_id), loop) for loop, checker in checkers]
    try:
        for future in futures:
            future.result(timeout=8)
    except FutureTimeout:
        raise ValueError("Kiểm tra kênh quá thời gian. Chưa đổi kênh; hãy thử lại.") from None
    finally:
        for future in futures:
            if not future.done():
                future.cancel()


def update_settings(values):
    validated = validate_settings(values)
    with _lock:
        updated = {**_settings, **validated}
        temp = SETTINGS_PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(updated, indent=4) + "\n", encoding="utf-8")
        os.replace(temp, SETTINGS_PATH)
        _settings.update(updated)
        return dict(_settings)


def publish_runtime(key, value):
    with _lock:
        _runtimes[str(key)] = dict(value)


def get_runtimes():
    with _lock:
        return [dict(value) for value in _runtimes.values()]


def is_running():
    return _running.is_set()


def set_running(value):
    global _resume_generation
    with _lock:
        if value:
            _resume_generation += 1
            _running.set()
        else:
            _running.clear()


def get_resume_generation():
    with _lock:
        return _resume_generation


async def wait_until_running():
    while not is_running():
        await asyncio.sleep(0.25)
