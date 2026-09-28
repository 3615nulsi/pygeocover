"""Modèles de données de l'API vélo (réponses réelles observées le 2026-09-28)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def parse_datetime(value: Any) -> Optional[datetime]:
    """Dates API au format `2026-09-28T06:25:36+0000` (ou `+00:00` / `Z`)."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+0000"
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        # l'API renvoie 1970-01-01 pour « non renseigné »
        return None if dt.year <= 1970 else dt
    return None


def format_datetime(value: datetime) -> str:
    """Format attendu par les paramètres `from`/`till` (ISO 8601 ; epoch -> HTTP 422)."""
    return value.strftime("%Y-%m-%dT%H:%M:%S%z")


def _float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class Location:
    lat: Optional[float]
    lon: Optional[float]
    date: Optional[datetime]
    speed: Optional[float]
    is_moving: bool
    # 0 dans l'historique ; seule `Bike.last_location` porte la vraie valeur
    battery_percentage: Optional[int]
    bike_id: Optional[int]
    id: Optional[str]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Location":
        return cls(
            lat=_float(data.get("lat")),
            lon=_float(data.get("lon")),
            date=parse_datetime(data.get("date")),
            speed=_float(data.get("speed")),
            is_moving=bool(data.get("is_moving")),
            battery_percentage=_int(data.get("battery_percentage")),
            bike_id=_int(data.get("bike_id")),
            id=data.get("id"),
        )


@dataclass
class Geofence:
    id: int
    name: str
    lat: Optional[float]
    lon: Optional[float]
    radius: Optional[float]  # mètres
    active: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Geofence":
        center = data.get("center") or {}
        return cls(
            id=int(data["id"]),
            name=data.get("name") or "",
            lat=_float(center.get("lat")),
            lon=_float(center.get("lon")),
            radius=_float(data.get("radius")),
            active=data.get("active_state") == 0,  # 0 = active (convention Conneqtech)
        )


@dataclass
class Bike:
    id: int
    name: str
    imei: Optional[str]
    battery_percentage: Optional[int]
    odometer_m: Optional[int]
    last_location: Optional[Location]
    geofences: List[Geofence]
    manufacturer: Optional[str]
    frame_number: Optional[str]
    article_number: Optional[str]
    image_url: Optional[str]
    is_stolen: bool
    ride_in_progress: bool
    raw: Dict[str, Any] = field(repr=False)

    @property
    def odometer_km(self) -> Optional[float]:
        return None if self.odometer_m is None else round(self.odometer_m / 1000, 1)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Bike":
        loc = data.get("last_location")
        return cls(
            id=int(data["id"]),
            name=data.get("name") or f"Vélo {data['id']}",
            imei=data.get("imei"),
            battery_percentage=_int(data.get("battery_percentage")),
            odometer_m=_int(data.get("odometer")),
            last_location=Location.from_dict(loc) if loc else None,
            geofences=[Geofence.from_dict(g) for g in data.get("geofences") or []],
            manufacturer=data.get("manufacturer"),
            frame_number=data.get("frame_number"),
            article_number=data.get("article_number"),
            image_url=data.get("bike_image_url"),
            is_stolen=bool(data.get("is_stolen")),
            ride_in_progress=bool(data.get("ride_in_progress")),
            raw=data,
        )


@dataclass
class BatteryState:
    battery_percentage: Optional[int]
    charging: Optional[bool]
    range_km: Optional[float]
    last_battery_update: Optional[datetime]
    last_full_charge: Optional[datetime]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatteryState":
        return cls(
            battery_percentage=_int(data.get("battery_percentage")),
            charging=data.get("charging"),
            range_km=_float(data.get("range")),
            last_battery_update=parse_datetime(data.get("last_battery_update")),
            last_full_charge=parse_datetime(data.get("last_full_charge")),
        )


@dataclass
class BikeState:
    powered_on: Optional[bool]
    ecu_locked: Optional[bool]
    erl_locked: Optional[bool]
    battery_percentage: Optional[int]
    charging: Optional[bool]
    range_km: Optional[float]
    odometer_km: Optional[float]  # en km ici (Bike.odometer_m est en mètres)
    last_full_charge: Optional[datetime]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BikeState":
        return cls(
            powered_on=data.get("powered_on"),
            ecu_locked=data.get("ecu_locked"),
            erl_locked=data.get("erl_locked"),
            battery_percentage=_int(data.get("battery_percentage")),
            charging=data.get("charging"),
            range_km=_float(data.get("range")),
            odometer_km=_float(data.get("odometer")),
            last_full_charge=parse_datetime(data.get("last_full_charge")),
        )


@dataclass
class Health:
    """`GET bike/{id}/health` : liste {key, status, value, value_type} aplatie."""

    last_connection: Optional[datetime]
    last_gps: Optional[datetime]
    gps_battery: Optional[int]  # % de la batterie du traceur GPS
    bike_system: Optional[bool]
    statuses: Dict[str, bool]
    raw: List[Dict[str, Any]] = field(repr=False)

    @classmethod
    def from_list(cls, items: List[Dict[str, Any]]) -> "Health":
        values = {i.get("key"): i.get("value") for i in items}
        gps_battery = values.get("gps_battery")
        system = values.get("bike_system")
        return cls(
            last_connection=parse_datetime(values.get("last_connection")),
            last_gps=parse_datetime(values.get("last_gps")),
            gps_battery=_int(str(gps_battery).rstrip("%")) if gps_battery is not None else None,
            bike_system=None if system is None else str(system).lower() == "true",
            statuses={i.get("key"): bool(i.get("status")) for i in items},
            raw=items,
        )


@dataclass
class Ride:
    id: int
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    distance_m: Optional[int]
    active_time_s: Optional[int]
    avg_speed: Optional[float]  # km/h
    calories: Optional[int]
    co2: Optional[int]  # unité non documentée (g économisés ?)
    elevation_up: Optional[int]
    elevation_down: Optional[int]
    rating: Optional[int]
    ride_type: Optional[str]
    weather_type: Optional[str]
    name: str

    @property
    def distance_km(self) -> Optional[float]:
        return None if self.distance_m is None else round(self.distance_m / 1000, 2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Ride":
        return cls(
            id=int(data["id"]),
            start_date=parse_datetime(data.get("start_date")),
            end_date=parse_datetime(data.get("end_date")),
            distance_m=_int(data.get("distance_traveled")),
            active_time_s=_int(data.get("active_time")),
            avg_speed=_float(data.get("avg_speed")),
            calories=_int(data.get("calories")),
            co2=_int(data.get("co2")),
            elevation_up=_int(data.get("elevation_up")),
            elevation_down=_int(data.get("elevation_down")),
            rating=_int(data.get("rating")),
            ride_type=data.get("ride_type"),
            weather_type=(data.get("weather_info") or {}).get("weather_type"),
            name=data.get("name") or "",
        )


@dataclass
class RidePage:
    rides: List[Ride]
    total: int
    offset: int
    limit: int


@dataclass
class User:
    id: int
    username: str  # UUID Conneqtech, identifiant stable
    name: Optional[str]
    email: Optional[str]
    country: Optional[str]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        return cls(
            id=int(data["id"]),
            username=data.get("username") or str(data["id"]),
            name=data.get("display_name") or data.get("name"),
            email=data.get("email"),
            country=data.get("country"),
        )
