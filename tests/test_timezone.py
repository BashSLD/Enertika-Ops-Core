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
