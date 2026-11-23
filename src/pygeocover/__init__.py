"""pygeocover: unofficial asynchronous client of the Decathlon Geocover API (Conneqtech)."""
from .auth import LoginRequest, TokenSet
from .client import GeocoverClient
from .exceptions import (
    GeocoverApiError,
    GeocoverAuthError,
    GeocoverConnectionError,
    GeocoverError,
    GeocoverLoginError,
    GeocoverRateLimitError,
    GeocoverResponseError,
)
from .models import BatteryState, Bike, BikeState, Geofence, Health, Location, Ride, RidePage, User

__version__ = "0.2.0"

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
    "GeocoverRateLimitError",
    "GeocoverResponseError",
    "Geofence",
    "Health",
    "Location",
    "LoginRequest",
    "Ride",
    "RidePage",
    "TokenSet",
    "User",
]
