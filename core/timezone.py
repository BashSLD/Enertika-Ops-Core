from datetime import date, datetime
from zoneinfo import ZoneInfo

_MX = ZoneInfo("America/Mexico_City")


def today_mx() -> date:
    return datetime.now(_MX).date()


def now_mx() -> datetime:
    return datetime.now(_MX)
