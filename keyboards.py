"""Клавиатуры гостя и администратора."""

from __future__ import annotations

import os
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from content import COMING_SOON, MENU


def main_keyboard() -> ReplyKeyboardMarkup:
    rows = []
    url = os.environ.get("WEBAPP_URL", "").strip()
    if url.startswith("https://"):
        rows.append([KeyboardButton(text="Открыть залы", web_app=WebAppInfo(url=url))])
    rows.extend([
        [KeyboardButton(text=MENU["nearest"])],
        [KeyboardButton(text=MENU["female"]), KeyboardButton(text=MENU["male"])],
        [KeyboardButton(text=MENU["heat"]), KeyboardButton(text=MENU["more"])],
    ])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Зал или ближайшее окно",
    )


def more_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Тариф", callback_data="more:tariffs"),
             InlineKeyboardButton(text="Пар по часам", callback_data="more:schedule")],
            [InlineKeyboardButton(text="Парения и SPA", callback_data="more:spa")],
            [InlineKeyboardButton(text="Подарок", callback_data="more:gift"),
             InlineKeyboardButton(text="Контакты", callback_data="more:contacts")],
            [InlineKeyboardButton(text="Что взять с собой", callback_data="faq:pack")],
        ]
    )


def hall_keyboard(hall: str) -> InlineKeyboardMarkup:
    from content import HALLS

    short = {"female": "Женский", "male": "Мужской"}
    others = [
        InlineKeyboardButton(text=short[key], callback_data=f"hall:{key}")
        for key in HALLS
        if key != hall
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Забронировать этот разряд", callback_data=f"book:{hall}")],
            others,
            [InlineKeyboardButton(text="Скоро откроется", callback_data="spaces")],
        ]
    )


def spaces_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label.split(" — ")[0], callback_data=f"wait:{key}")]
        for key, label in COMING_SOON.items()
    ]
    rows.append([InlineKeyboardButton(text="Ресторан", callback_data="restaurant")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Позвонить", callback_data="call:now")],
            [InlineKeyboardButton(text="Тарифы", callback_data="more:tariffs")],
            [InlineKeyboardButton(text="Мужской разряд", callback_data="hall:male"),
             InlineKeyboardButton(text="Женский разряд", callback_data="hall:female")],
            [InlineKeyboardButton(text="Забронировать VIP", callback_data="book:vip")],
        ]
    )


def vip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Женский VIP · 9 000 ₽", callback_data="offer:female:vip")],
            [InlineKeyboardButton(text="Мужской VIP · 21 000 ₽", callback_data="offer:male:vip12")],
        ]
    )


def host_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Занять это окно", callback_data="near:pick")],
            [InlineKeyboardButton(text="Другой день", callback_data="book:pick")],
        ]
    )


def nearest_halls_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Женский", callback_data="near:female"),
             InlineKeyboardButton(text="Мужской", callback_data="near:male")],
            [InlineKeyboardButton(text="Другой день", callback_data="book:pick")],
        ]
    )


def fit_keyboard() -> InlineKeyboardMarkup:
    from content import FIT

    rows = [[InlineKeyboardButton(text=item[0], callback_data=f"fit:{key}")] for key, item in FIT.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_keyboard() -> InlineKeyboardMarkup:
    from content import FAQ

    rows = [[InlineKeyboardButton(text=item[0], callback_data=f"faq:{key}")] for key, item in FAQ.items()]
    rows.append([InlineKeyboardButton(text="Занять ближайшее", callback_data="near:pick")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def upsell_keyboard() -> InlineKeyboardMarkup:
    from content import UPSELLS

    rows = [[InlineKeyboardButton(text=title, callback_data=f"extra:{key}")] for key, title, _price in UPSELLS]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def certificate_keyboard() -> InlineKeyboardMarkup:
    from content import CERTIFICATES

    rows = [[InlineKeyboardButton(text=title, callback_data=f"cert:{amount}")] for amount, title in CERTIFICATES]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def book_halls_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Женский", callback_data="book:female"),
             InlineKeyboardButton(text="Мужской", callback_data="book:male")],
        ]
    )


def offers_keyboard(hall: str) -> InlineKeyboardMarkup:
    from content import OFFERS

    rows = [
        [InlineKeyboardButton(text=item[1], callback_data=f"offer:{hall}:{item[0]}")]
        for item in OFFERS[hall]
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="book:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def days_keyboard(days: list[date], labels: list[str]) -> InlineKeyboardMarkup:
    rows = []
    pair: list[InlineKeyboardButton] = []
    for day, label in zip(days, labels):
        pair.append(InlineKeyboardButton(text=label, callback_data=f"date:{day.isoformat()}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="book:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slots_keyboard(labels: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f"slot:{index}")] for index, label in enumerate(labels)]
    rows.append([InlineKeyboardButton(text="Назад к датам", callback_data="book:dates")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def guests_keyboard(limit: int = 8) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=str(n), callback_data=f"guests:{n}") for n in range(1, limit + 1)]
    rows = [buttons[index:index + 4] for index in range(0, len(buttons), 4)]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="book:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить заявку", callback_data="book:send")],
            [InlineKeyboardButton(text="Заново", callback_data="book:dates"),
             InlineKeyboardButton(text="Отмена", callback_data="book:cancel")],
        ]
    )


def contacts_keyboard() -> InlineKeyboardMarkup:
    from content import INSTAGRAM_URL, MAP_URL, SITE, TELEGRAM_URL, VK_URL, WHATSAPP_URL

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Telegram", url=TELEGRAM_URL),
             InlineKeyboardButton(text="Instagram", url=INSTAGRAM_URL)],
            [InlineKeyboardButton(text="ВКонтакте", url=VK_URL),
             InlineKeyboardButton(text="WhatsApp", url=WHATSAPP_URL)],
            [InlineKeyboardButton(text="Маршрут", url=MAP_URL),
             InlineKeyboardButton(text="Сайт", url=SITE)],
            [InlineKeyboardButton(text="Ресторан", callback_data="restaurant")],
            [InlineKeyboardButton(text="Первый визит", callback_data="visit")],
            [InlineKeyboardButton(text="Скоро откроется", callback_data="spaces")],
        ]
    )


def heat_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Занять ближайшее окно", callback_data="near:pick")],
            [InlineKeyboardButton(text="Огонёк на сегодня", callback_data="ritual")],
        ]
    )


def user_cancel_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отменить заявку", callback_data=f"user:cancel:{booking_id}")]]
    )


def broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Отправить всем", callback_data="broadcast:yes"),
            InlineKeyboardButton(text="Отмена", callback_data="broadcast:no"),
        ]]
    )


def admin_keyboard(booking_id: int, status: str = "new") -> InlineKeyboardMarkup:
    if status == "new":
        return InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="Подтвердить", callback_data=f"adm:ok:{booking_id}"),
                InlineKeyboardButton(text="Нет места", callback_data=f"adm:no:{booking_id}"),
            ]]
        )
    if status == "confirmed":
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Гость не пришёл", callback_data=f"adm:miss:{booking_id}")]]
        )
    return InlineKeyboardMarkup(inline_keyboard=[])
