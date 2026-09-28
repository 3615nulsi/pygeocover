"""pygeocover — client asynchrone non officiel de l'API Decathlon Geocover (Conneqtech)."""
from .auth import LoginRequest, TokenSet
from .client import GeocoverClient
from .exceptions import (
    GeocoverApiError,
    GeocoverAuthError,
    GeocoverConnectionError,
    GeocoverError,
    GeocoverLoginError,
)
from .models import BatteryState, Bike, BikeState, Geofence, Health, Location, Ride, RidePage, User

__version__ = "0.1.0"

__all__ = [
    "BatteryState",
    "Bike",
    "BikeState",
    "GeocoverApiError",
    "GeocoverAuthError",
    "GeocoverClient",
    "GeocoverConnectionError",
    "GeocoverError",
    "GeocoverLoginError",
    "Geofence",
    "Health",
    "Location",
    "LoginRequest",
    "Ride",
    "RidePage",
    "TokenSet",
    "User",
]
