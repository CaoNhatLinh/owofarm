"""Validated, account-scoped manual sales requested by the dashboard."""

import asyncio
import re
import time
from collections import OrderedDict
from threading import RLock

from utils import bot_control

WEAPON_RANKS = [(r, r.title()) for r in
    ("common", "uncommon", "rare", "epic", "mythical", "legendary", "fabled")]
WEAPON_CODES = dict(zip((r for r,_ in WEAPON_RANKS),("cw","uw","rw","ew","mw","lw","fw")))
ANIMAL_RANKS = [("common","Common"), ("uncommon","Uncommon"), ("rare","Rare"),
    ("epic","Epic"), ("patreon","Patreon"), ("special","Special"),
    ("mythical","Mythical"), ("gem","Gem"), ("legendary","Legendary"),
    ("bot","Bot"), ("distorted","Distorted"), ("cpatreon","Custom Patreon"),
    ("fabled","Fabled"), ("hidden","Hidden")]
ANIMAL_CODES = dict(zip((r for r,_ in ANIMAL_RANKS),
    ("c","u","r","e","p","s","m","g","l","b","d","cp","f","h")))
TERMINAL = {"success", "partial", "failed", "cancelled"}
_lock = RLock()
_handlers = {}
_jobs = OrderedDict()


class SaleConflict(ValueError):
    pass


def ranks_through(kind, maximum):
    ranks = WEAPON_RANKS if kind == "weapons" else ANIMAL_RANKS if kind in ("animals","sacrifice") else None
    names = [name for name,_ in ranks or []]
    if maximum not in names:
        raise ValueError("Loại bán hoặc độ hiếm không hợp lệ.")
    return names[:names.index(maximum) + 1]


def register(account_id, label, loop, handler):
    with _lock:
        _handlers[str(account_id)] = (label, loop, handler)


def accounts():
    with _lock:
        return [dict(id=key, name=value[0]) for key,value in _handlers.items()]


def jobs():
    with _lock:
        history = list(_jobs.values())
        return [dict(job) for job in history[:-50] if job["state"] not in TERMINAL] + [
            dict(job) for job in history[-50:]
        ]


def update(job_id, **values):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(values, updatedAt=time.time())


def submit(data):
    if not isinstance(data, dict) or set(data) != {"kind", "maxRarity", "accountId", "requestId"}:
        raise ValueError("Yêu cầu bán không hợp lệ.")
    kind, maximum = data["kind"], data["maxRarity"]
    if not isinstance(kind,str) or not isinstance(maximum,str):
        raise ValueError("Loại bán hoặc độ hiếm không hợp lệ.")
    ranks_through(kind, maximum)
    request_id = data["requestId"]
    if not isinstance(request_id,str) or not re.fullmatch(r"[A-Za-z0-9-]{8,64}",request_id):
        raise ValueError("Mã yêu cầu bán không hợp lệ.")
    account_id = data["accountId"]
    if not isinstance(account_id,str):
        raise ValueError("Tài khoản không hợp lệ.")
    with _lock:
        if request_id in _jobs:
            previous = _jobs[request_id]
            if any(previous[key] != data[key] for key in ("kind","maxRarity","accountId")):
                raise ValueError("Mã yêu cầu đã dùng cho một thao tác khác.")
            return dict(previous)
        if account_id not in _handlers:
            raise SaleConflict("Tài khoản chưa kết nối. Chờ bot kết nối rồi thử lại.")
        if any(j["accountId"] == account_id and j["state"] not in TERMINAL for j in _jobs.values()):
            raise SaleConflict("Tài khoản đang có một lượt bán. Chờ kết quả trước khi bán tiếp.")
        label, loop, handler = _handlers[account_id]
        job = dict(id=request_id, accountId=account_id, accountName=label, kind=kind,
            maxRarity=maximum, state="queued", sold=0, message="Đã nhận yêu cầu; đang chờ bot xử lý.", updatedAt=time.time())
        _jobs[request_id] = job
    coroutine = handler(dict(job))
    try:
        asyncio.run_coroutine_threadsafe(coroutine, loop)
    except RuntimeError:
        coroutine.close()
        update(request_id, state="failed", message="Kết nối bot đã đóng; chưa gửi lệnh bán.")
        raise SaleConflict("Kết nối bot đã đóng; chưa gửi lệnh bán.") from None
    return dict(job)
