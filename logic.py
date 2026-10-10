"""Расчёт окон, тарифа, званий. Без Telegram — это можно проверять тестами."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from content import RANKS, STEAM_TIMES

ENTRY_HOURS = tuple(range(9, 19))

MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


@dataclass(frozen=True)
class Slot:
    start: str
    end: str
    price: int

    @property
    def label(self) -> str:
        return f"{self.start}–{self.end}"


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def ticket_price(day: date, hour: int) -> int:
    if is_weekend(day) or hour >= 14:
        return 5700
    return 4500


def slots_for(day: date, hours: int = 4, fixed_price: int | None = None) -> list[Slot]:
    slots = []
    for hour in ENTRY_HOURS:
        start = f"{hour:02d}:00"
        end = f"{hour + hours:02d}:00"
        price = fixed_price if fixed_price else ticket_price(day, hour)
        slots.append(Slot(start, end, price))
    return slots


def open_slots(day: date, now: datetime, hours: int = 4, fixed_price: int | None = None) -> list[Slot]:
    slots = slots_for(day, hours=hours, fixed_price=fixed_price)
    if day != now.date():
        return slots
    current = now.strftime("%H:%M")
    return [slot for slot in slots if slot.start > current]


def next_steam(now: datetime) -> tuple[date, str]:
    times = STEAM_TIMES["male"]
    current = now.strftime("%H:%M")
    upcoming = [item for item in times if item > current]
    if upcoming:
        return now.date(), upcoming[0]
    return now.date() + timedelta(days=1), times[0]


def nearest_entry(now: datetime, hours: int = 4) -> tuple[date, Slot]:
    today = open_slots(now.date(), now, hours=hours)
    if today:
        return now.date(), today[0]
    tomorrow = now.date() + timedelta(days=1)
    return tomorrow, slots_for(tomorrow, hours=hours)[0]


def host_brief(now: datetime) -> str:
    day, steam = next_steam(now)
    when = "сегодня" if day == now.date() else "завтра"
    steam_line = f"Ближайший авторский пар — {when} в {steam}. Он уже в билете."
    if not open_slots(now.date(), now):
        tomorrow = now.date() + timedelta(days=1)
        price = ticket_price(tomorrow, 9)
        return f"На сегодня вход закрыт. Завтра с 9:00 — {money(price)} за 4 часа.\n{steam_line}"
    price = ticket_price(now.date(), now.hour)
    benefit = ""
    if now.weekday() <= 2 and now.hour < 14 and not is_weekend(now.date()):
        benefit = "\nДо 13:59 по удостоверению — 1 500 ₽."
    return f"Если войти сейчас — {money(price)} за 4 часа.{benefit}\n{steam_line}"


def booking_days(
    now: datetime,
    horizon: int = 14,
    hours: int = 4,
    fixed_price: int | None = None,
) -> list[date]:
    start = now.date()
    if not open_slots(start, now, hours=hours, fixed_price=fixed_price):
        start = start + timedelta(days=1)
    return [start + timedelta(days=offset) for offset in range(horizon)]


def format_day(day: date, short: bool = False) -> str:
    weekday = WEEKDAYS_SHORT[day.weekday()] if short else WEEKDAYS[day.weekday()]
    if short:
        return f"{weekday} {day.day} {MONTHS[day.month - 1][:3]}"
    return f"{weekday}, {day.day} {MONTHS[day.month - 1]}"


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def coals_phrase(amount: int) -> str:
    number = abs(amount)
    tail = number % 100
    last = number % 10
    if 11 <= tail <= 14:
        word = "угольков"
    elif last == 1:
        word = "уголёк"
    elif last in (2, 3, 4):
        word = "уголька"
    else:
        word = "угольков"
    sign = "+" if amount > 0 else "−"
    return f"{sign}{number} {word}"


def estimate(price_each: int, guests: int, flat: bool = False) -> str:
    if flat:
        return (
            f"Комната: {money(price_each)} за окно. "
            "Входные билеты гостей администратор подтвердит отдельно, если они не входят в комнату."
        )
    total = price_each * guests
    return (
        f"Ориентир для взрослых: {money(price_each)} × {guests} = {money(total)}. "
        "Детям с 7 до 12 лет — половина, до 7 лет бесплатно. "
        "Льготу пересчитают на ресепшен по удостоверению."
    )


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("7"):
        return None
    return "+" + digits


def format_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) != 11:
        return phone
    return f"+{digits[0]} {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def rank_for(coals: int) -> tuple[str, str, int | None, int]:
    """Звание, описание, порог следующего, угольки текущего порога."""
    current = RANKS[0]
    nxt: tuple[int, str, str] | None = None
    for item in RANKS:
        if coals >= item[0]:
            current = item
        elif nxt is None:
            nxt = item
            break
    next_at = nxt[0] if nxt else None
    return current[1], current[2], next_at, current[0]


def progress_bar(coals: int, width: int = 10) -> str:
    _, _, next_at, floor = rank_for(coals)
    if next_at is None:
        return "█" * width
    span = max(next_at - floor, 1)
    filled = int(round(width * (coals - floor) / span))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def clean_name(raw: str) -> str | None:
    name = " ".join((raw or "").split())
    if len(name) < 2 or len(name) > 40:
        return None
    if any(ch in name for ch in "<>{}[]"):
        return None
    return name
