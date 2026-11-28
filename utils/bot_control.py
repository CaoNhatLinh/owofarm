"""Dashboard configuration and controls shared by Flask and Discord threads."""

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
GEM_RARITIES = ("common", "uncommon", "rare", "epic", "mythical", "legendary", "fabled")
DEFAULTS = dict(restEnabled=True, failureThreshold=3, restMinutes=10,
                responseTimeout=20, messageInterval=4.0, owoEnabled=True, huntEnabled=True, battleEnabled=True,
                randomChatEnabled=False,
                channelId="", prefix="o", gemOrder="low_to_high", gemsEnabled=True, gemSkipAtOrAbove="none",
                teamSetupEnabled=False, huntbotEnabled=False, huntbotMax=True, huntbotUpgradeEnabled=False,
                startupFriendlyBattles=False, cookieRecipientId="", prayEnabled=False, prayRecipientId="",
                huntEmergencySellEnabled=False, zooSacrificeSurplusEnabled=False,
                coinflipEnabled=False, slotsEnabled=False, blackjackEnabled=False,
                coinflipBet=200, slotsBet=200, blackjackBet=200, coinflipSide="heads", coinflipHistoryWindow=500, coinflipProbeTarget="heads", coinflipSwitchStart="heads",
                coinflipDoubleOnLoss=True, coinflipBonusOnLoss=False, slotsDoubleOnLoss=True, blackjackDoubleOnLoss=True,
                gambleGoalEnabled=True, gambleGoalAmount=30000,
                gambleLossEnabled=True, gambleLossAmount=10000)
_settings = dict(DEFAULTS)
_account_settings = {}
_runtimes = {}
_channel_checkers = {}
_resume_generation = 0
_account_resume_generations = {}
_paused_accounts = set()


def validate_settings(values):
    if not isinstance(values, dict) or not values or set(values) - DEFAULTS.keys():
        raise ValueError("Cấu hình không hợp lệ.")
    result = {}
    for key, value in values.items():
        if key in ("restEnabled", "owoEnabled", "huntEnabled", "battleEnabled", "randomChatEnabled", "gemsEnabled", "coinflipEnabled", "slotsEnabled", "blackjackEnabled",
                   "coinflipDoubleOnLoss", "coinflipBonusOnLoss", "slotsDoubleOnLoss", "blackjackDoubleOnLoss",
                   "gambleGoalEnabled", "gambleLossEnabled", "teamSetupEnabled", "huntbotEnabled", "huntbotMax",
                   "huntbotUpgradeEnabled", "huntEmergencySellEnabled", "zooSacrificeSurplusEnabled",
                   "startupFriendlyBattles", "prayEnabled"):
            if type(value) is not bool:
                raise ValueError("Công tắc chỉ nhận trạng thái bật hoặc tắt.")
        elif key in ("gambleGoalAmount", "gambleLossAmount"):
            if type(value) is not int or not 1 <= value <= 1000000000000:
                raise ValueError("Giới hạn phải là số nguyên từ 1 đến 1.000.000.000.000 cowoncy.")
        elif key in ("coinflipBet", "slotsBet", "blackjackBet"):
            if type(value) is not int or not 1 <= value <= 250000:
                raise ValueError("Tiền cược phải là số nguyên từ 1 đến 250.000 cowoncy.")
        elif key == "coinflipHistoryWindow":
            if type(value) is not int or value not in (100, 500):
                raise ValueError("Mẫu lịch sử Tung xu phải là 100 hoặc 500 ván.")
        elif key in ("coinflipProbeTarget", "coinflipSwitchStart"):
            if not isinstance(value, str) or value not in ("heads", "tails"):
                raise ValueError("Mặt cược chính phải là Ngửa hoặc Sấp.")
        elif key == "coinflipSide":
            if not isinstance(value, str) or value not in ("heads", "tails", "auto", "probe", "probe_loss", "win_switch"):
                raise ValueError("Chế độ Tung xu không hợp lệ.")
        elif key == "channelId":
            if not isinstance(value, str) or (value and (not value.isascii() or not value.isdigit() or not 17 <= len(value) <= 20)):
                raise ValueError("ID kênh phải gồm 17–20 chữ số.")
        elif key in ("cookieRecipientId", "prayRecipientId"):
            if value != "":
                validate_account_id(value)
        elif key == "prefix":
            if not isinstance(value, str) or not 1 <= len(value) <= 25 or not value.strip() or any(ord(c) < 32 or ord(c) > 126 for c in value) or "<@" in value:
                raise ValueError("Tiền tố lệnh phải có 1–25 ký tự ASCII, không xuống dòng hay nhắc tên tài khoản. Dấu cách được giữ nguyên.")
        elif key == "gemOrder":
            if not isinstance(value, str) or value not in ("high_to_low", "low_to_high"):
                raise ValueError("Thứ tự dùng đá quý phải từ cấp cao đến cấp thấp hoặc từ cấp thấp đến cấp cao.")
        elif key == "gemSkipAtOrAbove":
            if not isinstance(value, str) or value not in ("none", *GEM_RARITIES):
                raise ValueError("Cấp đá quý cần giữ lại không hợp lệ.")
        else:
            ranges = dict(failureThreshold=(1, 10, "Số lần OwO không phản hồi"),
                          restMinutes=(1, 120, "Thời gian tạm nghỉ"),
                          responseTimeout=(10, 90, "Thời gian chờ phản hồi"),
                          messageInterval=(3, 60, "Khoảng cách giữa hai lệnh"))
            low, high, label = ranges[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{label} phải nằm trong khoảng {low}–{high}.")
            if key != "messageInterval" and int(value) != value:
                raise ValueError(f"{label} phải là số nguyên.")
        result[key] = value
    return result


def validate_account_id(account_id):
    if not isinstance(account_id, str) or not account_id.isascii() or not account_id.isdigit() or not 17 <= len(account_id) <= 20:
        raise ValueError("ID tài khoản Discord không hợp lệ.")
    return account_id


def _load_legacy_automation():
    try:
        legacy = json.loads(SETTINGS_PATH.with_name("settings.json").read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        return
    try:
        if legacy["animal"]["emergencySell"]["enabled"] is True:
            _settings["huntEmergencySellEnabled"] = True
    except (KeyError, TypeError):
        pass
    try:
        huntbot = legacy["commands"]["autoHuntBot"]
        if huntbot["enabled"] is True:
            _settings.update(huntbotEnabled=True, huntbotMax=False,
                             huntbotUpgradeEnabled=huntbot.get("upgrader", {}).get("enabled") is True)
    except (AttributeError, KeyError, TypeError):
        pass


def _load_settings():
    _load_legacy_automation()
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return
    if not isinstance(saved, dict):
        return
    accounts = saved.pop("accounts", {})
    if saved:
        try:
            _settings.update(validate_settings(saved))
        except ValueError:
            pass
    if not isinstance(accounts, dict):
        return
    for account_id, overrides in accounts.items():
        try:
            _account_settings[validate_account_id(account_id)] = validate_settings(overrides)
        except ValueError:
            continue


_load_settings()


def get_settings(account_id=None):
    with _lock:
        return {**_settings, **_account_settings.get(str(account_id), {})}


def get_account_overrides(account_id):
    with _lock:
        return dict(_account_settings.get(str(account_id), {}))


def settings_for(bot):
    account_id = getattr(bot, "_dashboard_account_id", None)
    return get_settings(account_id) if account_id is not None else get_settings()


def manages_prayer(bot):
    account_id = getattr(bot, "_dashboard_account_id", None)
    with _lock:
        return _settings["prayEnabled"] or "prayEnabled" in _account_settings.get(str(account_id), {})


def register_channel_checker(key, loop, checker):
    with _lock:
        _channel_checkers[str(key)] = (loop, checker)


def has_channel_checker(account_id):
    with _lock:
        checker = _channel_checkers.get(str(account_id))
        return checker is not None and checker[0].is_running()


def validate_channel(channel_id, account_id=None):
    with _lock:
        checkers = [(loop, checker) for key, (loop, checker) in _channel_checkers.items()
                    if (account_id is None or key == str(account_id)) and loop.is_running()]
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


def _write_settings(settings, accounts):
    document = dict(settings)
    if accounts:
        document["accounts"] = accounts
    temp = SETTINGS_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(document, indent=4) + "\n", encoding="utf-8")
    os.replace(temp, SETTINGS_PATH)


def update_settings(values, account_id=None):
    validated = validate_settings(values)
    with _lock:
        if account_id is None:
            updated = {**_settings, **validated}
            _write_settings(updated, _account_settings)
            _settings.update(updated)
        else:
            account_id = validate_account_id(account_id)
            overrides = {**_account_settings.get(account_id, {}), **validated}
            _write_settings(_settings, {**_account_settings, account_id: overrides})
            _account_settings[account_id] = overrides
        return get_settings(account_id)


def clear_account_settings(account_id, *, keep_channel=False):
    account_id = validate_account_id(account_id)
    with _lock:
        if account_id in _account_settings:
            updated = dict(_account_settings)
            overrides = updated.pop(account_id)
            if keep_channel and "channelId" in overrides:
                updated[account_id] = {"channelId": overrides["channelId"]}
            _write_settings(_settings, updated)
            _account_settings.clear()
            _account_settings.update(updated)
        return get_settings(account_id)


def publish_runtime(key, value):
    with _lock:
        _runtimes[str(key)] = dict(value)


def get_runtimes():
    with _lock:
        return [dict(value, running=is_running(value.get("accountId")),
                     resumeRequest=get_resume_generation(value.get("accountId")),
                     paused=value.get("accountId") in _paused_accounts)
                for value in _runtimes.values()]


def is_running(account_id=None):
    with _lock:
        return _running.is_set() and str(account_id) not in _paused_accounts


def running_for(bot):
    account_id = getattr(bot, "_dashboard_account_id", None)
    return is_running(account_id) if account_id is not None else is_running()


def set_running(value, account_id=None):
    global _resume_generation
    with _lock:
        if account_id is not None:
            account_id = validate_account_id(account_id)
            if value:
                _paused_accounts.discard(account_id)
                _account_resume_generations[account_id] = _account_resume_generations.get(account_id, 0) + 1
            else:
                _paused_accounts.add(account_id)
        elif value:
            _resume_generation += 1
            _running.set()
        else:
            _running.clear()


def get_resume_generation(account_id=None):
    with _lock:
        return _resume_generation + _account_resume_generations.get(str(account_id), 0)


async def wait_until_running(account_id=None):
    while not is_running(account_id):
        await asyncio.sleep(0.25)
