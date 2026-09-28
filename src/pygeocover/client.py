"""Client asynchrone de l'API vélo Geocover."""
from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

import aiohttp

from .auth import LoginRequest, TokenSet
from .const import (
    DEFAULT_BRAND, DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, IDS_API, REQUEST_TIMEOUT, TOKEN_URL, bike_api_url,
)
from .exceptions import (
    GeocoverApiError,
    GeocoverAuthError,
    GeocoverConnectionError,
    GeocoverLoginError,
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

TokenCallback = Callable[[TokenSet], Union[None, Awaitable[None]]]


class GeocoverClient:
    """Accès à l'API vélo pour un compte.

    Le refresh_token est ROTATIF et à usage unique : chaque rafraîchissement en
    renvoie un nouveau et invalide l'ancien. `on_tokens_updated` est appelé à chaque
    nouveau jeu de jetons ; l'appelant DOIT le persister (sinon déconnexion au
    prochain redémarrage).
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Optional[TokenSet] = None,
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        client_secret: str = DEFAULT_CLIENT_SECRET,
        brand: str = DEFAULT_BRAND,
        on_tokens_updated: Optional[TokenCallback] = None,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = bike_api_url(brand)
        self._on_tokens_updated = on_tokens_updated
        self._refresh_lock = asyncio.Lock()
        self.tokens = tokens

    # --- connexion -----------------------------------------------------------

    async def async_start_login(self) -> LoginRequest:
        """Prépare une connexion : ouvrir `request.url` dans un navigateur."""
        settings = await self._raw_request(
            "GET", f"{IDS_API}/client/{self._client_id}/setting/loginpage")
        return LoginRequest.create(settings, self._client_id)

    async def async_finish_login(self, request: LoginRequest, pasted: str) -> TokenSet:
        """Termine la connexion avec l'URL de la page d'erreur collée par l'utilisateur."""
        idp_code = request.extract_code(pasted)
        try:
            data = await self._raw_request(
                "POST", TOKEN_URL, json=request.idp_exchange_payload(idp_code))
        except GeocoverApiError as err:
            raise GeocoverLoginError(
                f"Code Decathlon refusé ({err}) : il a peut-être expiré, relancez la connexion."
            ) from err
        code = data.get("code") if isinstance(data, dict) else None
        if not code:
            raise GeocoverLoginError(f"Réponse inattendue à l'échange du code : {data!r}")
        try:
            data = await self._raw_request(
                "POST", TOKEN_URL, data=request.token_payload(code, self._client_secret))
        except GeocoverApiError as err:
            raise GeocoverLoginError(f"Obtention des jetons refusée ({err}).") from err
        await self._set_tokens(TokenSet.from_response(data))
        return self.tokens  # type: ignore[return-value]

    # --- jetons --------------------------------------------------------------

    async def async_refresh_tokens(self, force: bool = False) -> TokenSet:
        """Rafraîchit l'access_token si nécessaire (ou toujours si `force`)."""
        if self.tokens is None:
            raise GeocoverAuthError("Aucun jeton : connexion nécessaire.")
        stale = self.tokens.access_token
        async with self._refresh_lock:
            # un autre appel a pu rafraîchir pendant l'attente du verrou
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
                if err.status in (400, 401, 403):
                    raise GeocoverAuthError(
                        f"refresh_token refusé ({err}) : nouvelle connexion nécessaire."
                    ) from err
                raise
            await self._set_tokens(TokenSet.from_response(data))
            _LOGGER.debug("Jetons rafraîchis")
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
                    raise GeocoverApiError(resp.status, await _error_detail(resp))
                if resp.status == 204:
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GeocoverConnectionError(f"{method} {url} : {err!r}") from err

    async def _api(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET authentifié sur l'API vélo ; 401 -> refresh forcé -> un seul nouvel essai."""
        await self.async_refresh_tokens()
        for attempt in (1, 2):
            assert self.tokens is not None
            try:
                return await self._raw_request(
                    "GET", self._base_url + path, params=params,
                    headers={"Authorization": f"Bearer {self.tokens.access_token}",
                             "Accept-Language": "fr"})
            except GeocoverApiError as err:
                if err.status != 401:
                    raise
                if attempt == 2:
                    raise GeocoverAuthError(f"Accès refusé à {path} malgré un jeton neuf.") from err
                await self.async_refresh_tokens(force=True)

    # --- endpoints -----------------------------------------------------------

    async def async_get_user(self) -> User:
        return User.from_dict(await self._api("user/me"))

    async def async_get_bikes(self) -> List[Bike]:
        """Un seul appel : position, batterie, odomètre et géofences de chaque vélo."""
        return [Bike.from_dict(b) for b in await self._api("bike") or []]

    async def async_get_bike(self, bike_id: int) -> Bike:
        return Bike.from_dict(await self._api(f"bike/{bike_id}"))

    async def async_get_locations(
        self, bike_id: int, start: datetime, end: datetime
    ) -> List[Location]:
        """Historique des positions (du plus récent au plus ancien). Dates avec fuseau."""
        data = await self._api(f"bike/{bike_id}/location",
                               {"from": format_datetime(start), "till": format_datetime(end)})
        return [Location.from_dict(item) for item in data or []]

    async def async_get_battery(self, bike_id: int) -> BatteryState:
        return BatteryState.from_dict(await self._api(f"bike/{bike_id}/battery/current-state"))

    async def async_get_state(self, bike_id: int) -> Optional[BikeState]:
        data = await self._api(f"bike/{bike_id}/state")
        return BikeState.from_dict(data[0]) if data else None

    async def async_get_health(self, bike_id: int) -> Health:
        return Health.from_list(await self._api(f"bike/{bike_id}/health") or [])

    async def async_get_geofences(self, bike_id: int) -> List[Geofence]:
        return [Geofence.from_dict(g) for g in await self._api(f"bike/{bike_id}/geofence") or []]

    async def async_get_rides(
        self, bike_id: int, limit: int = 20, offset: int = 0, newest_first: bool = True
    ) -> RidePage:
        """Trajets paginés ; tri `order=<champ>;<sens>` comme l'app (défaut serveur : ascendant)."""
        order = "start_date;desc" if newest_first else "start_date;asc"
        data = await self._api(f"v2/bike/{bike_id}/ride",
                               {"limit": limit, "offset": offset, "order": order})
        meta = data.get("meta") or {}
        return RidePage(
            rides=[Ride.from_dict(r) for r in data.get("data") or []],
            total=int(meta.get("total_records") or 0),
            offset=int(meta.get("offset") or offset),
            limit=int(meta.get("limit") or limit),
        )

    async def async_get_latest_ride(self, bike_id: int) -> Optional[Ride]:
        page = await self.async_get_rides(bike_id, limit=1)
        return page.rides[0] if page.rides else None


async def _error_detail(resp: aiohttp.ClientResponse) -> str:
    try:
        body = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001 - corps non JSON
        return (await resp.text())[:200]
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("error_description") or body.get("error") or body)
    return str(body)[:200]
