"""Fin-Check Bot: проверяет арифметику финансовых отчётов в чате."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import db
from analyzer import check_report, make_summary
from filters import looks_like_report

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

dp = Dispatcher()

PERIODS = {
    "день": (1, "за сегодня и вчера"),
    "неделя": (7, "за неделю"),
    "месяц": (30, "за месяц"),
}

HELP_TEXT = (
    "Я проверяю финансовые отчёты в этом чате.\n\n"
    "Просто пишите отчёты текстом — я сам их замечу, пересчитаю все суммы "
    "и отвечу, сходится ли арифметика.\n\n"
    "Команды:\n"
    "/svodka — сводка по отчётам за неделю\n"
    "/svodka день | неделя | месяц — сводка за период\n"
    "/help — эта справка"
)


@dp.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await message.reply(HELP_TEXT)


@dp.message(Command("svodka"))
async def cmd_svodka(message: Message, command: CommandObject) -> None:
    arg = (command.args or "неделя").strip().lower()
    days, label = PERIODS.get(arg, PERIODS["неделя"])
    reports = db.get_reports(message.chat.id, days)
    if not reports:
        await message.reply(f"Отчётов {label} в этом чате не нашёл.")
        return
    note = await message.reply(f"Собираю сводку по {len(reports)} отчётам…")
    summary = await make_summary(reports, label)
    if summary is None:
        await note.edit_text("Не получилось собрать сводку, попробуйте позже.")
        return
    await note.edit_text(f"📊 Сводка {label}:\n\n{summary}")


@dp.message(F.text, F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP,
                                     ChatType.PRIVATE}))
async def on_text(message: Message) -> None:
    text = message.text or ""
    if not looks_like_report(text):
        log.info("Фильтр отклонил сообщение: %r", text[:80])
        return
    log.info("Сообщение похоже на отчёт, отправляю на проверку: %r", text[:80])
    result = await check_report(text)
    if result is None or not result.get("is_report"):
        return
    user = message.from_user.full_name if message.from_user else "неизвестно"
    db.save_report(message.chat.id, message.message_id, user, text, result)
    if result.get("has_errors"):
        errors = "\n".join(f"• {e}" for e in result.get("errors") or [])
        await message.reply(f"⚠️ Нашёл расхождения в отчёте:\n{errors}")
    else:
        await message.reply("✅ Проверил: суммы сходятся.")


async def main() -> None:
    token = os.environ["BOT_TOKEN"]
    db.init_db()
    bot = Bot(token)
    log.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
