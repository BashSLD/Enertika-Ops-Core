from datetime import date, datetime
from zoneinfo import ZoneInfo

_MX = ZoneInfo("America/Mexico_City")
MX_TZ = _MX


def today_mx() -> date:
    return datetime.now(_MX).date()


def now_mx() -> datetime:
    return datetime.now(_MX)


def ensure_mx(dt: datetime) -> datetime:
    """Garantiza tzinfo MX: un naive se asume ya en hora local MX (nunca UTC implicito)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MX_TZ)
    return dt.astimezone(MX_TZ)


def fmt_time_mx(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.astimezone(_MX).strftime("%H:%M")
