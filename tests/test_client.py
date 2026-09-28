import asyncio
import time
from datetime import datetime, timezone

import aiohttp
import pytest

from pygeocover import (
    GeocoverAuthError, GeocoverClient, GeocoverConnectionError, GeocoverLoginError, LoginRequest,
    TokenSet,
)
from pygeocover.const import IDS_API, TOKEN_URL, bike_api_url

from .conftest import BIKE, LOGIN_SETTINGS, ride, token_response

API = bike_api_url()


def fresh_tokens() -> TokenSet:
    return TokenSet("at_0", "rt_0", time.time() + 3600)


async def test_get_bikes_with_valid_token(session):
    session.add("GET", API + "bike", payload=[BIKE])
    bikes = await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_bikes()
    assert bikes[0].name == "Vélo test"
    headers = session.calls_to("GET", API + "bike")[0].kwargs["headers"]
    assert headers["Authorization"] == "Bearer at_0"
    assert headers["Accept"] == "application/json"  # sinon HTTP 406


async def test_expired_token_is_refreshed_and_persisted(session):
    saved = []
    session.add("POST", TOKEN_URL, payload=token_response(1))
    session.add("GET", API + "bike", payload=[BIKE])
    client = GeocoverClient(session, TokenSet("at_0", "rt_0", 0), client_secret="secret",
                            on_tokens_updated=saved.append)
    await client.async_get_bikes()
    assert client.tokens.access_token == "at_1"
    assert [t.refresh_token for t in saved] == ["rt_1"]  # rotation persistée
    form = session.calls_to("POST", TOKEN_URL)[0].kwargs["data"]
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "rt_0"
    assert form["client_secret"] == "secret"


async def test_default_client_secret_is_used(session):
    from pygeocover.const import DEFAULT_CLIENT_SECRET
    session.add("POST", TOKEN_URL, payload=token_response(1))
    await GeocoverClient(session, TokenSet("", "rt_0", 0)).async_refresh_tokens()
    assert session.calls_to("POST", TOKEN_URL)[0].kwargs["data"]["client_secret"] == DEFAULT_CLIENT_SECRET


async def test_async_callback_is_awaited(session):
    saved = []

    async def save(tokens):
        await asyncio.sleep(0)
        saved.append(tokens)

    session.add("POST", TOKEN_URL, payload=token_response(1))
    client = GeocoverClient(session, TokenSet("", "rt_0", 0), client_secret="secret",
                            on_tokens_updated=save)
    await client.async_refresh_tokens()
    assert saved[0].access_token == "at_1"


async def test_401_forces_one_refresh_then_retries(session):
    session.add("GET", API + "bike", status=401)
    session.add("POST", TOKEN_URL, payload=token_response(1))
    session.add("GET", API + "bike", payload=[BIKE])
    client = GeocoverClient(session, fresh_tokens(), client_secret="secret")
    bikes = await client.async_get_bikes()
    assert len(bikes) == 1 and client.tokens.access_token == "at_1"


async def test_rejected_refresh_token_raises_auth_error(session):
    session.add("POST", TOKEN_URL, status=400, payload={"error": "invalid_grant"})
    client = GeocoverClient(session, TokenSet("", "rt_old", 0), client_secret="secret")
    with pytest.raises(GeocoverAuthError):
        await client.async_get_bikes()


async def test_no_tokens_raises_auth_error(session):
    with pytest.raises(GeocoverAuthError):
        await GeocoverClient(session, client_secret="secret").async_get_bikes()


async def test_concurrent_calls_refresh_only_once(session):
    session.add("POST", TOKEN_URL, payload=token_response(1))
    session.add("GET", API + "bike", payload=[BIKE], repeat=True)
    client = GeocoverClient(session, TokenSet("at_0", "rt_0", 0), client_secret="secret")
    await asyncio.gather(*(client.async_get_bikes() for _ in range(5)))
    assert len(session.calls_to("POST", TOKEN_URL)) == 1


async def test_connection_error(session):
    session.add("GET", API + "bike", exception=aiohttp.ClientConnectionError("boom"))
    with pytest.raises(GeocoverConnectionError):
        await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_bikes()


async def test_timeout_is_a_connection_error(session):
    session.add("GET", API + "bike", exception=asyncio.TimeoutError())
    with pytest.raises(GeocoverConnectionError):
        await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_bikes()


async def test_full_login_flow(session):
    saved = []
    session.add("GET", f"{IDS_API}/client/client-1/setting/loginpage", payload=LOGIN_SETTINGS)
    session.add("POST", TOKEN_URL, payload={"code": "IDSCODE"})
    session.add("POST", TOKEN_URL, payload=token_response(1))
    client = GeocoverClient(session, client_id="client-1", client_secret="secret",
                            on_tokens_updated=saved.append)
    req = await client.async_start_login()
    pasted = f"https://login.ids.conneq.tech/redirect?code=IDPCODE&state={req.state}"
    tokens = await client.async_finish_login(req, pasted)
    assert tokens.refresh_token == "rt_1" and saved == [tokens]
    step1, step2 = session.calls_to("POST", TOKEN_URL)
    assert step1.kwargs["json"]["grant_type"] == "idp_authorization_code"
    assert step1.kwargs["json"]["code"] == "IDPCODE"
    assert step2.kwargs["data"]["code"] == "IDSCODE"
    assert step2.kwargs["data"]["code_verifier"] == req.code_verifier


async def test_login_with_expired_code(session, login_settings):
    session.add("POST", TOKEN_URL, status=400, payload={"detail": "invalid code"})
    client = GeocoverClient(session, client_secret="secret")
    with pytest.raises(GeocoverLoginError):
        await client.async_finish_login(LoginRequest.create(login_settings), "IDPCODE")


async def test_latest_ride_sorted_newest_first(session):
    session.add("GET", API + "v2/bike/1/ride",
                payload={"meta": {"limit": 1, "offset": 0, "total_records": 678},
                         "data": [ride(678, "2026-09-28T16:13:36+0000")]})
    latest = await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_latest_ride(1)
    assert latest.id == 678
    # syntaxe de l'app (service n1 : new String[]{"start_date;desc"})
    assert session.calls[0].kwargs["params"] == {"limit": 1, "offset": 0, "order": "start_date;desc"}


async def test_no_ride(session):
    session.add("GET", API + "v2/bike/1/ride",
                payload={"meta": {"limit": 1, "offset": 0, "total_records": 0}, "data": []})
    client = GeocoverClient(session, fresh_tokens(), client_secret="secret")
    assert await client.async_get_latest_ride(1) is None


async def test_locations_sends_iso_dates(session):
    session.add("GET", API + "bike/1/location", payload=[])
    start = datetime(2026, 9, 27, tzinfo=timezone.utc)
    end = datetime(2026, 9, 28, tzinfo=timezone.utc)
    await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_locations(1, start, end)
    assert session.calls[0].kwargs["params"] == {
        "from": "2026-09-27T00:00:00+0000", "till": "2026-09-28T00:00:00+0000"}
