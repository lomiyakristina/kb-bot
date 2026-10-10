"""Таблица учёта: кто нажал Старт и на каком этапе остановился."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from paths import data_dir

DESKTOP = Path.home() / "Desktop" / "красногорские-бани-учет.xlsx"

HALLS = {
    "male": "Мужской разряд",
    "female": "Женский разряд",
    "family": "Семейный разряд",
}
BOOKING = {
    "new": "Оставил заявку",
    "confirmed": "Подтверждено",
    "declined": "Нет места",
    "cancelled": "Гость отменил",
    "missed": "Не пришёл",
}
RANK = [
    ("missed", "Не пришёл"),
    ("confirmed", "Подтверждено"),
    ("declined", "Нет места"),
    ("cancelled", "Гость отменил"),
    ("new", "Оставил заявку"),
]


def stamp(raw: str | None) -> str:
    if not raw:
        return ""
    day, _, clock = raw.partition("T")
    parts = day.split("-")
    if len(parts) != 3:
        return raw
    pretty = f"{parts[2]}.{parts[1]}.{parts[0]}"
    if clock:
        pretty += " " + clock[:5]
    return pretty


def stage(buttons: set[str], booking_status: str | None) -> str:
    if booking_status:
        for code, title in RANK:
            if booking_status == code:
                return title
    if "Забронировать" in buttons:
        return "Начал бронь"
    if buttons & {"Тарифы", "Расписание паров"}:
        return "Смотрел тариф"
    if buttons & {"Женский", "Мужской", "Зайти сегодня", "Парения и SPA"}:
        return "Смотрел зал"
    if buttons:
        return "Смотрел меню"
    return "Нажал Старт"


def person_stage(user: sqlite3.Row, buttons: set[str], booking_status: str | None) -> str:
    if int(user["start_count"] or 0) <= 0:
        return "Зашёл, Старт не нажал"
    return stage(buttons, booking_status)


def write(conn: sqlite3.Connection) -> Path:
    users = conn.execute(
        "SELECT * FROM users ORDER BY COALESCE(last_start_at, created_at) DESC"
    ).fetchall()
    events = conn.execute(
        "SELECT * FROM events ORDER BY id"
    ).fetchall()
    bookings = conn.execute(
        "SELECT * FROM bookings ORDER BY id DESC"
    ).fetchall()
    by_user_buttons: dict[int, set[str]] = {}
    names = {int(row["user_id"]): row for row in users}
    for event in events:
        if event["kind"] != "button":
            continue
        by_user_buttons.setdefault(int(event["user_id"]), set()).add(event["label"] or "")
    latest_booking: dict[int, sqlite3.Row] = {}
    for booking in bookings:
        latest_booking.setdefault(int(booking["user_id"]), booking)

    book = Workbook()
    guests = book.active
    guests.title = "Гости"
    headers = [
        "Имя",
        "Telegram",
        "Откуда",
        "Первый Старт",
        "Последний заход",
        "Раз нажал Старт",
        "Этап",
        "Что смотрел",
        "Заявка",
        "Разряд",
        "Дата визита",
        "Гостей",
        "Телефон",
        "Бот заблокирован",
    ]
    guests.append(headers)
    for cell in guests[1]:
        cell.font = Font(bold=True)
    for user in users:
        user_id = int(user["user_id"])
        booking = latest_booking.get(user_id)
        looked = by_user_buttons.get(user_id, set())
        status = booking["status"] if booking else None
        source = ""
        try:
            source = user["source"] or ""
        except (IndexError, KeyError):
            source = ""
        guests.append([
            user["full_name"] or "",
            f"@{user['username']}" if user["username"] else "",
            source,
            stamp(user["created_at"]),
            stamp(user["last_start_at"]),
            int(user["start_count"] or 0),
            person_stage(user, looked, status),
            ", ".join(sorted(item for item in looked if item)),
            BOOKING.get(status, "") if status else "",
            HALLS.get(booking["hall"], booking["hall"]) if booking else "",
            booking["visit_date"] if booking else "",
            booking["guests"] if booking else "",
            booking["phone"] if booking else "",
            "да" if int(user["blocked"] or 0) else "",
        ])
    for column in guests.columns:
        guests.column_dimensions[column[0].column_letter].width = 22

    steps = book.create_sheet("Шаги")
    steps.append(["Когда", "Имя", "Telegram", "Шаг", "Деталь"])
    for cell in steps[1]:
        cell.font = Font(bold=True)
    for event in events:
        user = names.get(int(event["user_id"]))
        kind = {"start": "Старт", "button": "Кнопка", "booking": "Заявка", "broadcast": "Рассылка"}.get(
            event["kind"], event["kind"]
        )
        detail = event["label"] or ""
        if event["kind"] == "booking":
            detail = BOOKING.get(detail, detail)
        steps.append([
            stamp(event["created_at"]),
            (user["full_name"] if user else "") or "",
            f"@{user['username']}" if user and user["username"] else "",
            kind,
            detail,
        ])
    for column in steps.columns:
        steps.column_dimensions[column[0].column_letter].width = 24

    path = data_dir() / "учет-гостей.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    try:
        book.save(DESKTOP)
    except OSError:
        pass
    return path
