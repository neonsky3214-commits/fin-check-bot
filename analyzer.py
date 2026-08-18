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


def _text(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

CHECK_SYSTEM = """Ты — внимательный финансовый контролёр. Тебе присылают сообщения из рабочего чата.

Задача:
1. Определи, является ли сообщение финансовым отчётом — то есть содержит статьи с суммами (расходы, доходы, выручка, касса и т.п.). Просто упоминание денег в разговоре — НЕ отчёт.
2. Если это отчёт — тщательно пересчитай ВСЮ арифметику: сложи статьи и сравни с заявленными итогами, проверь разности (остаток = приход − расход), проценты, промежуточные суммы. Считай аккуратно, столбиком.
3. Каждое найденное расхождение опиши конкретно: что заявлено и что получается при пересчёте.

Правила учёта в этом бизнесе:
- Суммы, положенные в сейф («Сейф», «в сейф», «сдали в сейф» и т.п.) — это НЕ расход, а перемещение наличных на хранение. НИКОГДА не включай их в expenses и не называй расходом.
- При проверке остатка наличных/кассы учитывай сейф как отдельное движение: наличные уменьшаются и на расходы, и на сумму, убранную в сейф.
- Если в отчёте касса/остаток не сходится, но расхождение ровно равно сумме сейфа — вероятно, автор просто не вычел/прибавил сейф; укажи это прямо.

Отвечай СТРОГО одним JSON-объектом без пояснений вокруг:
{
  "is_report": true/false,
  "has_errors": true/false,
  "errors": ["описание расхождения по-русски", ...],
  "total": число или null,  // главный итог отчёта, если есть
  "income": число или null,  // сумма ВСЕХ доходов/выручки, посчитанная тобой самостоятельно по статьям
  "expenses": число или null,  // сумма ВСЕХ расходов, посчитанная тобой самостоятельно по статьям
  "summary": "одна строка: о чём отчёт и его итог"
}
Если is_report=false, остальные поля: has_errors=false, errors=[], total=null, income=null, expenses=null, summary=""."""

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
            max_tokens=8000,
            system=CHECK_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = _text(resp)
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"В ответе модели нет JSON: {raw[:200]}")
        return json.loads(raw[start:end + 1])
    except Exception:
        log.exception("Ошибка при проверке отчёта")
        return None


async def make_summary(reports: list[dict], period_label: str) -> str | None:
    lines = []
    for r in reports:
        errors = json.loads(r["errors_json"]) if r["errors_json"] else []
        err_part = f" | ошибки: {'; '.join(errors)}" if errors else ""
        total_part = f" | итог: {r['total']}" if r["total"] is not None else ""
        inc = r.get("income")
        exp = r.get("expenses")
        money_part = ""
        if inc is not None or exp is not None:
            money_part = f" | доходы: {inc}, расходы: {exp}"
        lines.append(f"{r['date']} | {r['user_name']} | {r['summary']}"
                     f"{total_part}{money_part}{err_part}")
    payload = f"Период: {period_label}\nОтчёты:\n" + "\n".join(lines)
    try:
        resp = await _get_client().messages.create(
            model=MODEL,
            max_tokens=6000,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": payload}],
        )
        return _text(resp)
    except Exception:
        log.exception("Ошибка при формировании сводки")
        return None
