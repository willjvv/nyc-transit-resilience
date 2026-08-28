"""Time semantics for MTA GTFS/GTFS-realtime reconciliation.

GTFS schedule times are service-day times: a trip operating at 01:15 local time
can be encoded as 25:15:00, meaning 01:15 on the calendar day after the service
started. Reconciliation must therefore compare realtime Unix timestamps after
converting them to America/New_York wall-clock time and candidate service dates.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
SECONDS_PER_DAY = 24 * 60 * 60


def parse_gtfs_time(value: str | int | float | None) -> int | None:
    """Convert HH:MM:SS GTFS time, including hour >= 24, to service seconds."""
    if value is None:
        return None
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(float(p)) for p in parts)
    except ValueError:
        return None
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def unix_to_local(timestamp: int | float) -> datetime:
    """Convert Unix timestamp to an America/New_York aware datetime."""
    return datetime.fromtimestamp(float(timestamp), tz=ZoneInfo("UTC")).astimezone(NY_TZ)


def service_date_candidates(timestamp: int | float) -> list[tuple[str, int]]:
    """Return possible (service_date, service_seconds) pairs for a realtime timestamp.

    A local timestamp before midnight can belong to the same service date.
    A local timestamp after midnight can also belong to the previous service date,
    represented using GTFS's >24:00 convention.
    """
    local = unix_to_local(timestamp)
    seconds = (
        local.hour * 3600
        + local.minute * 60
        + local.second
        + local.microsecond // 1_000_000
    )
    current = local.date()
    previous = current - timedelta(days=1)
    return [
        (current.isoformat(), seconds),
        (previous.isoformat(), seconds + SECONDS_PER_DAY),
    ]


def service_date_from_gtfs_date(value: str | None) -> str | None:
    """Normalize GTFS trip.start_date (YYYYMMDD) to YYYY-MM-DD."""
    if not value:
        return None
    text = str(value)
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def local_date_from_unix(timestamp: int | float) -> str:
    return unix_to_local(timestamp).date().isoformat()


def local_hour_from_service_seconds(seconds: int | float | None) -> int | None:
    if seconds is None:
        return None
    return int(seconds) // 3600 % 24
