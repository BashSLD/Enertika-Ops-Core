import pathlib
from datetime import date, datetime
from zoneinfo import ZoneInfo


def test_today_mx_returns_date():
    from core.timezone import today_mx
    result = today_mx()
    assert isinstance(result, date)
    assert not isinstance(result, datetime)


def test_now_mx_returns_aware_datetime():
    from core.timezone import now_mx
    result = now_mx()
    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    assert str(result.tzinfo) == "America/Mexico_City"


def test_today_mx_matches_mexico_city():
    from core.timezone import today_mx, now_mx
    mx_now = now_mx()
    mx_today = today_mx()
    assert mx_today == mx_now.date()


def test_no_naive_date_today():
    """date.today() devuelve fecha UTC en Railway — usar today_mx() de core/timezone.py."""
    violations = []
    for root in ("modules", "core"):
        for path in pathlib.Path(root).rglob("*.py"):
            if path.name == "timezone.py":
                continue
            if "date.today()" in path.read_text(encoding="utf-8"):
                violations.append(str(path))
    assert violations == [], f"Usar today_mx() en lugar de date.today() en: {violations}"


def test_no_toISOString_in_templates():
    """toISOString() devuelve fecha UTC — usar toLocalISO inline en templates."""
    violations = []
    for path in pathlib.Path("templates").rglob("*.html"):
        if "toISOString()" in path.read_text(encoding="utf-8"):
            violations.append(str(path))
    assert violations == [], f"Usar toLocalISO() en lugar de toISOString() en: {violations}"
