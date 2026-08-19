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
    "Ещё я умею:\n"
    "• сравнивать выручку с прошлыми сменами;\n"
    "• сверять кассу с прошлой сменой (касса + нал − расходы − сейф);\n"
    "• напоминать в 12:00, если отчёт за смену не сдан;\n"
    "• присылать сводку сам: по понедельникам в 10:00 и 1-го числа за месяц.\n\n"
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


_CHATS = {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.PRIVATE}


async def _process(message: Message, text: str) -> None:
    if not looks_like_report(text):
        log.info("Фильтр отклонил сообщение: %r", text[:80])
        return
    log.info("Сообщение похоже на отчёт, отправляю на проверку: %r", text[:80])
    result = await check_report(text)
    if result is None:
        await message.reply(
            "⚙️ Не смог проверить это сообщение — техническая ошибка. "
            "Отправьте отчёт ещё раз."
        )
        return
    if not result.get("is_report"):
        return
    log.info("Отчёт распознан, сохраняю. Ошибки: %s", result.get("errors"))
    user = message.from_user.full_name if message.from_user else "неизвестно"
    previous = db.get_previous_reports(message.chat.id, message.message_id)
    db.save_report(message.chat.id, message.message_id, user, text, result)
    extra = (_format_recount(result)
             + _format_comparison(result, previous)
             + _format_cash_check(result, previous))
    if result.get("has_errors"):
        errors = "\n".join(f"• {e}" for e in result.get("errors") or [])
        await message.reply(f"⚠️ Нашёл расхождения в отчёте:\n{errors}{extra}")
    else:
        await message.reply(f"✅ Проверил: суммы сходятся.{extra}")


def _fmt_money(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def _format_recount(result: dict) -> str:
    income, expenses = result.get("income"), result.get("expenses")
    parts = []
    if income is not None:
        parts.append(f"доходы {_fmt_money(income)} ₽")
    if expenses is not None:
        parts.append(f"расходы {_fmt_money(expenses)} ₽")
    if income is not None and expenses is not None:
        parts.append(f"разница {_fmt_money(income - expenses)} ₽")
    if not parts:
        return ""
    return "\n\n📊 Мой пересчёт: " + ", ".join(parts) + "."


def _format_comparison(result: dict, previous: list[dict]) -> str:
    """Сравнение выручки с прошлой сменой и средним по последним сменам."""
    total = result.get("total")
    if not total:
        return ""
    prev_totals = [r["total"] for r in previous if r.get("total")]
    if not prev_totals:
        return ""
    parts = []
    last = prev_totals[0]
    if last:
        change = (total - last) / last * 100
        parts.append(f"{change:+.0f}% к прошлой смене")
    if len(prev_totals) >= 3:
        avg = sum(prev_totals) / len(prev_totals)
        change = (total - avg) / avg * 100
        parts.append(f"{change:+.0f}% к среднему за последние "
                     f"{len(prev_totals)} смен")
    if not parts:
        return ""
    return "\n📈 Выручка: " + ", ".join(parts) + "."


def _format_cash_check(result: dict, previous: list[dict]) -> str:
    """Мягкая сверка кассы: касса вчера + нал − расходы − сейф = касса сегодня."""
    kassa, cash = result.get("kassa"), result.get("cash")
    if kassa is None or cash is None:
        return ""
    prev = next((r for r in previous if r.get("kassa") is not None), None)
    if prev is None:
        return ""
    expected = (prev["kassa"] + cash - (result.get("expenses") or 0)
                - (result.get("safe") or 0))
    diff = kassa - expected
    if abs(diff) < 50:
        return ""
    sign = "больше" if diff > 0 else "меньше"
    return (f"\n💰 Касса: по расчёту от прошлой смены ожидал "
            f"{_fmt_money(expected)} ₽ (касса {_fmt_money(prev['kassa'])} + "
            f"нал − расходы − сейф), в отчёте {_fmt_money(kassa)} ₽ — "
            f"на {_fmt_money(abs(diff))} ₽ {sign}. "
            f"Было изъятие, размен или инкассация?")


@dp.message(F.text, F.chat.type.in_(_CHATS))
async def on_text(message: Message) -> None:
    await _process(message, message.text or "")


@dp.message(F.caption, F.chat.type.in_(_CHATS))
async def on_caption(message: Message) -> None:
    await _process(message, message.caption or "")


@dp.edited_message(F.text | F.caption, F.chat.type.in_(_CHATS))
async def on_edited(message: Message) -> None:
    await _process(message, message.text or message.caption or "")


@dp.message()
async def on_other(message: Message) -> None:
    log.info("Сообщение без текста, пропускаю: type=%s", message.content_type)


REMIND_HOUR = 12      # дедлайн отчёта за смену
DIGEST_HOUR = 10      # час отправки автосводок
DIGEST_WEEKDAY = 0    # понедельник — недельная сводка


async def _send_digest(bot: Bot, chat_id: int, days: int, label: str) -> None:
    reports = db.get_reports(chat_id, days)
    if not reports:
        return
    summary = await make_summary(reports, label)
    if summary:
        await bot.send_message(chat_id, f"📊 Сводка {label}:\n\n{summary}")


async def scheduler(bot: Bot) -> None:
    """Раз в минуту: напоминания о несданных отчётах и автосводки."""
    from datetime import timedelta
    while True:
        try:
            now = db.now()
            today = now.strftime("%Y-%m-%d")
            for chat_id in db.get_active_chats():
                if (now.hour >= REMIND_HOUR
                        and not db.has_report_since(chat_id,
                                                    now - timedelta(hours=24))
                        and db.try_mark_sent("remind", chat_id, today)):
                    await bot.send_message(
                        chat_id,
                        "⏰ Отчёт за вчерашнюю смену ещё не сдан. "
                        "Пришлите его в чат — я проверю.")
                if (now.weekday() == DIGEST_WEEKDAY
                        and now.hour >= DIGEST_HOUR
                        and db.try_mark_sent("weekly", chat_id, today)):
                    await _send_digest(bot, chat_id, 7, "за неделю")
                if (now.day == 1 and now.hour >= DIGEST_HOUR
                        and db.try_mark_sent("monthly", chat_id, today)):
                    await _send_digest(bot, chat_id, 30, "за месяц")
        except Exception:
            log.exception("Ошибка в планировщике")
        await asyncio.sleep(60)


async def main() -> None:
    token = os.environ["BOT_TOKEN"]
    db.init_db()
    bot = Bot(token)
    asyncio.create_task(scheduler(bot))
    log.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
