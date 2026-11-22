"""Local account credentials, separate from public dashboard settings."""

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


def read_accounts():
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


def save(data):
    token, channel = validate(data)
    with _lock:
        # A single-account form must not silently delete other configured accounts.
        if len(read_accounts()) > 1:
            raise ValueError("File có nhiều tài khoản. Hãy sửa tokens.txt trực tiếp để giữ đủ tài khoản.")
        descriptor, name = tempfile.mkstemp(prefix=".account-", suffix=".tmp", dir=ROOT)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(f"{token} {channel}\n")
            PENDING_PATH.write_text("{}\n", encoding="utf-8")
            os.replace(name, TOKENS_PATH)
        finally:
            Path(name).unlink(missing_ok=True)
        changed.set()


def for_startup():
    """Adopt the newly entered channel only when connecting the new credentials."""
    with _lock:
        accounts = read_accounts()
        if accounts and PENDING_PATH.exists():
            from utils import bot_control
            bot_control.update_settings({"channelId": ""})
            PENDING_PATH.unlink()
        return accounts
