from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_kst() -> date:
    return datetime.now(KST).date()


def to_kst_date(dt: datetime) -> date:
    """DB에서 읽은 naive(UTC) / aware datetime 모두 KST 날짜로 변환"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).date()
