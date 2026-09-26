"""Beijing time formatting for timestamps shown in the operator console."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")


def beijing_datetime(value: datetime | str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        # Database timestamps and Sonar analysis dates carry an offset. Treat any
        # offset-free machine timestamp as UTC rather than using the host timezone.
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(BEIJING)
    except ValueError:
        return None


def format_beijing(value: datetime | str | None) -> str:
    stamp = beijing_datetime(value)
    return stamp.strftime("%Y-%m-%d %H:%M") if stamp else ""


def iso_beijing(value: datetime | str | None) -> str:
    stamp = beijing_datetime(value)
    return stamp.isoformat() if stamp else ""
