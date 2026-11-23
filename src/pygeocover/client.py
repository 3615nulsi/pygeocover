"""Asynchronous client of the Geocover bike API."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import inspect
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar, Union

import aiohttp

from .auth import LoginRequest, TokenSet
from .const import (
    DEFAULT_BRAND, DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, DEFAULT_LANGUAGE, IDS_API,
    REQUEST_TIMEOUT, TOKEN_URL, bike_api_url,
)
from .exceptions import (
    GeocoverApiError,
    GeocoverAuthError,
    GeocoverConnectionError,
    GeocoverLoginError,
    GeocoverRateLimitError,
    GeocoverResponseError,
)
from .models import (
    BatteryState,
    Bike,
    BikeState,
    Geofence,
    Health,
    Location,
    Ride,
    RidePage,
    User,
    format_datetime,
)

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")
TokenCallback = Callable[[TokenSet], Union[None, Awaitable[None]]]

# Errors of the token endpoint that mean the refresh token itself is no longer valid.
# Anything else (server incident, malformed request) must not force a new sign-in.
_REJECTED_GRANT_ERRORS = {"invalid_grant"}


def _parse(builder: Callable[..., T], *args: Any) -> T:
    """Build a model, turning any format surprise into `GeocoverResponseError`."""
    try:
        return builder(*args)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as err:
        raise GeocoverResponseError(f"Unexpected response format: {err!r}") from err


class GeocoverClient:
    """Access to the bike API for one account.

    The refresh token is ROTATING and single-use: every refresh returns a new one and
    invalidates the previous one. `on_tokens_updated` is called with every new token
    set; the caller MUST persist it, or the next restart will require a new sign-in.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Optional[TokenSet] = None,
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        client_secret: str = DEFAULT_CLIENT_SECRET,
        brand: str = DEFAULT_BRAND,
        language: str = DEFAULT_LANGUAGE,
        on_tokens_updated: Optional[TokenCallback] = None,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = bike_api_url(brand)
        self._language = language
        self._on_tokens_updated = on_tokens_updated
        self._refresh_lock = asyncio.Lock()
        self.tokens = tokens

    # --- sign-in ------------------------------------------------------------

    async def async_start_login(self) -> LoginRequest:
        """Prepare a sign-in: open `request.url` in a browser."""
        settings = await self._raw_request(
            "GET", f"{IDS_API}/client/{self._client_id}/setting/loginpage")
        return _parse(LoginRequest.create, settings, self._client_id)

    async def async_finish_login(self, request: LoginRequest, pasted: str) -> TokenSet:
        """Finish the sign-in with the address of the error page pasted by the user."""
        idp_code = request.extract_code(pasted)
        try:
            data = await self._raw_request(
                "POST", TOKEN_URL, json=request.idp_exchange_payload(idp_code))
        except GeocoverApiError as err:
            raise GeocoverLoginError(
                f"Decathlon code rejected ({err}): it may have expired, sign in again."
            ) from err
        code = data.get("code") if isinstance(data, dict) else None
        if not code:
            raise GeocoverResponseError(f"Unexpected answer to the code exchange: {data!r}")
        try:
            data = await self._raw_request(
                "POST", TOKEN_URL, data=request.token_payload(code, self._client_secret))
        except GeocoverApiError as err:
            raise GeocoverLoginError(f"Token request rejected ({err}).") from err
        await self._set_tokens(_parse(TokenSet.from_response, data))
        return self.tokens  # type: ignore[return-value]

    # --- tokens -------------------------------------------------------------

    async def async_refresh_tokens(self, force: bool = False) -> TokenSet:
        """Refresh the access token when needed (always if `force`)."""
        if self.tokens is None:
            raise GeocoverAuthError("No tokens: sign-in required.")
        stale = self.tokens.access_token
        async with self._refresh_lock:
            # another call may have refreshed while we waited for the lock
            if force and self.tokens.access_token != stale:
                return self.tokens
            if not force and not self.tokens.needs_refresh():
                return self.tokens
            try:
                data = await self._raw_request("POST", TOKEN_URL, data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self.tokens.refresh_token,
                    "grant_type": "refresh_token",
                })
            except GeocoverApiError as err:
                if err.error in _REJECTED_GRANT_ERRORS or err.status in (401, 403):
                    raise GeocoverAuthError(
                        f"Refresh token rejected ({err}): sign-in required."
                    ) from err
                raise
            await self._set_tokens(_parse(TokenSet.from_response, data))
            _LOGGER.debug("Tokens refreshed")
            return self.tokens  # type: ignore[return-value]

    async def _set_tokens(self, tokens: TokenSet) -> None:
        self.tokens = tokens
        if self._on_tokens_updated is not None:
            result = self._on_tokens_updated(tokens)
            if inspect.isawaitable(result):
                await result

    # --- HTTP ----------------------------------------------------------------

    async def _raw_request(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = {"Accept": "application/json", **kwargs.pop("headers", {})}
        try:
            async with self._session.request(
                method, url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT), **kwargs,
            ) as resp:
                if resp.status >= 400:
                    raise await _api_error(resp)
                if resp.status == 204:
                    return None
                try:
                    return await resp.json(content_type=None)
                except ValueError as err:
                    raise GeocoverResponseError(
                        f"{method} {url}: invalid JSON ({err})") from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GeocoverConnectionError(f"{method} {url}: {err!r}") from err

    async def _api(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Authenticated GET on the bike API; 401 -> forced refresh -> one more try."""
        await self.async_refresh_tokens()
        for attempt in (1, 2):
            assert self.tokens is not None
            try:
                return await self._raw_request(
                    "GET", self._base_url + path, params=params,
                    headers={"Authorization": f"Bearer {self.tokens.access_token}",
                             "Accept-Language": self._language})
            except GeocoverApiError as err:
                if err.status != 401:
                    raise
                if attempt == 2:
                    raise GeocoverAuthError(
                        f"Access to {path} denied despite a fresh token.") from err
                await self.async_refresh_tokens(force=True)

    # --- endpoints ----------------------------------------------------------

    async def async_get_user(self) -> User:
        return _parse(User.from_dict, await self._api("user/me"))

    async def async_get_bikes(self) -> List[Bike]:
        """One call: position, battery, odometer and geofences of every bike."""
        data = await self._api("bike")
        return _parse(lambda items: [Bike.from_dict(b) for b in items or []], data)

    async def async_get_bike(self, bike_id: int) -> Bike:
        return _parse(Bike.from_dict, await self._api(f"bike/{bike_id}"))

    async def async_get_locations(
        self, bike_id: int, start: datetime, end: datetime
    ) -> List[Location]:
        """Position history (newest first). Dates must be timezone-aware."""
        data = await self._api(f"bike/{bike_id}/location",
                               {"from": format_datetime(start), "till": format_datetime(end)})
        return _parse(lambda items: [Location.from_dict(i) for i in items or []], data)

    async def async_get_battery(self, bike_id: int) -> BatteryState:
        data = await self._api(f"bike/{bike_id}/battery/current-state")
        return _parse(BatteryState.from_dict, data)

    async def async_get_state(self, bike_id: int) -> Optional[BikeState]:
        data = await self._api(f"bike/{bike_id}/state")
        return _parse(lambda d: BikeState.from_dict(d[0]) if d else None, data)

    async def async_get_health(self, bike_id: int) -> Health:
        data = await self._api(f"bike/{bike_id}/health")
        return _parse(Health.from_list, data or [])

    async def async_get_geofences(self, bike_id: int) -> List[Geofence]:
        data = await self._api(f"bike/{bike_id}/geofence")
        return _parse(lambda items: [Geofence.from_dict(g) for g in items or []], data)

    async def async_get_rides(
        self, bike_id: int, limit: int = 20, offset: int = 0, newest_first: bool = True
    ) -> RidePage:
        """Paginated rides; sorted with `order=<field>;<direction>` like the app.

        `total` is the number of rides recorded for the bike.
        """
        order = "start_date;desc" if newest_first else "start_date;asc"
        data = await self._api(f"v2/bike/{bike_id}/ride",
                               {"limit": limit, "offset": offset, "order": order})
        return _parse(_ride_page, data or {}, limit, offset)

    async def async_get_latest_ride(self, bike_id: int) -> Optional[Ride]:
        page = await self.async_get_rides(bike_id, limit=1)
        return page.rides[0] if page.rides else None


def _ride_page(data: Dict[str, Any], limit: int, offset: int) -> RidePage:
    meta = data.get("meta") or {}
    return RidePage(
        rides=[Ride.from_dict(r) for r in data.get("data") or []],
        total=int(meta.get("total_records") or 0),
        offset=int(meta.get("offset") or offset),
        limit=int(meta.get("limit") or limit),
    )


def _retry_after(value: Optional[str]) -> Optional[float]:
    """`Retry-After` header: delay in seconds, or an HTTP date."""
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((when - datetime.now(timezone.utc)).total_seconds(), 0.0)


async def _api_error(resp: aiohttp.ClientResponse) -> GeocoverApiError:
    detail, error = await _error_detail(resp)
    retry_after = _retry_after(resp.headers.get("Retry-After"))
    cls = GeocoverRateLimitError if resp.status == 429 else GeocoverApiError
    return cls(resp.status, detail, error=error, retry_after=retry_after)


async def _error_detail(resp: aiohttp.ClientResponse) -> "tuple[str, Optional[str]]":
    """Return a short description of an error response, and its OAuth error code."""
    try:
        body = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001 - non-JSON body
        return (await resp.text())[:200], None
    if isinstance(body, dict):
        error = body.get("error")
        detail = body.get("detail") or body.get("error_description") or error or body
        return str(detail)[:200], error if isinstance(error, str) else None
    return str(body)[:200], None
