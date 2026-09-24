"""Canonical UTC instants with strict venue-local daylight-saving handling."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException


def instant(value: str, timezone_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        zone = ZoneInfo(timezone_name)
        if 'T' not in value or len(value) < 16:
            raise ValueError('Time is required')
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
        candidates = {
            parsed.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            for fold in (0, 1)
            if parsed.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            .astimezone(zone).replace(tzinfo=None) == parsed
        }
        if len(candidates) != 1:
            raise ValueError('Local time is ambiguous or does not exist; provide an explicit UTC offset')
        return candidates.pop()
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(422, f'Invalid booking time: {exc}') from exc


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


def window(venue: dict, start: str, end: str | None = None):
    zone = venue.get('timezone', 'Australia/Sydney')
    begin = instant(start, zone)
    finish = instant(end, zone) if end else begin + timedelta(minutes=venue.get('default_duration_minutes', 90))
    if finish <= begin or finish - begin > timedelta(days=7):
        raise HTTPException(422, 'Booking end must be after start and within seven days')
    return stamp(begin), stamp(finish)


def day_window(venue: dict, date: str):
    try:
        day = datetime.strptime(date, '%Y-%m-%d')
    except ValueError as exc:
        raise HTTPException(422, 'Date must be YYYY-MM-DD') from exc
    zone = venue.get('timezone', 'Australia/Sydney')
    return (stamp(instant(day.isoformat(), zone)),
            stamp(instant((day + timedelta(days=1)).isoformat(), zone)))
