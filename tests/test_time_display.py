from datetime import datetime, timezone

from cleardebt.time_display import format_beijing, iso_beijing


def test_sonar_utc_timestamp_displays_in_beijing():
    assert format_beijing("2026-09-26T10:19:28+0000") == "2026-09-26 18:19"
    assert iso_beijing("2026-09-26T10:19:28+0000") == "2026-09-26T18:19:28+08:00"


def test_database_timestamp_displays_in_beijing():
    stamp = datetime(2026, 9, 26, 10, 19, tzinfo=timezone.utc)
    assert format_beijing(stamp) == "2026-09-26 18:19"
