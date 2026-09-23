"""When automated backlog remediation should run."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_AUTOMATION = {
    "enabled": True,
    "frequency": "daily",
    "weekday": 0,
    "hour": 8,
    "minute": 0,
    "timezone": "Asia/Shanghai",
    "pause_when_open_mrs": None,
}


def normalize_automation(raw) -> dict:
    data = dict(DEFAULT_AUTOMATION)
    if isinstance(raw, dict):
        data.update({key: raw[key] for key in DEFAULT_AUTOMATION if key in raw})
    frequency = str(data.get("frequency") or "daily").lower()
    if frequency not in {"daily", "weekly"}:
        frequency = "daily"
    data["frequency"] = frequency
    data["enabled"] = bool(data.get("enabled", True))
    try:
        data["weekday"] = int(data.get("weekday") or 0) % 7
    except (TypeError, ValueError):
        data["weekday"] = 0
    try:
        data["hour"] = max(0, min(23, int(data.get("hour") if data.get("hour") is not None else 8)))
    except (TypeError, ValueError):
        data["hour"] = 8
    try:
        data["minute"] = max(0, min(59, int(data.get("minute") if data.get("minute") is not None else 0)))
    except (TypeError, ValueError):
        data["minute"] = 0
    tz = str(data.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    data["timezone"] = tz
    pause = data.get("pause_when_open_mrs")
    if pause in ("", None):
        data["pause_when_open_mrs"] = None
    else:
        try:
            data["pause_when_open_mrs"] = max(1, int(pause))
        except (TypeError, ValueError):
            data["pause_when_open_mrs"] = None
    return data


def schedule_due(automation: dict, now: datetime | None = None) -> bool:
    """True when local time matches the configured daily/weekly slot within the same minute."""
    settings = normalize_automation(automation)
    if not settings["enabled"]:
        return False
    try:
        zone = ZoneInfo(settings["timezone"])
    except Exception:
        zone = ZoneInfo("Asia/Shanghai")
    local = (now or datetime.now(tz=zone)).astimezone(zone)
    if local.hour != settings["hour"] or local.minute != settings["minute"]:
        return False
    if settings["frequency"] == "weekly" and local.weekday() != settings["weekday"]:
        return False
    return True


def schedule_skip_reason(automation: dict, now: datetime | None = None) -> str | None:
    settings = normalize_automation(automation)
    if not settings["enabled"]:
        return "定时清 backlog 关掉了。"
    if schedule_due(settings, now):
        return None
    when = f"{settings['hour']:02d}:{settings['minute']:02d}"
    if settings["frequency"] == "weekly":
        return f"未到设定时间（每周 weekday={settings['weekday']} {when} {settings['timezone']}）。"
    return f"未到设定时间（每天 {when} {settings['timezone']}）。"
