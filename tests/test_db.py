import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import db
    importlib.reload(db)
    db.init_db()
    return db


def test_save_and_get_report(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    result = {
        "is_report": True,
        "has_errors": True,
        "errors": ["Итого заявлено 100, по пересчёту 110"],
        "total": 100,
        "summary": "Отчёт за смену",
    }
    db.save_report(-1001, 42, "Иван", "текст отчёта", result)
    reports = db.get_reports(-1001, days=7)
    assert len(reports) == 1
    assert reports[0]["user_name"] == "Иван"
    assert reports[0]["total"] == 100
    assert reports[0]["has_errors"] == 1


def test_other_chat_not_returned(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    result = {"has_errors": False, "errors": [], "total": 5, "summary": "x"}
    db.save_report(-1001, 1, "A", "t", result)
    assert db.get_reports(-2002, days=7) == []
