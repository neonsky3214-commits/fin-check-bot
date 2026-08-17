"""Анализ отчётов через Claude API: распознавание и проверка арифметики."""
import json
import logging
import os

from anthropic import AsyncAnthropic

log = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client

CHECK_SYSTEM = """Ты — внимательный финансовый контролёр. Тебе присылают сообщения из рабочего чата.

Задача:
1. Определи, является ли сообщение финансовым отчётом — то есть содержит статьи с суммами (расходы, доходы, выручка, касса и т.п.). Просто упоминание денег в разговоре — НЕ отчёт.
2. Если это отчёт — тщательно пересчитай ВСЮ арифметику: сложи статьи и сравни с заявленными итогами, проверь разности (остаток = приход − расход), проценты, промежуточные суммы. Считай аккуратно, столбиком.
3. Каждое найденное расхождение опиши конкретно: что заявлено и что получается при пересчёте.

Отвечай СТРОГО одним JSON-объектом без пояснений вокруг:
{
  "is_report": true/false,
  "has_errors": true/false,
  "errors": ["описание расхождения по-русски", ...],
  "total": число или null,  // главный итог отчёта, если есть
  "summary": "одна строка: о чём отчёт и его итог"
}
Если is_report=false, остальные поля: has_errors=false, errors=[], total=null, summary=""."""

SUMMARY_SYSTEM = """Ты — финансовый аналитик. Тебе дают список финансовых отчётов из рабочего чата за период (дата, автор, итог, краткое содержание, найденные ошибки).

Составь краткую сводку по-русски для руководителя:
- сколько отчётов и от кого;
- общие суммы/динамика, если складываются;
- в каких отчётах были арифметические ошибки;
- что бросается в глаза.

Пиши обычным текстом (без markdown-заголовков), компактно, до 15 строк."""


async def check_report(text: str) -> dict | None:
    """Возвращает dict с результатом проверки или None при ошибке API."""
    try:
        resp = await _get_client().messages.create(
            model=MODEL,
            max_tokens=1500,
            system=CHECK_SYSTEM,
            messages=[
                {"role": "user", "content": text},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + resp.content[0].text
        return json.loads(raw)
    except Exception:
        log.exception("Ошибка при проверке отчёта")
        return None


async def make_summary(reports: list[dict], period_label: str) -> str | None:
    lines = []
    for r in reports:
        errors = json.loads(r["errors_json"]) if r["errors_json"] else []
        err_part = f" | ошибки: {'; '.join(errors)}" if errors else ""
        total_part = f" | итог: {r['total']}" if r["total"] is not None else ""
        lines.append(f"{r['date']} | {r['user_name']} | {r['summary']}{total_part}{err_part}")
    payload = f"Период: {period_label}\nОтчёты:\n" + "\n".join(lines)
    try:
        resp = await _get_client().messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": payload}],
        )
        return resp.content[0].text
    except Exception:
        log.exception("Ошибка при формировании сводки")
        return None
