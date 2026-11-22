"""Execute user-requested sales independently of the farm queue."""

import asyncio
import re
import time
from contextlib import asynccontextmanager

from utils import bot_control, quick_sale_jobs as sales


class SaleStopped(Exception):
    pass


def check_context(bot, context):
    status = bot.ch.command_handler_status
    if status.captcha or status.sleep or bot.response_guard.cooling_down:
        raise SaleStopped("Bot đang nghỉ hoặc chờ CAPTCHA. Không tiếp tục thao tác.")
    if (bot.cm.id, bot.settings_dict.prefix) != context:
        raise SaleStopped("Kênh hoặc prefix đã đổi. Lượt bán đã dừng.")


async def wait_ready(bot, context):
    check_context(bot, context)
    try:
        await asyncio.wait_for(bot.response_guard.wait_ready(manual=True), bot_control.get_settings()["responseTimeout"] + 5)
    except asyncio.TimeoutError:
        raise SaleStopped("Chưa nhận được phản hồi lệnh trước. Không tự gửi lại lệnh bán.") from None
    check_context(bot, context)


@asynccontextmanager
async def reader_for(bot):
    reader = bot.get_cog("Weapons")
    temporary = reader is None
    if temporary:
        from core.cogs.weapons import Weapons
        reader = Weapons(bot)
        bot.add_listener(reader.on_message, "on_message")
        bot.add_listener(reader.on_message_edit, "on_message_edit")
    try:
        async with reader._cycle_lock:
            previous = getattr(reader, "_manual_requests", False)
            reader._manual_requests = True
            try:
                yield reader
            finally:
                reader._manual_requests = previous
    finally:
        if temporary:
            bot.remove_listener(reader.on_message, "on_message")
            bot.remove_listener(reader.on_message_edit, "on_message_edit")
            await reader.cog_unload()


async def sell_weapons(bot, reader, job, context):
    sold = 0
    for rarity in sales.ranks_through("weapons", job["maxRarity"]):
        await wait_ready(bot, context)
        response = await reader._request_response("weapon_rank_sell", "sell", sales.WEAPON_CODES[rarity])
        if response is None:
            raise SaleStopped("Chưa xác nhận kết quả bán. Không tự gửi lại; hãy kiểm tra kho/nhật ký.")
        text = response[1]
        lower = text.casefold()
        if "do not have any weapons with this rank" in lower:
            continue
        if "you sold all your" not in lower or "weapons" not in lower:
            raise SaleStopped("OwO chưa xác nhận bán vũ khí thành công. Không tự gửi lại.")
        # The rank command excludes equipped, favorite and unsellable weapons in OwO.
        listing = re.search(r"Sold:\*{0,2}\s*([^\n]+)", text, re.I)
        count = len(re.findall(r"<a?:[A-Za-z0-9_]+:\d+>",listing[1])) if listing else 0
        if not count:
            raise SaleStopped("OwO báo đã bán nhưng chưa đọc được số lượng. Hãy kiểm tra nhật ký; không tự gửi lại.")
        sold += count
        sales.update(job["id"], sold=sold, message=f"Đã bán {sold} vũ khí; vừa xử lý cấp {rarity}.")
        await bot.log(f"Bán nhanh: đã bán {count} vũ khí cấp {rarity}.", "#bcf36b")
    return sold


async def sell_animals(bot, reader, job, context):
    sacrificing = job["kind"] == "sacrifice"
    arguments = " ".join(sales.ANIMAL_CODES[r] for r in sales.ranks_through(job["kind"],job["maxRarity"]))
    await wait_ready(bot, context)
    response = await reader._request_response("animal_sacrifice" if sacrificing else "animal_sell", "sac" if sacrificing else "sell", arguments)
    if response is None:
        raise SaleStopped("Chưa nhận được kết quả xử lý thú. Không tự gửi lại; hãy kiểm tra zoo/nhật ký.")
    text = response[1].casefold()
    if "don't have enough animals" in text:
        return 0
    if (" sacrificed " if sacrificing else " sold ") not in text or "for a total" not in text:
        raise SaleStopped("OwO chưa xác nhận thao tác thành công. Hãy xem nhật ký.")
    seller = bot.get_cog("Sell")
    if seller:
        setattr(seller, "sac_lastran" if sacrificing else "sell_lastran", time.monotonic())
    counts = re.findall(r"(?<!\w)x([\d,]+)",text)
    return sum(int(count.replace(",","")) for count in counts) if counts else None


@asynccontextmanager
async def animal_sale_lock(bot, kind):
    seller = bot.get_cog("Sell") if kind in ("animals","sacrifice") else None
    if seller:
        async with seller._sale_lock:
            yield
    else:
        yield


async def run_sale(bot, job):
    sales.update(job["id"], state="running", message="Đang kiểm tra và thực hiện bán…")
    try:
        await asyncio.wait_for(bot.wait_until_ready(), 15)
        context = (bot.cm.id, bot.settings_dict.prefix)
        check_context(bot, context)
        async with animal_sale_lock(bot, job["kind"]):
            async with reader_for(bot) as reader:
                if job["kind"] == "weapons":
                    sold = await sell_weapons(bot,reader,job,context)
                else:
                    sold = await sell_animals(bot,reader,job,context)
        noun = "vũ khí" if job["kind"] == "weapons" else "thú"
        action = "hiến tế" if job["kind"] == "sacrifice" else "bán"
        message = f"Đã {action} {sold} {noun}." if sold is not None else f"OwO đã xác nhận {action} thành công."
        sales.update(job["id"], state="success", sold=sold, message=message)
        await bot.log(f"Bán nhanh: {message}", "#bcf36b")
    except asyncio.CancelledError:
        sales.update(job["id"], state="cancelled", message="Lượt bán đã dừng. Kiểm tra kho trước khi bán lại.")
        raise
    except Exception as exc:
        current = next((j for j in sales.jobs() if j["id"] == job["id"]), job)
        message = str(exc) if isinstance(exc,SaleStopped) else f"Lượt bán dừng do lỗi {type(exc).__name__}. Không tự gửi lại."
        sales.update(job["id"], state="partial" if current.get("sold") else "failed", message=message)
        await bot.log(f"Bán nhanh: {message}", "#e5bb78")
