import pytest
from fastapi import HTTPException
from booking_time import instant, window, day_window


def test_equivalent_offsets_have_identical_storage():
    venue = {'timezone': 'Australia/Melbourne'}
    assert window(venue, '2027-01-10T18:00:00') == window(venue, '2027-01-10T07:00:00Z')


@pytest.mark.parametrize('value', ['2026-10-04T02:30:00', '2026-04-05T02:30:00', 'not-a-time', '2026-04-05'])
def test_invalid_nonexistent_or_ambiguous_local_time_fails(value):
    with pytest.raises(HTTPException) as exc:
        instant(value, 'Australia/Melbourne')
    assert exc.value.status_code == 422


def test_dst_overlap_can_be_disambiguated_with_offset():
    assert instant('2026-04-05T02:30:00+11:00', 'Australia/Melbourne') != instant(
        '2026-04-05T02:30:00+10:00', 'Australia/Melbourne')


def test_end_before_start_is_rejected():
    with pytest.raises(HTTPException):
        window({'timezone': 'UTC'}, '2027-01-10T18:00:00Z', '2027-01-10T17:00:00Z')


def test_local_date_filter_uses_dst_day_boundaries():
    begin, end = day_window({'timezone': 'Australia/Melbourne'}, '2026-10-04')
    from datetime import datetime
    assert (datetime.fromisoformat(end) - datetime.fromisoformat(begin)).total_seconds() == 23 * 3600
