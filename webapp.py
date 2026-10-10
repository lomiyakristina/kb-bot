"""Мини-приложение Красногорских бань.

Цены, окна и тексты берутся из content.py и logic.py — те же, что у бота.
Локальный просмотр не пишет заявку в базу и не пишет администратору.
Настоящая заявка уходит только с подписью Telegram (initData).
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from content import (
    ACHIEVEMENTS,
    ADDRESS,
    ARRIVAL,
    BRAND,
    CERTIFICATES,
    COMING_SOON,
    FAQ,
    FIRST_VISIT,
    FIT,
    HALLS,
    HOURS,
    INSTAGRAM_URL,
    MAP_URL,
    OFFERS,
    PHONE_DISPLAY,
    PHONE_TEL,
    RANKS,
    RESTAURANT,
    RITUALS,
    SITE,
    SPA,
    STEAM_TIMES,
    TARIFFS,
    TELEGRAM_URL,
    UPSELLS,
    VK_URL,
    WELCOME,
    WHATSAPP_URL,
)
from keyboards import admin_keyboard
from logic import (
    booking_days,
    clean_name,
    estimate,
    format_day,
    format_phone,
    host_brief,
    money,
    nearest_entry,
    normalize_phone,
    open_slots,
    rank_for,
)
from storage import PENDING_LIMIT, Storage

ROOT = Path(__file__).resolve().parent
MINIAPP = ROOT / "miniapp"
MSK = ZoneInfo("Europe/Moscow")

STATUS = {
    "new": "ждёт подтверждения",
    "confirmed": "место есть",
    "declined": "нет места",
    "cancelled": "отменена",
    "missed": "гость не пришёл",
}


class QuoteError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message


def now_msk() -> datetime:
    return datetime.now(MSK)


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def plain(text: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return html.unescape(cleaned).strip()


def blocks(text: str) -> list[dict]:
    parts = re.split(r"\n\s*\n", text or "")
    result = []
    for part in parts:
        match = re.match(r"\s*<b>(.*?)</b>\s*(.*)", part, re.S)
        if match:
            heading = plain(match.group(1))
            body = plain(match.group(2))
        else:
            heading = ""
            body = plain(part)
        lines = [line.strip() for line in body.split("\n") if line.strip()]
        if heading or lines:
            result.append({"heading": heading, "lines": lines})
    return result


def lines_of(text: str) -> list[str]:
    return [line.strip() for line in plain(text).split("\n") if line.strip()]


def check_init_data(init_data: str, token: str, now: datetime | None = None) -> dict | None:
    """Подпись Telegram. Без неё гостя нельзя считать настоящим."""
    if not init_data or not token or "сюда" in token:
        return None
    from urllib.parse import parse_qsl

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received = parsed.pop("hash", None)
    if not received:
        return None
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received):
        return None
    try:
        auth_date = int(parsed.get("auth_date") or "0")
    except ValueError:
        return None
    moment = now or datetime.now(MSK)
    if auth_date <= 0 or abs(int(moment.timestamp()) - auth_date) > 86400:
        return None
    try:
        user = json.loads(parsed.get("user") or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int) or user["id"] <= 0:
        return None
    return user


def preview_allowed(request: web.Request) -> bool:
    if os.environ.get("WEBAPP_URL", "").strip().startswith("https://"):
        return False
    return request.remote in {"127.0.0.1", "::1"}


def identify(request: web.Request, body: dict) -> tuple[dict, bool]:
    init_data = str(body.get("initData") or "").strip()
    if init_data:
        user = check_init_data(init_data, os.environ.get("BOT_TOKEN", "").strip())
        if user is None:
            raise QuoteError("Откройте залы из бота Красногорских бань.")
        return user, False
    if preview_allowed(request):
        return {"id": 0, "first_name": "Предпросмотр", "username": None}, True
    raise QuoteError("Откройте залы из бота Красногорских бань.")


def full_name(user: dict) -> str:
    parts = [str(user.get("first_name") or "").strip(), str(user.get("last_name") or "").strip()]
    name = " ".join(part for part in parts if part)
    return name or "Гость"


def find_offer(hall: str, offer_id: str) -> tuple | None:
    for item in OFFERS.get(hall, []):
        if item[0] == offer_id:
            return item
    return None


def quote(payload: dict, now: datetime) -> dict:
    kind = payload.get("kind") or "visit"
    name = clean_name(str(payload.get("name") or ""))
    if not name:
        raise QuoteError("Напишите имя: от 2 до 40 букв.")
    phone = normalize_phone(str(payload.get("phone") or ""))
    if not phone:
        raise QuoteError("Не вижу номер. Нужен российский, 11 цифр.")

    if kind == "certificate":
        try:
            amount = int(payload.get("amount"))
        except (TypeError, ValueError):
            raise QuoteError("Такого сертификата нет")
        if amount not in {item[0] for item in CERTIFICATES}:
            raise QuoteError("Такого сертификата нет")
        title = next(item[1] for item in CERTIFICATES if item[0] == amount)
        return {
            "kind": "certificate",
            "hall": "female",
            "visit_date": now.date().isoformat(),
            "slot_label": f"Сертификат {money(amount)}",
            "guests": 1,
            "guest_name": name,
            "phone": phone,
            "price_each": amount,
            "price_flat": 1,
            "offer_title": title,
            "lines": [
                "Сертификат",
                title,
                f"Для: {name}",
                f"Телефон: {format_phone(phone)}",
                f"Сумма: {money(amount)}",
            ],
            "estimate": "Это заявка на выпуск. Администратор подтвердит, как забрать.",
            "note": "Место и сертификат появляются после подтверждения, не в момент заявки.",
        }

    hall = str(payload.get("hall") or "")
    if hall not in HALLS or not HALLS[hall].get("bookable"):
        raise QuoteError("Этот разряд сейчас не бронируется.")
    found = find_offer(hall, str(payload.get("offer") or ""))
    if found is None:
        raise QuoteError("Такого формата нет")
    _offer_id, offer_title, hours, fixed, cap = found
    try:
        day = date.fromisoformat(str(payload.get("date") or ""))
    except ValueError:
        raise QuoteError("Выберите день ещё раз.")
    if day not in booking_days(now, hours=hours, fixed_price=fixed):
        raise QuoteError("На этот день окна уже другие. Выберите день заново.")
    slots = open_slots(day, now, hours=hours, fixed_price=fixed)
    start = str(payload.get("start") or "")
    slot = next((item for item in slots if item.start == start), None)
    if slot is None:
        raise QuoteError("Это окно уже прошло. Выберите другое.")
    try:
        guests = int(payload.get("guests"))
    except (TypeError, ValueError):
        raise QuoteError("Укажите число гостей.")
    if guests < 1 or guests > int(cap):
        raise QuoteError(f"В этом формате до {cap} гостей.")
    extra_key = str(payload.get("extra") or "none")
    extra = next((item for item in UPSELLS if item[0] == extra_key), None)
    if extra is None:
        raise QuoteError("Такого дополнения нет.")
    _code, extra_title, extra_price = extra
    label = slot.label
    if extra_price:
        label = f"{label} + {extra_title}"
    flat = fixed is not None
    overtime = "Продление комнаты подтвердит администратор." if flat else "После 4 часов — 31 ₽ за минуту."
    summary = [
        HALLS[hall]["title"],
        offer_title,
        format_day(day),
        slot.label,
        f"Гостей: {guests}",
        name,
        format_phone(phone),
    ]
    if extra_price:
        summary.append(f"Дополнительно: {extra_title}")
    return {
        "kind": "visit",
        "hall": hall,
        "visit_date": day.isoformat(),
        "slot_label": label,
        "guests": guests,
        "guest_name": name,
        "phone": phone,
        "price_each": slot.price,
        "price_flat": 1 if flat else 0,
        "offer_title": offer_title,
        "lines": summary,
        "estimate": estimate(slot.price, guests, flat=flat),
        "note": overtime,
    }


def build_catalog(now: datetime) -> dict:
    day, slot = nearest_entry(now)
    when = "Сегодня" if day == now.date() else "Завтра"
    return {
        "ok": True,
        "brand": BRAND,
        "address": ADDRESS,
        "hours": HOURS,
        "phone_display": PHONE_DISPLAY,
        "phone_tel": PHONE_TEL,
        "welcome": lines_of(WELCOME),
        "brief": [line for line in host_brief(now).split("\n") if line.strip()],
        "nearest": {
            "when": when,
            "date": day.isoformat(),
            "label": format_day(day),
            "start": slot.start,
            "end": slot.end,
            "window": slot.label,
            "price": slot.price,
            "price_label": money(slot.price),
        },
        "steam": STEAM_TIMES["male"],
        "halls": {
            key: {
                "title": item["title"],
                "blocks": blocks(item["text"]),
                "bookable": bool(item.get("bookable")),
            }
            for key, item in HALLS.items()
        },
        "offers": {
            hall: [
                {"id": item[0], "title": item[1], "hours": item[2], "flat": item[3] is not None, "cap": item[4]}
                for item in rows
            ]
            for hall, rows in OFFERS.items()
        },
        "tariffs": blocks(TARIFFS),
        "spa": blocks(SPA),
        "restaurant": blocks(RESTAURANT),
        "first_visit": blocks(FIRST_VISIT),
        "arrival": lines_of(ARRIVAL),
        "faq": [{"id": key, "title": item[0], "text": item[1]} for key, item in FAQ.items()],
        "fit": [{"id": key, "title": item[0], "text": item[1]} for key, item in FIT.items()],
        "certificates": [{"amount": amount, "title": title} for amount, title in CERTIFICATES],
        "upsells": [{"id": key, "title": title, "price": price} for key, title, price in UPSELLS],
        "coming_soon": [
            {"id": key, "title": label.split(" — ")[0], "text": label} for key, label in COMING_SOON.items()
        ],
        "links": {
            "map": MAP_URL,
            "site": SITE,
            "telegram": TELEGRAM_URL,
            "instagram": INSTAGRAM_URL,
            "vk": VK_URL,
            "whatsapp": WHATSAPP_URL,
        },
        "ranks": [{"coals": item[0], "title": item[1], "about": item[2]} for item in RANKS],
    }


def days_payload(hall: str, offer_id: str, now: datetime) -> dict:
    found = find_offer(hall, offer_id)
    if found is None or hall not in HALLS:
        raise QuoteError("Такого формата нет")
    _oid, _title, hours, fixed, _cap = found
    days = booking_days(now, hours=hours, fixed_price=fixed)
    return {
        "ok": True,
        "days": [{"date": day.isoformat(), "label": format_day(day, short=True)} for day in days],
    }


def slots_payload(hall: str, offer_id: str, raw_day: str, now: datetime) -> dict:
    found = find_offer(hall, offer_id)
    if found is None:
        raise QuoteError("Такого формата нет")
    _oid, _title, hours, fixed, _cap = found
    try:
        day = date.fromisoformat(raw_day)
    except ValueError:
        raise QuoteError("Выберите день ещё раз.")
    slots = open_slots(day, now, hours=hours, fixed_price=fixed)
    if not slots:
        raise QuoteError("На этот день окна уже прошли")
    return {
        "ok": True,
        "slots": [
            {"start": slot.start, "end": slot.end, "label": slot.label, "price_label": money(slot.price)}
            for slot in slots
        ],
    }


def profile(storage: Storage, user: dict, preview: bool) -> dict:
    today = now_msk().date()
    ritual = RITUALS[today.toordinal() % len(RITUALS)]
    if preview:
        return {
            "ok": True,
            "preview": True,
            "name": "Предпросмотр",
            "coals": 0,
            "rank": RANKS[0][1],
            "about": RANKS[0][2],
            "next": RANKS[1][1],
            "visits": 0,
            "lights": 1,
            "lights_total": len(RANKS),
            "achievements": [],
            "bookings": [],
            "ritual": ritual,
            "ritual_taken": False,
        }
    user_id = int(user["id"])
    storage.ensure_user(user_id, user.get("username"), full_name(user))
    storage.note_start(user_id)
    row = storage.user(user_id)
    if int(row["start_count"] or 0) == 0:
        storage.mark_start(user_id)
        row = storage.user(user_id)
    title, about, _next_at, _floor = rank_for(int(row["coals"]))
    index = next(i for i, item in enumerate(RANKS) if item[1] == title)
    nxt = RANKS[index + 1][1] if index + 1 < len(RANKS) else ""
    bookings = []
    for item in storage.user_bookings(user_id):
        bookings.append(
            {
                "id": int(item["id"]),
                "status": item["status"],
                "status_label": STATUS.get(item["status"], item["status"]),
                "hall": HALLS.get(item["hall"], {}).get("title", item["hall"]),
                "date": format_day(date.fromisoformat(item["visit_date"])),
                "slot": item["slot_label"],
                "guests": int(item["guests"]),
                "can_cancel": item["status"] == "new",
            }
        )
    return {
        "ok": True,
        "preview": False,
        "name": row["full_name"] or full_name(user),
        "coals": int(row["coals"]),
        "rank": title,
        "about": about,
        "next": nxt,
        "visits": int(row["visits"]),
        "lights": index + 1,
        "lights_total": len(RANKS),
        "achievements": [ACHIEVEMENTS[code] for code in sorted(storage.achievements(user_id)) if code in ACHIEVEMENTS],
        "bookings": bookings,
        "ritual": ritual,
        "ritual_taken": row["ritual_day"] == today.isoformat(),
    }


def consent_line() -> str:
    return "Имя и телефон уйдут администратору комплекса — только для этой брони."


async def read_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def fail(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


async def on_catalog(_request: web.Request) -> web.Response:
    return web.json_response(build_catalog(now_msk()))


async def on_days(request: web.Request) -> web.Response:
    try:
        payload = days_payload(request.query.get("hall", ""), request.query.get("offer", ""), now_msk())
    except QuoteError as exc:
        return fail(exc.message)
    return web.json_response(payload)


async def on_slots(request: web.Request) -> web.Response:
    try:
        payload = slots_payload(
            request.query.get("hall", ""),
            request.query.get("offer", ""),
            request.query.get("date", ""),
            now_msk(),
        )
    except QuoteError as exc:
        return fail(exc.message)
    return web.json_response(payload)


async def on_session(request: web.Request) -> web.Response:
    body = await read_body(request)
    try:
        user, preview = identify(request, body)
    except QuoteError as exc:
        return fail(exc.message, 401)
    return web.json_response(profile(request.app["storage"], user, preview))


async def on_quote(request: web.Request) -> web.Response:
    body = await read_body(request)
    try:
        _user, preview = identify(request, body)
        quoted = quote(body, now_msk())
    except QuoteError as exc:
        return fail(exc.message, 401 if "бота" in exc.message else 400)
    quoted["ok"] = True
    quoted["preview"] = preview
    quoted["consent"] = consent_line()
    return web.json_response(quoted)


async def notify(bot: Bot | None, storage: Storage, admins: set[int], booking_id: int) -> None:
    if bot is None:
        return
    row = storage.booking(booking_id)
    if row is None:
        return
    user = storage.user(int(row["user_id"]))
    username = f"@{user['username']}" if user["username"] else "без username"
    hall = HALLS.get(row["hall"], {}).get("title", row["hall"])
    text = (
        f"<b>Заявка №{row['id']}</b> · мини-приложение\n\n"
        f"{html.escape(hall)}\n"
        f"{html.escape(format_day(date.fromisoformat(row['visit_date'])))}\n"
        f"{html.escape(row['slot_label'])}\n"
        f"Гостей: {row['guests']}\n"
        f"{html.escape(row['guest_name'])} · {html.escape(format_phone(row['phone']))}\n"
        f"Telegram: {html.escape(username)} · id {row['user_id']}\n"
        f"Ступень: {html.escape(row['rank_title'])} · визитов {user['visits']}\n"
        f"{html.escape(estimate(row['price_each'], row['guests'], flat=bool(row['price_flat'])))}"
    )
    markup = admin_keyboard(booking_id, "new")
    guest_id = int(row["user_id"])
    for admin_id in admins:
        if admin_id == guest_id:
            continue
        try:
            await bot.send_message(admin_id, text, reply_markup=markup)
        except Exception:
            continue


async def on_booking(request: web.Request) -> web.Response:
    body = await read_body(request)
    try:
        user, preview = identify(request, body)
        quoted = quote(body, now_msk())
    except QuoteError as exc:
        return fail(exc.message, 401 if "бота" in exc.message else 400)
    if preview:
        return web.json_response(
            {
                "ok": True,
                "preview": True,
                "lines": quoted["lines"],
                "estimate": quoted["estimate"],
                "message": "Это просмотр на компьютере. Администратору заявка не ушла.",
                "arrival": lines_of(ARRIVAL),
            }
        )
    storage: Storage = request.app["storage"]
    user_id = int(user["id"])
    storage.ensure_user(user_id, user.get("username"), full_name(user))
    if storage.pending_count(user_id) >= PENDING_LIMIT:
        return fail("Уже три заявки в работе. Дождитесь ответа или отмените одну.")
    title, _about, _next, _floor = rank_for(int(storage.user(user_id)["coals"]))
    booking_id = storage.create_booking(
        {
            "user_id": user_id,
            "hall": quoted["hall"],
            "visit_date": quoted["visit_date"],
            "slot_label": quoted["slot_label"],
            "guests": quoted["guests"],
            "guest_name": quoted["guest_name"],
            "phone": quoted["phone"],
            "price_each": quoted["price_each"],
            "rank_title": title,
            "price_flat": quoted["price_flat"],
        }
    )
    await notify(request.app["bot"], storage, request.app["admins"], booking_id)
    return web.json_response(
        {
            "ok": True,
            "preview": False,
            "id": booking_id,
            "message": f"Заявка №{booking_id} у администратора. Окно не занято, пока её не подтвердят.",
            "coals": "+12 угольков за заявку.",
            "arrival": lines_of(ARRIVAL),
        }
    )


async def on_touch(request: web.Request) -> web.Response:
    body = await read_body(request)
    try:
        user, preview = identify(request, body)
    except QuoteError as exc:
        return fail(exc.message, 401)
    if preview:
        return web.json_response({"ok": True, "notes": []})
    storage: Storage = request.app["storage"]
    user_id = int(user["id"])
    storage.ensure_user(user_id, user.get("username"), full_name(user))
    what = str(body.get("what") or "")
    notes: list[str] = []
    if what in HALLS:
        notes = storage.note_hall(user_id, what)
    elif what == "tariffs":
        notes = storage.note_tariffs(user_id)
    elif what == "schedule":
        notes = storage.note_schedule(user_id, now_msk().date().isoformat())
    storage.log(user_id, "button", {"female": "Женский", "male": "Мужской", "tariffs": "Тарифы", "schedule": "Расписание паров"}.get(what, what))
    return web.json_response({"ok": True, "notes": notes})


async def on_ritual(request: web.Request) -> web.Response:
    body = await read_body(request)
    try:
        user, preview = identify(request, body)
    except QuoteError as exc:
        return fail(exc.message, 401)
    today = now_msk().date()
    ritual = RITUALS[today.toordinal() % len(RITUALS)]
    if preview:
        return web.json_response({"ok": True, "preview": True, "text": ritual, "notes": [], "taken": False})
    storage: Storage = request.app["storage"]
    user_id = int(user["id"])
    storage.ensure_user(user_id, user.get("username"), full_name(user))
    notes = storage.note_ritual(user_id, today.isoformat())
    return web.json_response({"ok": True, "preview": False, "text": ritual, "notes": notes, "taken": not notes})


async def on_wait(request: web.Request) -> web.Response:
    body = await read_body(request)
    try:
        user, preview = identify(request, body)
    except QuoteError as exc:
        return fail(exc.message, 401)
    space = str(body.get("space") or "")
    if space not in COMING_SOON:
        return fail("Неизвестный зал")
    title = COMING_SOON[space].split(" — ")[0]
    if preview:
        return web.json_response(
            {"ok": True, "preview": True, "message": f"В просмотре лист на «{title}» не записывается."}
        )
    storage: Storage = request.app["storage"]
    user_id = int(user["id"])
    storage.ensure_user(user_id, user.get("username"), full_name(user))
    fresh = storage.join_waitlist(user_id, space)
    if not fresh:
        return web.json_response({"ok": True, "message": "Вы уже в этом листе."})
    bot = request.app["bot"]
    if bot is not None:
        for admin_id in request.app["admins"]:
            if admin_id == user_id:
                continue
            try:
                await bot.send_message(
                    admin_id,
                    f"Лист ожидания: {html.escape(title)}\n{html.escape(full_name(user))} · id {user_id}",
                )
            except Exception:
                continue
    return web.json_response({"ok": True, "message": f"Вы в листе на «{title}». Напишем, когда зал откроют."})


async def on_cancel(request: web.Request) -> web.Response:
    body = await read_body(request)
    try:
        user, preview = identify(request, body)
    except QuoteError as exc:
        return fail(exc.message, 401)
    if preview:
        return fail("В просмотре отменять нечего.")
    try:
        booking_id = int(body.get("id"))
    except (TypeError, ValueError):
        return fail("Заявка не найдена")
    storage: Storage = request.app["storage"]
    row = storage.booking(booking_id)
    if row is None or int(row["user_id"]) != int(user["id"]):
        return fail("Это не ваша заявка")
    if row["status"] != "new":
        return fail("Эту заявку уже нельзя отменить.")
    storage.set_status(booking_id, "cancelled")
    return web.json_response({"ok": True, "message": f"Заявка №{booking_id} отменена. Угольки за неё сняты."})


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(MINIAPP / "index.html")


def build_app(bot: Bot | None, storage: Storage, admins: set[int]) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["storage"] = storage
    app["admins"] = admins
    app.router.add_get("/api/catalog", on_catalog)
    app.router.add_get("/api/days", on_days)
    app.router.add_get("/api/slots", on_slots)
    app.router.add_post("/api/session", on_session)
    app.router.add_post("/api/quote", on_quote)
    app.router.add_post("/api/booking", on_booking)
    app.router.add_post("/api/touch", on_touch)
    app.router.add_post("/api/ritual", on_ritual)
    app.router.add_post("/api/wait", on_wait)
    app.router.add_post("/api/cancel", on_cancel)
    app.router.add_get("/", index)
    app.router.add_static("/static", MINIAPP, show_index=False)
    return app


async def start_web(bot: Bot | None, storage: Storage, admins: set[int]) -> web.AppRunner:
    load_env()
    port = int(os.environ.get("WEBAPP_PORT", "8787") or "8787")
    host = os.environ.get("WEBAPP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    runner = web.AppRunner(build_app(bot, storage, admins))
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    print(f"Мини-приложение: http://{host}:{port}")
    return runner


def main() -> None:
    load_env()
    token = os.environ.get("BOT_TOKEN", "").strip()
    bot = None
    if token and "сюда" not in token:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    admins = set()
    for part in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(","):
        if part.isdigit():
            admins.add(int(part))
    app = build_app(bot, Storage(), admins)
    port = int(os.environ.get("WEBAPP_PORT", "8787") or "8787")
    web.run_app(app, host="127.0.0.1", port=port, print=lambda msg: print(msg))


if __name__ == "__main__":
    main()
