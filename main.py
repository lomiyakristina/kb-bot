"""Точка входа бота «Живой жар»."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonWebApp,
    WebAppInfo,
)

import handlers
import webapp
from storage import Storage

ROOT = Path(__file__).resolve().parent


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


def admin_ids() -> set[int]:
    raw = os.environ.get("ADMIN_IDS", "")
    found = set()
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            found.add(int(part))
    return found


async def run() -> None:
    load_env()
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token or "сюда" in token:
        raise SystemExit("Создайте .env из .env.example и вставьте токен BotFather в BOT_TOKEN.")
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher(storage=MemoryStorage())
    handlers.setup(Storage(), admin_ids())
    handlers.store.refresh_ledger()
    dispatcher.include_router(handlers.router)
    guest_commands = [
        BotCommand(command="start", description="Старт"),
    ]
    await bot.set_my_commands(guest_commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(guest_commands, scope=BotCommandScopeAllPrivateChats())
    admin_commands = [
        BotCommand(command="start", description="Старт"),
        BotCommand(command="guests", description="Кто нажал Старт"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="table", description="Таблица гостей"),
        BotCommand(command="broadcast", description="Рассылка"),
        BotCommand(command="admin", description="Новые заявки"),
    ]
    for admin_id in admin_ids():
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            continue
    url = os.environ.get("WEBAPP_URL", "").strip()
    if url.startswith("https://"):
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Залы", web_app=WebAppInfo(url=url))
            )
        except Exception:
            pass
    runner = None
    try:
        runner = await webapp.start_web(bot, handlers.store, admin_ids())
    except Exception as exc:
        print(f"Мини-приложение не запустилось: {exc}")
    try:
        await dispatcher.start_polling(bot)
    finally:
        if runner is not None:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run())
