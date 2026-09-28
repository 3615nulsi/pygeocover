from datetime import datetime, timedelta, timezone

from pygeocover.models import (
    BatteryState, Bike, BikeState, Health, Ride, format_datetime, parse_datetime,
)

from .conftest import BATTERY, BIKE, HEALTH, STATE, ride


def test_parse_datetime_formats():
    expected = datetime(2026, 9, 28, 6, 25, 36, tzinfo=timezone.utc)
    assert parse_datetime("2026-09-28T06:25:36+0000") == expected
    assert parse_datetime("2026-09-28T06:25:36+00:00") == expected
    assert parse_datetime("2026-09-28T06:25:36Z") == expected
    assert parse_datetime("1970-01-01T00:00:00+0000") is None  # « non renseigné »
    assert parse_datetime(None) is None
    assert parse_datetime("n'importe quoi") is None


def test_format_datetime_is_iso_with_offset():
    dt = datetime(2026, 9, 28, 8, 0, tzinfo=timezone(timedelta(hours=2)))
    assert format_datetime(dt) == "2026-09-28T08:00:00+0200"


def test_bike():
    bike = Bike.from_dict(BIKE)
    assert bike.id == 1 and bike.name == "Vélo test"
    assert bike.battery_percentage == 75
    assert bike.odometer_km == 5953.8
    assert bike.last_location.lat == 48.85 and bike.last_location.is_moving is False
    assert bike.last_location.date.tzinfo is not None
    assert bike.geofences[0].name == "Maison" and bike.geofences[0].active
    assert bike.geofences[0].radius == 150


def test_bike_without_location():
    bike = Bike.from_dict({"id": 2})
    assert bike.last_location is None and bike.geofences == [] and bike.odometer_km is None
    assert bike.name == "Vélo 2"


def test_health():
    health = Health.from_list(HEALTH)
    assert health.gps_battery == 100
    assert health.bike_system is True
    assert health.last_gps == datetime(2026, 9, 28, 6, 25, 36, tzinfo=timezone.utc)
    assert health.statuses["last_connection"] is True


def test_state_and_battery():
    state = BikeState.from_dict(STATE[0])
    assert state.odometer_km == 5954 and state.range_km == 100 and state.powered_on is False
    battery = BatteryState.from_dict(BATTERY)
    assert battery.charging is False and battery.last_full_charge is None


def test_ride():
    r = Ride.from_dict(ride(7, "2026-09-28T16:13:36+0000"))
    assert r.distance_km == 4.7 and r.active_time_s == 927 and r.weather_type == "cloudy"
