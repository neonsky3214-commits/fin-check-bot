"""Быстрый локальный фильтр: похоже ли сообщение на финансовый отчёт.

Отсекает обычную болтовню до обращения к Claude API.
"""
import re

FIN_KEYWORDS = [
    "итог", "итого", "расход", "доход", "выручк", "прибыл", "затрат",
    "бюджет", "руб", "₽", "оплат", "касс", "продаж", "отчет", "отчёт",
    "остаток", "аванс", "зарплат", "себестоим", "налог", "сумм", "смен",
    "выплат", "долг", "аренд", "закуп", "приход", "баланс", "оборот",
]

_NUMBER_RE = re.compile(r"\d[\d\s]*(?:[.,]\d+)?")


def looks_like_report(text: str) -> bool:
    if not text or len(text) < 20:
        return False
    numbers = _NUMBER_RE.findall(text)
    if len(numbers) < 2:
        return False
    lowered = text.lower()
    return any(kw in lowered for kw in FIN_KEYWORDS)
