import importlib
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
os.environ.setdefault("BOT_TOKEN", "1:x")

from main import _format_cash_check, _format_comparison


def _report(**kw):
    base = {"total": None, "income": None, "expenses": None,
            "cash": None, "kassa": None, "safe": None}
    base.update(kw)
    return base


class TestComparison:
    def test_no_previous_reports(self):
        assert _format_comparison(_report(total=100_000), []) == ""

    def test_change_vs_last_shift(self):
        prev = [_report(total=80_000)]
        out = _format_comparison(_report(total=88_000), prev)
        assert "+10% к прошлой смене" in out

    def test_average_needs_three_shifts(self):
        prev = [_report(total=100_000), _report(total=100_000)]
        out = _format_comparison(_report(total=110_000), prev)
        assert "к среднему" not in out
        prev.append(_report(total=100_000))
        out = _format_comparison(_report(total=110_000), prev)
        assert "+10% к среднему за последние 3 смен" in out


class TestCashCheck:
    def test_matches_expected(self):
        prev = [_report(kassa=33_490)]
        cur = _report(kassa=33_490 + 21_690 - 8_850 - 4_500,
                      cash=21_690, expenses=8_850, safe=4_500)
        assert _format_cash_check(cur, prev) == ""

    def test_mismatch_asks_question(self):
        prev = [_report(kassa=33_490)]
        cur = _report(kassa=50_000, cash=21_690, expenses=8_850, safe=4_500)
        out = _format_cash_check(cur, prev)
        assert "Было изъятие" in out
        assert "41 830" in out  # ожидаемая касса

    def test_no_kassa_in_previous(self):
        prev = [_report(kassa=None)]
        cur = _report(kassa=10_000, cash=5_000)
        assert _format_cash_check(cur, prev) == ""


class TestSchedulingDb:
    def _fresh_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import db
        importlib.reload(db)
        db.init_db()
        return db

    def test_active_chats_and_has_report_since(self, tmp_path, monkeypatch):
        db = self._fresh_db(tmp_path, monkeypatch)
        db.save_report(-1001, 1, "A", "t", {"has_errors": False})
        assert db.get_active_chats() == [-1001]
        assert db.has_report_since(-1001, db.now() - timedelta(hours=1))
        assert not db.has_report_since(-1001, db.now() + timedelta(hours=1))

    def test_mark_sent_once_per_day(self, tmp_path, monkeypatch):
        db = self._fresh_db(tmp_path, monkeypatch)
        assert db.try_mark_sent("remind", -1001, "2026-08-19")
        assert not db.try_mark_sent("remind", -1001, "2026-08-19")
        assert db.try_mark_sent("remind", -1001, "2026-08-20")
        assert db.try_mark_sent("weekly", -1001, "2026-08-19")

    def test_previous_reports_excludes_current(self, tmp_path, monkeypatch):
        db = self._fresh_db(tmp_path, monkeypatch)
        db.save_report(-1001, 1, "A", "t1", {"has_errors": False, "total": 100})
        db.save_report(-1001, 2, "A", "t2", {"has_errors": False, "total": 200})
        prev = db.get_previous_reports(-1001, exclude_message_id=2)
        assert [r["total"] for r in prev] == [100]
