import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filters import looks_like_report


def test_report_with_totals_passes():
    text = (
        "Отчёт за смену:\n"
        "Выручка 45 000 руб\n"
        "Расходы 12 500 руб\n"
        "Итого: 32 500 руб"
    )
    assert looks_like_report(text)


def test_small_talk_rejected():
    assert not looks_like_report("Привет, как дела?")


def test_single_number_rejected():
    assert not looks_like_report("Встречаемся завтра в 15:00 около входа")


def test_numbers_without_finance_words_rejected():
    assert not looks_like_report(
        "Вчера пришло 120 человек, а сегодня уже 340, отличная динамика"
    )


def test_short_text_rejected():
    assert not looks_like_report("итого 5 и 6")
