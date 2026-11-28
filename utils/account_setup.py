"""Local account credentials, separate from public dashboard settings."""

import base64
import binascii
import os
import re
import tempfile
from pathlib import Path
from threading import Event, RLock

ROOT = Path(__file__).resolve().parents[1]
TOKENS_PATH = ROOT / "tokens.txt"
PENDING_PATH = ROOT / "config" / "account_pending.json"
changed = Event()
_lock = RLock()
_pending_accounts = set()


def read_accounts():
    with _lock:
        if not TOKENS_PATH.exists():
            return []
        rows = []
        for line in TOKENS_PATH.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError("tokens.txt có dòng sai định dạng. Cần TOKEN ID_KENH.")
            rows.append(parts)
        return rows


def validate(data):
    if not isinstance(data, dict) or set(data) != {"token", "channelId"}:
        raise ValueError("Cần token và ID kênh.")
    token, channel = data["token"], data["channelId"]
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{30,256}", token):
        raise ValueError("Token không hợp lệ: chỉ nhập token, không thêm dấu cách hay tiền tố.")
    if not isinstance(channel, str) or not re.fullmatch(r"[0-9]{17,20}", channel):
        raise ValueError("ID kênh phải gồm 17–20 chữ số.")
    return token, channel


def account_id_from_token(token):
    prefix, separator, _ = token.partition(".")
    if not separator or not 22 <= len(prefix) <= 28:
        return ""
    try:
        account_id = base64.b64decode(prefix + "=" * (-len(prefix) % 4), altchars=b"-_", validate=True).decode("ascii")
    except (ValueError, binascii.Error):
        return ""
    return account_id if re.fullmatch(r"[0-9]{17,20}", account_id) else ""


def _write_accounts(accounts, legacy_pending=False):
    descriptor, name = tempfile.mkstemp(prefix=".account-", suffix=".tmp", dir=TOKENS_PATH.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for token, channel in accounts:
                stream.write(f"{token} {channel}\n")
        if legacy_pending:
            PENDING_PATH.write_text("{}\n", encoding="utf-8")
        os.replace(name, TOKENS_PATH)
    finally:
        Path(name).unlink(missing_ok=True)


def _account_metadata(account_id, initial_channel, position, runtime):
    from utils import bot_control

    settings = bot_control.get_settings(account_id) if account_id else {}
    return {
        "accountId": account_id,
        "name": runtime.get("name") or f"Tài khoản {position + 1}",
        "channelId": settings.get("channelId") or initial_channel,
        "connected": bool(runtime.get("connected", runtime)),
        "restartRequired": account_id in _pending_accounts,
    }


def _runtimes_by_account():
    from utils import bot_control

    return {str(runtime["accountId"]): runtime for runtime in bot_control.get_runtimes() if runtime.get("accountId")}


def list_accounts():
    """List local accounts without exposing token values to dashboard polling."""
    with _lock:
        runtimes = _runtimes_by_account()
        return [
            _account_metadata(account_id, channel, position, runtimes.get(account_id, {}))
            for position, (token, channel) in enumerate(read_accounts())
            if (account_id := account_id_from_token(token))
        ]


def _find_account(accounts, account_id):
    for position, (token, _) in enumerate(accounts):
        if account_id and account_id == account_id_from_token(token):
            return position
    raise ValueError("Không tìm thấy tài khoản này trong cấu hình đã lưu.")


def read_account(account_id, *, reveal=False):
    """Read one configured account, including the secret only on explicit request."""
    with _lock:
        accounts = read_accounts()
        position = _find_account(accounts, account_id)
        token, channel = accounts[position]
        runtime = _runtimes_by_account().get(account_id, {})
        result = _account_metadata(account_id, channel, position, runtime)
        if reveal:
            result["token"] = token
        return result


def add(data):
    from utils import bot_control

    token, channel = validate(data)
    account_id = account_id_from_token(token)
    if not account_id:
        raise ValueError("Không đọc được ID tài khoản từ token Discord.")

    with _lock:
        accounts = read_accounts()
        identities = [account_id_from_token(previous_token) for previous_token, _ in accounts]
        if account_id in identities:
            raise ValueError("Tài khoản này đã được thêm. Hãy chọn tài khoản để đổi token.")

        shared_channel = bot_control.get_settings()["channelId"]
        if shared_channel and len(accounts) == 1 and identities[0] and not PENDING_PATH.exists():
            # Keep the currently effective destination when transitioning from a shared channel.
            current_account = identities[0]
            current_channel = bot_control.get_settings(current_account)["channelId"]
            if current_channel == shared_channel:
                bot_control.update_settings({"channelId": current_channel}, current_account)
            bot_control.update_settings({"channelId": ""})
        elif shared_channel:
            bot_control.update_settings({"channelId": channel}, account_id)

        needs_restart = bool(accounts or _runtimes_by_account())
        _write_accounts([*accounts, (token, channel)])
        if needs_restart:
            _pending_accounts.add(account_id)
        changed.set()
        return read_account(account_id)


def update_account(account_id, data):
    from utils import bot_control

    if not isinstance(data, dict) or set(data) not in ({"token"}, {"channelId"}):
        raise ValueError("Hãy chọn đổi token hoặc đổi ID kênh.")

    with _lock:
        accounts = read_accounts()
        position = _find_account(accounts, account_id)
        old_token, initial_channel = accounts[position]
        token, channel = validate({"token": old_token, "channelId": initial_channel} | data)
        channel_applied = False
        if "token" in data:
            if account_id_from_token(token) != account_id:
                raise ValueError("Token phải thuộc tài khoản đã chọn. Dùng Thêm tài khoản cho token khác.")
            if token != old_token:
                accounts[position] = (token, initial_channel)
                _write_accounts(accounts)
                _pending_accounts.add(account_id)
                changed.set()
        else:
            current_channel = bot_control.get_settings(account_id)["channelId"] or initial_channel
            if channel != current_channel:
                runtime = _runtimes_by_account().get(account_id)
                if runtime and account_id not in _pending_accounts:
                    bot_control.validate_channel(channel, account_id)
                    channel_applied = True
                bot_control.update_settings({"channelId": channel}, account_id)
                if not channel_applied:
                    _pending_accounts.add(account_id)
        return {**read_account(account_id), "channelApplied": channel_applied}


def save(data):
    token, channel = validate(data)
    with _lock:
        from utils import bot_control
        accounts = read_accounts()
        # A single-account form must not silently delete other configured accounts.
        if len(accounts) > 1:
            raise ValueError("File có nhiều tài khoản. Hãy sửa tokens.txt trực tiếp để giữ đủ tài khoản.")
        live_channel_change = bool(
            accounts and token == accounts[0][0]
            and not PENDING_PATH.exists()
            and any(runtime.get("accountId") for runtime in bot_control.get_runtimes())
        )
        if live_channel_change:
            # Reject inaccessible channels before replacing the saved account file.
            bot_control.validate_channel(channel)
        _write_accounts([(token, channel)], legacy_pending=True)
        applied = False
        if live_channel_change:
            try:
                bot_control.update_settings({"channelId": channel})
                PENDING_PATH.unlink()
                applied = True
            except OSError:
                # Credentials are saved. Keep the marker so restart adopts their channel.
                pass
        changed.set()
        return applied


def for_startup():
    """Adopt the newly entered channel only when connecting the new credentials."""
    with _lock:
        accounts = read_accounts()
        if accounts and PENDING_PATH.exists():
            from utils import bot_control
            bot_control.update_settings({"channelId": ""})
            PENDING_PATH.unlink()
        _pending_accounts.clear()
        return accounts
