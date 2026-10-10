"""Точка входа бота «Живой жар»."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import handlers
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
    dispatcher.include_router(handlers.router)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть бота"),
            BotCommand(command="menu", description="Показать клавиатуру"),
            BotCommand(command="cancel", description="Закрыть черновик брони"),
            BotCommand(command="whoami", description="Узнать свой Telegram id"),
            BotCommand(command="admin", description="Новые заявки"),
        ]
    )
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run())
