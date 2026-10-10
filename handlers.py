"""Сценарии бота: разряды, тариф, бронь, жар, админ."""

from __future__ import annotations

import asyncio
import html
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from content import (
    ACHIEVEMENTS,
    ADDRESS,
    BRAND,
    COMING_SOON,
    ARRIVAL,
    FAQ,
    FIRST_VISIT,
    FIT,
    HALLS,
    HOURS,
    MENU,
    OFFERS,
    OWNER_ID,
    INSTAGRAM_URL,
    PHONE_DISPLAY,
    PHONE_TEL,
    RANKS,
    RESTAURANT,
    RITUALS,
    SPA,
    STEAM_TIMES,
    TELEGRAM_URL,
    TARIFFS,
    UPSELLS,
    VK_URL,
    WELCOME,
)
from keyboards import (
    admin_keyboard,
    broadcast_keyboard,
    book_halls_keyboard,
    certificate_keyboard,
    confirm_keyboard,
    faq_keyboard,
    fit_keyboard,
    contacts_keyboard,
    days_keyboard,
    guests_keyboard,
    hall_keyboard,
    heat_keyboard,
    home_keyboard,
    main_keyboard,
    more_keyboard,
    welcome_keyboard,
    nearest_halls_keyboard,
    offers_keyboard,
    slots_keyboard,
    spaces_keyboard,
    section_nav,
    upsell_keyboard,
    user_cancel_keyboard,
    with_nav,
)
from logic import (
    Slot,
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
    progress_bar,
    rank_for,
)
from storage import PENDING_LIMIT, Storage

ROOT = Path(__file__).resolve().parent
MSK = ZoneInfo("Europe/Moscow")
router = Router()
store: Storage
ADMIN_IDS: set[int] = set()


class Book(StatesGroup):
    name = State()
    phone = State()
    confirm = State()


class Broadcast(StatesGroup):
    draft = State()
    confirm = State()


def setup(storage: Storage, admin_ids: set[int]) -> None:
    global store, ADMIN_IDS
    store = storage
    ADMIN_IDS = admin_ids


def now_msk() -> datetime:
    return datetime.now(MSK)


def guest_name(message: Message) -> str:
    user = message.from_user
    return user.full_name if user and user.full_name else "Гость"


def remember(message: Message) -> int:
    user = message.from_user
    assert user is not None
    store.ensure_user(user.id, user.username, user.full_name or "Гость")
    return user.id


async def toast(notes: list[str], query: CallbackQuery | None = None) -> str:
    line = " · ".join(notes)
    if query and line:
        await query.answer(line[:180])
    elif query:
        await query.answer()
    return line


def with_notes(text: str, notes: list[str]) -> str:
    if not notes:
        return text
    return text + "\n\n<i>" + html.escape(" · ".join(notes)) + "</i>"


async def show_photo(message: Message, filename: str, caption: str, markup) -> None:
    path = ROOT / "photos" / filename
    if path.exists():
        await message.answer_photo(FSInputFile(path), caption=caption, reply_markup=markup)
    else:
        await message.answer(caption, reply_markup=markup)


async def show_welcome_video(message: Message, caption: str, markup) -> None:
    path = ROOT / "photos" / "welcome.mp4"
    if not path.exists():
        await show_photo(message, "hero.jpg", caption, markup)
        return
    await message.answer_video(
        FSInputFile(path),
        caption=caption,
        reply_markup=markup,
        width=720,
        height=1280,
        duration=33,
        supports_streaming=True,
    )


def schedule_text() -> str:
    times = ", ".join(STEAM_TIMES["male"])
    return (
        "<b>Авторский пар</b>\n"
        "Каждые 1,5 часа, в мужском и женском разрядах одинаково. "
        "Входит в стоимость посещения.\n\n"
        f"{times}\n\n"
        "Сеанс билета — 4 часа с момента входа.\n"
        f"{HOURS.capitalize()}.\n\n"
        "Чтобы занять окно, выберите разряд ниже."
    )


def heat_text(user_id: int) -> str:
    user = store.user(user_id)
    title, about, _next_at, _floor = rank_for(user["coals"])
    index = next(i for i, item in enumerate(RANKS) if item[1] == title)
    lights = "●" * (index + 1) + "○" * (len(RANKS) - index - 1)
    if index + 1 < len(RANKS):
        nxt = RANKS[index + 1][1]
        goal = f"Дальше — {nxt}. Зажигается подтверждённым визитом."
    else:
        goal = "Все пять огоньков. На входе встречают по имени."
    return (
        f"<b>Мой жар</b>\n"
        f"{lights}  <b>{html.escape(title)}</b>\n"
        f"{html.escape(about)}\n\n"
        f"{html.escape(goal)}\n"
        f"Визитов: {user['visits']}"
    )


def contacts_text() -> str:
    return (
        f"<b>Контакты</b>\n\n"
        f"{BRAND}\n"
        f"{ADDRESS}\n"
        f"{HOURS.capitalize()}.\n"
        f"Телефон: {PHONE_DISPLAY}\n\n"
        f'<a href="{TELEGRAM_URL}">Telegram</a> · @krasnogorskie_bani\n'
        f'<a href="{INSTAGRAM_URL}">Instagram</a>\n'
        f'<a href="{VK_URL}">ВКонтакте</a>'
    )


def draft_text(data: dict) -> str:
    hall = HALLS[data["hall"]]["title"]
    day = date.fromisoformat(data["date"])
    slot = Slot(data["start"], data["end"], int(data["price"]))
    flat = bool(data.get("flat"))
    extra = ""
    if data.get("extra_title"):
        extra = f"\nДополнительно: {data['extra_title']}"
    if data.get("certificate"):
        return (
            "<b>Сертификат</b>\n\n"
            f"{html.escape(data.get('offer_title') or 'Сертификат')}\n"
            f"Для: {html.escape(data['guest_name'])}\n"
            f"Телефон: {html.escape(format_phone(data['phone']))}\n"
            f"Сумма: {html.escape(money(int(data['price'])))}\n\n"
            "Это заявка на выпуск. Администратор подтвердит, как забрать."
        )
    overtime = "Продление комнаты подтвердит администратор." if flat else "После 4 часов — 31 ₽ за минуту."
    return (
        "<b>Заявка</b>\n\n"
        f"{html.escape(hall)}\n"
        f"{html.escape(data.get('offer_title') or 'Вход')}\n"
        f"{html.escape(format_day(day))}\n"
        f"{html.escape(slot.label)}\n"
        f"Гостей: {data['guests']}\n"
        f"{html.escape(data['guest_name'])}\n"
        f"{html.escape(format_phone(data['phone']))}\n\n"
        f"{html.escape(estimate(slot.price, int(data['guests']), flat=flat))}{html.escape(extra)}\n\n"
        f"{overtime}\n"
        "Место появляется после подтверждения администратора, не в момент заявки.\n\n"
        "Кнопка «Отправить заявку» передаёт имя и телефон администратору комплекса — только для этой брони."
    )


def admin_card(row) -> str:
    user = store.user(row["user_id"])
    username = f"@{user['username']}" if user["username"] else "без username"
    return (
        f"<b>Заявка №{row['id']}</b> · {html.escape(row['status'])}\n\n"
        f"{html.escape(HALLS[row['hall']]['title'])}\n"
        f"{html.escape(format_day(date.fromisoformat(row['visit_date'])))}\n"
        f"{html.escape(row['slot_label'])}\n"
        f"Гостей: {row['guests']}\n"
        f"{html.escape(row['guest_name'])} · {html.escape(format_phone(row['phone']))}\n"
        f"Telegram: {html.escape(username)} · id {row['user_id']}\n"
        f"Ступень: {html.escape(row['rank_title'])} · визитов {user['visits']}\n"
        f"{html.escape(estimate(row['price_each'], row['guests'], flat=bool(row['price_flat'])))}"
    )


async def notify_admins(message: Message, booking_id: int) -> None:
    row = store.booking(booking_id)
    if row is None:
        return
    text = admin_card(row)
    markup = admin_keyboard(booking_id, "new")
    delivered = False
    guest_id = int(row["user_id"])
    for admin_id in (OWNER_ID,):
        if admin_id == guest_id:
            continue
        try:
            await message.bot.send_message(admin_id, text, reply_markup=markup)
            delivered = True
        except Exception:
            continue
    if not delivered:
        await message.answer(
            "Заявка записана. Администратор увидит её, когда в .env будет его Telegram id — команда /whoami."
        )


async def begin_dates(target: Message, state: FSMContext, hall: str) -> None:
    data = await state.get_data()
    hours = int(data.get("hours") or 4)
    fixed = data.get("fixed_price")
    offer_title = data.get("offer_title") or "Вход"
    flat = bool(data.get("flat"))
    guest_cap = int(data.get("guest_cap") or 8)
    await state.set_state(None)
    await state.update_data(
        hall=hall,
        hours=hours,
        fixed_price=fixed,
        offer_title=offer_title,
        flat=flat,
        guest_cap=guest_cap,
    )
    moment = now_msk()
    days = booking_days(moment, hours=hours, fixed_price=fixed)
    labels = [format_day(day, short=True) for day in days]
    await target.answer(
        f"<b>{html.escape(HALLS[hall]['title'])}</b>\n"
        f"{html.escape(data.get('offer_title') or 'Вход')}. Выберите день.",
        reply_markup=days_keyboard(days, labels),
    )


MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def format_stamp(raw: str | None) -> str:
    if not raw:
        return "—"
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    return f"{moment.day} {MONTHS[moment.month - 1]}, {moment:%H:%M}"


SOURCE_LABELS = {
    "instagram": "Instagram",
    "ig": "Instagram",
    "stories": "Stories",
    "reels": "Reels",
    "vk": "VK",
    "friends": "Друзья",
    "maps": "Карты",
    "site": "Сайт",
    "qr": "QR",
    "ads": "Реклама",
    "whatsapp": "WhatsApp",
}


def source_label(raw: str | None) -> str:
    code = (raw or "").strip().lower()
    if not code:
        return ""
    return SOURCE_LABELS.get(code, code)


def start_card(row, first: bool) -> str:
    username = f"@{row['username']}" if row["username"] else "без username"
    title = "Новый человек нажал Старт" if first else "Снова нажал Старт"
    count = int(row["start_count"] or 0)
    when = "первый заход" if first else f"заход {count}"
    source = source_label(row["source"] if "source" in row.keys() else None)
    source_line = f"\nоткуда: {html.escape(source)}" if source else ""
    return (
        f"<b>{title}</b>\n"
        f"{html.escape(row['full_name'] or 'Гость')}\n"
        f"{html.escape(username)}\n"
        f"{when} · {html.escape(format_stamp(row['last_start_at']))}"
        f"{source_line}\n"
        f"id <code>{row['user_id']}</code>"
    )


async def notify_start(message: Message, row, first: bool) -> None:
    text = start_card(row, first)
    guest_id = message.from_user.id if message.from_user else int(row["user_id"])
    for admin_id in (OWNER_ID,):
        if admin_id == guest_id:
            continue
        try:
            await message.bot.send_message(admin_id, text)
        except Exception:
            continue


def guests_text() -> str:
    total, rows = store.starts(30)
    if total == 0:
        return "Пока никто не нажимал Старт."
    lines = [f"<b>Кто нажал Старт</b> · {total}"]
    for index, row in enumerate(rows, start=1):
        username = f"@{row['username']}" if row["username"] else "без username"
        source = source_label(row["source"] if "source" in row.keys() else None)
        source_part = f" · откуда: {html.escape(source)}" if source else ""
        lines.append(
            f"\n{index}. {html.escape(row['full_name'] or 'Гость')} · {html.escape(username)}\n"
            f"последний заход {html.escape(format_stamp(row['last_start_at']))} · всего {int(row['start_count'] or 0)}"
            f"{source_part}"
        )
    if total > len(rows):
        lines.append(f"\nПоказаны последние {len(rows)} из {total}.")
    return "".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    await state.clear()
    user_id = remember(message)
    store.note_start(user_id)
    first, row = store.mark_start(user_id, command.args)
    await message.answer(WELCOME, reply_markup=welcome_keyboard())
    await notify_start(message, row, first)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    remember(message)
    await message.answer("Меню на клавиатуре снизу.", reply_markup=main_keyboard())


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    user = message.from_user
    assert user is not None
    role = "администратор" if user.id in ADMIN_IDS else "гость"
    await message.answer(f"Ваш id: <code>{user.id}</code>\nРоль сейчас: {role}")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Черновик брони закрыт.", reply_markup=main_keyboard())


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    user = message.from_user
    assert user is not None
    if user.id not in ADMIN_IDS:
        await message.answer("Этот раздел только для администратора комплекса.")
        return
    rows = store.pending()
    if not rows:
        await message.answer("Новых заявок нет.")
        return
    await message.answer(f"Новых заявок: {len(rows)}")
    for row in rows:
        await message.answer(admin_card(row), reply_markup=admin_keyboard(row["id"], "new"))


@router.message(Command("guests"))
async def cmd_guests(message: Message) -> None:
    user = message.from_user
    assert user is not None
    if user.id not in ADMIN_IDS:
        await message.answer("Этот список только для администратора комплекса.")
        return
    await message.answer(guests_text())


STATUS_RU = {
    "new": "новые",
    "confirmed": "подтверждённые",
    "declined": "нет места",
    "cancelled": "гость отменил",
    "missed": "не пришёл",
}


def stats_text() -> str:
    data = store.stats()
    lines = [
        "<b>Статистика</b>",
        f"Нажали Старт: {data['people']}",
        f"Сегодня заходили: {data['today']}",
        f"Новые сегодня: {data['first_today']}",
        f"Всего нажатий Старт: {data['starts']}",
        f"Заблокировали бота: {data['blocked']}",
    ]
    if data["bookings"]:
        lines.append("\n<b>Заявки</b>")
        for status, count in data["bookings"].items():
            lines.append(f"{STATUS_RU.get(status, status)}: {count}")
    else:
        lines.append("\nЗаявок пока нет.")
    if data["buttons"]:
        lines.append("\n<b>Что нажимали</b>")
        for label, count in data["buttons"]:
            lines.append(f"{html.escape(label or '—')}: {count}")
    return "\n".join(lines)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    user = message.from_user
    assert user is not None
    if user.id not in ADMIN_IDS:
        await message.answer("Статистика только для администратора комплекса.")
        return
    await message.answer(stats_text())


@router.message(Command("table"))
async def cmd_table(message: Message) -> None:
    user = message.from_user
    assert user is not None
    if user.id not in ADMIN_IDS:
        await message.answer("Таблица только для администратора комплекса.")
        return
    path = store.refresh_ledger()
    if path is None or not path.exists():
        await message.answer("Таблица ещё не собралась.")
        return
    await message.answer_document(
        FSInputFile(path),
        caption="Кто нажал Старт и на каком этапе остановился. Файл обновляется сам.",
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    user = message.from_user
    assert user is not None
    if user.id not in ADMIN_IDS:
        await message.answer("Рассылка только для администратора комплекса.")
        return
    await state.set_state(Broadcast.draft)
    await message.answer(
        "Пришлите сообщение рассылки: текст, фото или видео.\n"
        "Оно уйдёт всем, кто нажал Старт.\n"
        "/cancel — не отправлять."
    )


@router.message(Broadcast.draft)
async def broadcast_draft(message: Message, state: FSMContext) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Broadcast.confirm)
    count = len(store.audience())
    await message.answer(
        f"Отправить это {count} людям, которые нажали Старт?",
        reply_markup=broadcast_keyboard(),
    )


@router.callback_query(F.data == "broadcast:no")
async def broadcast_no(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await query.answer("Отменено")
    if query.message:
        await query.message.answer("Рассылка отменена.")


@router.callback_query(F.data == "broadcast:yes")
async def broadcast_yes(query: CallbackQuery, state: FSMContext) -> None:
    user = query.from_user
    if user.id not in ADMIN_IDS:
        await query.answer("Только администратор")
        return
    data = await state.get_data()
    await state.clear()
    if "chat_id" not in data or "message_id" not in data:
        await query.answer("Нет сообщения для рассылки")
        return
    ids = [item for item in store.audience() if item != user.id]
    await query.answer()
    if query.message:
        await query.message.answer(f"Отправляю {len(ids)}…")
    sent = 0
    failed = 0
    for user_id in ids:
        try:
            await query.bot.copy_message(user_id, data["chat_id"], data["message_id"])
            sent += 1
        except Exception as exc:
            failed += 1
            reason = str(exc).lower()
            if "forbidden" in reason or "blocked" in reason or "deactivated" in reason:
                store.set_blocked(user_id)
        await asyncio.sleep(0.05)
    store.log(user.id, "broadcast", f"ушло {sent}, не дошло {failed}")
    if query.message:
        await query.message.answer(f"Ушло {sent}. Не дошло {failed}.")


@router.message(F.text.in_(list(MENU.values())))
async def on_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = remember(message)
    text = message.text or ""
    store.log(user_id, "button", text)
    if text == MENU["female"]:
        notes = store.note_hall(user_id, "female")
        await show_photo(message, HALLS["female"]["photo"], with_notes(HALLS["female"]["text"], notes), with_nav(hall_keyboard("female")))
    elif text == MENU["male"]:
        notes = store.note_hall(user_id, "male")
        await show_photo(message, HALLS["male"]["photo"], with_notes(HALLS["male"]["text"], notes), with_nav(hall_keyboard("male")))
    elif text == MENU["tariffs"]:
        notes = store.note_tariffs(user_id)
        await show_photo(message, "tariffs.png", with_notes(TARIFFS, notes), section_nav())
    elif text == MENU["schedule"]:
        notes = store.note_schedule(user_id, now_msk().date().isoformat())
        await message.answer(with_notes(schedule_text(), notes), reply_markup=with_nav(book_halls_keyboard()))
    elif text == MENU["spa"]:
        await message.answer(SPA, reply_markup=section_nav())
    elif text == MENU["nearest"]:
        await message.answer(host_brief(now_msk()) + "\n\nКакой разряд?", reply_markup=nearest_halls_keyboard())
    elif text == MENU["book"]:
        await message.answer("Какой разряд бронируем?", reply_markup=book_halls_keyboard())
    elif text == MENU["heat"]:
        await message.answer(heat_text(user_id), reply_markup=heat_keyboard())
    elif text == MENU["more"]:
        await message.answer("Тариф, пар, подарок и как добраться.", reply_markup=more_keyboard())
    elif text == MENU["contacts"]:
        await show_photo(message, "hero.jpg", contacts_text(), contacts_keyboard())


@router.callback_query(F.data == "call:now")
async def on_call(query: CallbackQuery) -> None:
    assert query.message
    user = query.from_user
    store.ensure_user(user.id, user.username, user.full_name or "Гость")
    store.log(user.id, "button", "Позвонить")
    await query.message.answer(
        f'Позвонить по телефону <a href="tel:{PHONE_TEL}">8-925-105-77-77</a>',
        reply_markup=home_keyboard(),
    )
    await query.answer()


@router.callback_query(F.data == "menu:home")
async def on_home(query: CallbackQuery, state: FSMContext) -> None:
    assert query.message
    await state.clear()
    await query.message.answer(WELCOME, reply_markup=welcome_keyboard())
    await query.answer()


@router.callback_query(F.data.startswith("hall:"))
async def on_hall(query: CallbackQuery) -> None:
    assert query.data and query.message
    hall = query.data.split(":", 1)[1]
    if hall not in HALLS:
        await query.answer("Такого разряда нет")
        return
    user = query.from_user
    store.ensure_user(user.id, user.username, user.full_name or "Гость")
    notes = store.note_hall(user.id, hall)
    await toast(notes, query)
    await show_photo(query.message, HALLS[hall]["photo"], with_notes(HALLS[hall]["text"], notes), with_nav(hall_keyboard(hall)))


@router.callback_query(F.data == "spaces")
async def on_spaces(query: CallbackQuery) -> None:
    assert query.message
    lines = ["<b>Скоро откроется</b>", "Нажмите зал — оставим вас в листе, когда он заработает.", ""]
    lines.extend(COMING_SOON.values())
    await query.message.answer("\n".join(lines), reply_markup=spaces_keyboard())
    await query.answer()


@router.callback_query(F.data.startswith("wait:"))
async def on_wait(query: CallbackQuery) -> None:
    assert query.data
    space = query.data.split(":", 1)[1]
    if space not in COMING_SOON:
        await query.answer("Неизвестный зал")
        return
    user = query.from_user
    store.ensure_user(user.id, user.username, user.full_name or "Гость")
    fresh = store.join_waitlist(user.id, space)
    if fresh:
        await query.answer("Записали. +4 уголька")
        title = COMING_SOON[space].split(" — ")[0]
        await query.message.answer(
            f"Вы в листе на «{title}». Администратор это видит и сможет написать, когда зал откроют."
        )
        for admin_id in (OWNER_ID,):
            if admin_id == user.id:
                continue
            try:
                await query.bot.send_message(
                    admin_id,
                    f"Лист ожидания: {html.escape(COMING_SOON[space].split(' — ')[0])}\n"
                    f"{html.escape(user.full_name or 'Гость')} · id {user.id}",
                )
            except Exception:
                continue
    else:
        await query.answer("Вы уже в этом листе")


@router.callback_query(F.data.startswith("more:"))
async def on_more(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    key = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    store.ensure_user(user_id, query.from_user.username, query.from_user.full_name or "Гость")
    if key == "tariffs":
        notes = store.note_tariffs(user_id)
        await show_photo(query.message, "tariffs.png", with_notes(TARIFFS, notes), section_nav())
    elif key == "schedule":
        notes = store.note_schedule(user_id, now_msk().date().isoformat())
        await query.message.answer(with_notes(schedule_text(), notes), reply_markup=with_nav(book_halls_keyboard()))
    elif key == "spa":
        await query.message.answer(SPA, reply_markup=section_nav())
    elif key == "gift":
        await query.message.answer("Сертификат на сумму из прайса. Администратор подготовит.", reply_markup=certificate_keyboard())
    elif key == "contacts":
        await query.message.answer(contacts_text(), reply_markup=contacts_keyboard())
    await query.answer()


@router.callback_query(F.data == "visit")
async def on_visit(query: CallbackQuery) -> None:
    assert query.message
    await query.message.answer(FIRST_VISIT)
    await query.answer()


@router.callback_query(F.data == "restaurant")
async def on_restaurant(query: CallbackQuery) -> None:
    assert query.message
    await show_photo(query.message, "restaurant.jpg", RESTAURANT, section_nav())
    await query.answer()


@router.callback_query(F.data == "ritual")
async def on_ritual(query: CallbackQuery) -> None:
    user = query.from_user
    store.ensure_user(user.id, user.username, user.full_name or "Гость")
    today = now_msk().date()
    ritual = RITUALS[today.toordinal() % len(RITUALS)]
    notes = store.note_ritual(user.id, today.isoformat())
    await toast(notes, query)
    text = "<b>Ритуал дня</b>\n\n" + html.escape(ritual)
    if not notes:
        text += "\n\n<i>На сегодня уже забран.</i>"
    await query.message.answer(with_notes(text, notes), reply_markup=heat_keyboard())


def _label_with_extra(data: dict) -> str:
    label = str(data["slot_label"])
    if data.get("extra_title"):
        label = f"{label} + {data['extra_title']}"
    return label


@router.callback_query(F.data == "fit")
async def on_fit_menu(query: CallbackQuery) -> None:
    assert query.message
    await query.message.answer("Для кого визит? От этого зависит, что предлагать.", reply_markup=fit_keyboard())
    await query.answer()


@router.callback_query(F.data.startswith("fit:"))
async def on_fit(query: CallbackQuery) -> None:
    assert query.data and query.message
    key = query.data.split(":", 1)[1]
    if key not in FIT:
        await query.answer("Нет такого формата")
        return
    title, text = FIT[key]
    if key == "gift":
        markup = certificate_keyboard()
    elif key == "company":
        markup = offers_keyboard("male")
    else:
        markup = nearest_halls_keyboard()
    await query.message.answer(f"<b>{html.escape(title)}</b>\n\n{html.escape(text)}", reply_markup=markup)
    await query.answer()


@router.callback_query(F.data == "faq")
async def on_faq_menu(query: CallbackQuery) -> None:
    assert query.message
    await query.message.answer("Коротко, до заявки.", reply_markup=faq_keyboard())
    await query.answer()


@router.callback_query(F.data.startswith("faq:"))
async def on_faq(query: CallbackQuery) -> None:
    assert query.data and query.message
    key = query.data.split(":", 1)[1]
    if key not in FAQ:
        await query.answer()
        return
    title, text = FAQ[key]
    await query.message.answer(
        f"<b>{html.escape(title)}</b>\n\n{html.escape(text)}",
        reply_markup=nearest_halls_keyboard(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("near:"))
async def on_near(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    hall = query.data.split(":", 1)[1]
    if hall == "pick":
        await query.message.answer(host_brief(now_msk()) + "\n\nКакой разряд?", reply_markup=nearest_halls_keyboard())
        await query.answer()
        return
    if hall not in HALLS:
        await query.answer("Нет такого разряда")
        return
    day, slot = nearest_entry(now_msk())
    await state.update_data(
        hall=hall,
        offer_title="Вход на 4 часа",
        hours=4,
        fixed_price=None,
        flat=False,
        guest_cap=8,
        certificate=False,
        date=day.isoformat(),
        start=slot.start,
        end=slot.end,
        price=slot.price,
        slot_label=slot.label,
    )
    await query.message.answer(
        f"<b>{html.escape(HALLS[hall]['title'])}</b>\n"
        f"{html.escape(format_day(day))}, {html.escape(slot.label)}\n"
        f"{html.escape(money(slot.price))} за взрослого, 4 часа.\n\n"
        "Сколько гостей?",
        reply_markup=guests_keyboard(8),
    )
    await query.answer()


@router.callback_query(F.data.startswith("cert:"))
async def on_cert(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    amount = int(query.data.split(":", 1)[1])
    today = now_msk().date()
    await state.update_data(
        hall="female",
        certificate=True,
        offer_title=f"Сертификат {money(amount)}",
        flat=True,
        guest_cap=1,
        guests=1,
        date=today.isoformat(),
        start="сертификат",
        end="в комплексе",
        price=amount,
        slot_label=f"Сертификат {money(amount)}",
        extra_title="",
    )
    await state.set_state(Book.name)
    await query.message.answer("Как зовут того, кому подарок?")
    await query.answer()


@router.callback_query(F.data.startswith("extra:"))
async def on_extra(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    key = query.data.split(":", 1)[1]
    found = next((item for item in UPSELLS if item[0] == key), None)
    if found is None:
        await query.answer()
        return
    _code, title, price = found
    await state.update_data(extra_title="" if price == 0 else title, extra_price=price)
    await state.set_state(Book.name)
    await query.message.answer("Как к вам обращаться? Имя и, если хотите, фамилия.")
    await query.answer()


@router.callback_query(F.data.startswith("book:"))
async def on_book(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    action = query.data.split(":", 1)[1]
    if action == "pick":
        await query.message.answer("Какой разряд и какой день?", reply_markup=book_halls_keyboard())
        await query.answer()
        return
    if action == "vip":
        from keyboards import vip_keyboard

        await query.message.answer("Какой VIP бронируем?", reply_markup=vip_keyboard())
        await query.answer()
        return
    if action == "cancel":
        await state.clear()
        await query.answer("Отменено")
        await query.message.answer("Черновик закрыт.", reply_markup=main_keyboard())
        return
    if action == "dates":
        data = await state.get_data()
        hall = data.get("hall")
        if hall not in HALLS:
            await query.answer("Сначала выберите разряд")
            return
        await begin_dates(query.message, state, hall)
        await query.answer()
        return
    if action == "send":
        await send_booking(query, state)
        return
    if action not in OFFERS:
        await query.answer("Неизвестный разряд")
        return
    from keyboards import offers_keyboard

    await state.update_data(hall=action)
    await query.message.answer(
        f"<b>{html.escape(HALLS[action]['title'])}</b>\nЧто бронируем?",
        reply_markup=offers_keyboard(action),
    )
    await query.answer()


@router.callback_query(F.data.startswith("offer:"))
async def on_offer(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    _, hall, offer_id = query.data.split(":")
    found = next((item for item in OFFERS.get(hall, []) if item[0] == offer_id), None)
    if found is None:
        await query.answer("Такого формата нет")
        return
    _oid, title, hours, fixed, cap = found
    await state.update_data(
        hall=hall,
        offer_title=title,
        hours=hours,
        fixed_price=fixed,
        flat=fixed is not None,
        guest_cap=cap,
    )
    await begin_dates(query.message, state, hall)
    await query.answer()


@router.callback_query(F.data.startswith("date:"))
async def on_date(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    day = date.fromisoformat(query.data.split(":", 1)[1])
    data = await state.get_data()
    slots = open_slots(
        day,
        now_msk(),
        hours=int(data.get("hours") or 4),
        fixed_price=data.get("fixed_price"),
    )
    if not slots:
        await query.answer("На этот день окна уже прошли")
        return
    await state.update_data(date=day.isoformat())
    labels = [f"{slot.label} · {money(slot.price)}" for slot in slots]
    await state.update_data(slot_labels=[slot.label for slot in slots], slot_prices=[slot.price for slot in slots], slot_starts=[slot.start for slot in slots], slot_ends=[slot.end for slot in slots])
    await query.message.answer(
        f"<b>{html.escape(format_day(day))}</b>\nВыберите окно входа.",
        reply_markup=slots_keyboard(labels),
    )
    await query.answer()


@router.callback_query(F.data.startswith("slot:"))
async def on_slot(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    index = int(query.data.split(":", 1)[1])
    data = await state.get_data()
    starts = data.get("slot_starts") or []
    if index < 0 or index >= len(starts):
        await query.answer("Это окно уже неактуально")
        return
    await state.update_data(start=starts[index], end=data["slot_ends"][index], price=data["slot_prices"][index], slot_label=data["slot_labels"][index])
    cap = int(data.get("guest_cap") or 8)
    await query.message.answer("Сколько гостей?", reply_markup=guests_keyboard(cap))
    await query.answer()


@router.callback_query(F.data.startswith("guests:"))
async def on_guests(query: CallbackQuery, state: FSMContext) -> None:
    assert query.data and query.message
    guests = int(query.data.split(":", 1)[1])
    if guests < 1 or guests > 12:
        await query.answer("Столько гостей сюда не поставить")
        return
    cap = int((await state.get_data()).get("guest_cap") or 8)
    if guests > cap:
        await query.answer(f"В этом формате до {cap} гостей")
        return
    await state.update_data(guests=guests)
    await query.message.answer(
        "Один жест к визиту. Цены из меню комплекса, можно пропустить.",
        reply_markup=upsell_keyboard(),
    )
    await query.answer()


@router.message(Book.name, F.text)
async def on_name(message: Message, state: FSMContext) -> None:
    name = clean_name(message.text or "")
    if not name:
        await message.answer("Напишите имя: от 2 до 40 букв, без ссылок.")
        return
    await state.update_data(guest_name=name)
    await state.set_state(Book.phone)
    await message.answer("Телефон для подтверждения. Можно в формате 8 925 000-00-00.")


@router.message(Book.phone, F.text)
async def on_phone(message: Message, state: FSMContext) -> None:
    phone = normalize_phone(message.text or "")
    if not phone:
        await message.answer("Не вижу номер. Нужен российский, 11 цифр.")
        return
    await state.update_data(phone=phone)
    await state.set_state(Book.confirm)
    data = await state.get_data()
    await message.answer(draft_text(data), reply_markup=confirm_keyboard())


@router.message(StateFilter(Book.confirm), F.text)
async def on_confirm_text(message: Message) -> None:
    await message.answer("Заявка ждёт кнопку «Отправить заявку» или «Отмена».")


async def send_booking(query: CallbackQuery, state: FSMContext) -> None:
    assert query.message
    data = await state.get_data()
    needed = ("hall", "date", "slot_label", "guests", "guest_name", "phone", "price")
    if any(key not in data for key in needed):
        await query.answer("Черновик закрыт. Начните заново")
        return
    user = query.from_user
    store.ensure_user(user.id, user.username, user.full_name or "Гость")
    if store.pending_count(user.id) >= PENDING_LIMIT:
        await query.answer("Уже три заявки в работе")
        await query.message.answer("Сначала дождитесь ответа по текущим заявкам или отмените одну из них.")
        return
    title, _about, _next, _floor = rank_for(store.user(user.id)["coals"])
    booking_id = store.create_booking(
        {
            "user_id": user.id,
            "hall": data["hall"],
            "visit_date": data["date"],
            "slot_label": _label_with_extra(data),
            "guests": int(data["guests"]),
            "guest_name": data["guest_name"],
            "phone": data["phone"],
            "price_each": int(data["price"]),
            "rank_title": title,
            "price_flat": 1 if data.get("flat") else 0,
        }
    )
    await state.clear()
    await query.answer("Заявка ушла")
    await query.message.answer(
        f"Заявка №{booking_id} у администратора.\n"
        "Когда место подтвердят, сюда придёт сообщение. До этого окно не занято.\n\n"
        "+12 угольков за заявку.\n\n"
        f"{ARRIVAL}",
        reply_markup=user_cancel_keyboard(booking_id),
    )
    await notify_admins(query.message, booking_id)


@router.callback_query(F.data.startswith("user:cancel:"))
async def on_user_cancel(query: CallbackQuery) -> None:
    assert query.data and query.message
    booking_id = int(query.data.rsplit(":", 1)[1])
    row = store.booking(booking_id)
    if row is None or row["user_id"] != query.from_user.id:
        await query.answer("Это не ваша заявка")
        return
    if row["status"] != "new":
        await query.answer("Эту заявку уже нельзя отменить кнопкой")
        return
    store.set_status(booking_id, "cancelled")
    await query.answer("Заявка отменена")
    await query.message.answer(f"Заявка №{booking_id} отменена. Угольки за неё сняты.")


@router.callback_query(F.data.startswith("adm:"))
async def on_admin(query: CallbackQuery) -> None:
    assert query.data and query.message
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Только для администратора")
        return
    _prefix, action, raw_id = query.data.split(":")
    booking_id = int(raw_id)
    row = store.booking(booking_id)
    if row is None:
        await query.answer("Заявка не найдена")
        return
    if action == "ok":
        if row["status"] != "new":
            await query.answer("Уже обработана")
            return
        updated = store.set_status(booking_id, "confirmed")
        if updated is None or updated["status"] != "confirmed":
            await query.answer("Уже обработана")
            return
        await query.message.edit_reply_markup(reply_markup=admin_keyboard(booking_id, "confirmed"))
        await query.message.answer(f"Заявка №{booking_id} подтверждена.")
        try:
            await query.bot.send_message(
                row["user_id"],
                f"Заявка №{booking_id} подтверждена.\n\n"
                f"{html.escape(HALLS[row['hall']]['title'])}\n"
                f"{html.escape(format_day(date.fromisoformat(row['visit_date'])))}\n"
                f"{html.escape(row['slot_label'])}\n"
                f"Гостей: {row['guests']}\n\n"
                "Ждём вас. Длительность — как в заявке, с момента входа в это окно.\n"
                "+40 угольков, визит зачтён.",
            )
        except Exception:
            await query.message.answer("Гостю не удалось написать — возможно, он закрыл бота.")
        await query.answer("Подтверждено")
        return
    if action == "no":
        if row["status"] != "new":
            await query.answer("Уже обработана")
            return
        updated = store.set_status(booking_id, "declined")
        if updated is None or updated["status"] != "declined":
            await query.answer("Уже обработана")
            return
        await query.message.edit_reply_markup(reply_markup=None)
        try:
            await query.bot.send_message(
                row["user_id"],
                f"По заявке №{booking_id} места нет.\n"
                "Выберите другое окно через «Забронировать». Угольки за эту заявку сняты.",
            )
        except Exception:
            pass
        await query.answer("Гостю отправили отказ")
        return
    if action == "miss":
        if row["status"] != "confirmed":
            await query.answer("Визит уже не в статусе подтверждён")
            return
        updated = store.set_status(booking_id, "missed")
        if updated is None or updated["status"] != "missed":
            await query.answer("Визит уже не в статусе подтверждён")
            return
        await query.message.edit_reply_markup(reply_markup=None)
        await query.answer("Визит снят")
        try:
            await query.bot.send_message(
                row["user_id"],
                f"Визит по заявке №{booking_id} не зачтён. Угольки за подтверждение сняты.",
            )
        except Exception:
            pass


@router.message(F.text)
async def fallback(message: Message) -> None:
    await message.answer("Нажмите кнопку внизу — или /menu, если клавиатура спряталась.", reply_markup=main_keyboard())
