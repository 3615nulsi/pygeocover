import asyncio
import re
import time
from datetime import datetime, timezone

import aiohttp
import pytest
from aioresponses import aioresponses

from pygeocover import (
    GeocoverAuthError, GeocoverClient, GeocoverConnectionError, GeocoverLoginError, TokenSet,
)
from pygeocover.const import IDS_API, TOKEN_URL, bike_api_url

from .conftest import BIKE, LOGIN_SETTINGS, ride, token_response

API = bike_api_url()


@pytest.fixture
def mock():
    with aioresponses() as m:
        yield m


def fresh_tokens() -> TokenSet:
    return TokenSet("at_0", "rt_0", time.time() + 3600)


async def test_get_bikes_with_valid_token(mock):
    mock.get(API + "bike", payload=[BIKE])
    async with aiohttp.ClientSession() as session:
        client = GeocoverClient(session, fresh_tokens(), client_secret="secret")
        bikes = await client.async_get_bikes()
    assert bikes[0].name == "Vélo test"
    call = mock.requests[("GET", aiohttp.client.URL(API + "bike"))][0]
    assert call.kwargs["headers"]["Authorization"] == "Bearer at_0"
    assert call.kwargs["headers"]["Accept"] == "application/json"  # sinon HTTP 406


async def test_expired_token_is_refreshed_and_persisted(mock):
    saved = []
    mock.post(TOKEN_URL, payload=token_response(1))
    mock.get(API + "bike", payload=[BIKE])
    async with aiohttp.ClientSession() as session:
        client = GeocoverClient(session, TokenSet("at_0", "rt_0", 0), client_secret="secret",
                                on_tokens_updated=saved.append)
        await client.async_get_bikes()
    assert client.tokens.access_token == "at_1"
    assert [t.refresh_token for t in saved] == ["rt_1"]  # rotation persistée
    form = mock.requests[("POST", aiohttp.client.URL(TOKEN_URL))][0].kwargs["data"]
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "rt_0"
    assert form["client_secret"] == "secret"


async def test_async_callback_is_awaited(mock):
    saved = []

    async def save(tokens):
        await asyncio.sleep(0)
        saved.append(tokens)

    mock.post(TOKEN_URL, payload=token_response(1))
    async with aiohttp.ClientSession() as session:
        client = GeocoverClient(session, TokenSet("", "rt_0", 0), client_secret="secret", on_tokens_updated=save)
        await client.async_refresh_tokens()
    assert saved[0].access_token == "at_1"


async def test_401_forces_one_refresh_then_retries(mock):
    mock.get(API + "bike", status=401)
    mock.post(TOKEN_URL, payload=token_response(1))
    mock.get(API + "bike", payload=[BIKE])
    async with aiohttp.ClientSession() as session:
        client = GeocoverClient(session, fresh_tokens(), client_secret="secret")
        bikes = await client.async_get_bikes()
    assert len(bikes) == 1 and client.tokens.access_token == "at_1"


async def test_rejected_refresh_token_raises_auth_error(mock):
    mock.post(TOKEN_URL, status=400, payload={"error": "invalid_grant"})
    async with aiohttp.ClientSession() as session:
        client = GeocoverClient(session, TokenSet("", "rt_old", 0), client_secret="secret")
        with pytest.raises(GeocoverAuthError):
            await client.async_get_bikes()


async def test_no_tokens_raises_auth_error():
    async with aiohttp.ClientSession() as session:
        with pytest.raises(GeocoverAuthError):
            await GeocoverClient(session, client_secret="secret").async_get_bikes()


async def test_concurrent_calls_refresh_only_once(mock):
    mock.post(TOKEN_URL, payload=token_response(1))
    mock.get(API + "bike", payload=[BIKE], repeat=True)
    async with aiohttp.ClientSession() as session:
        client = GeocoverClient(session, TokenSet("at_0", "rt_0", 0), client_secret="secret")
        await asyncio.gather(*(client.async_get_bikes() for _ in range(5)))
    assert len(mock.requests[("POST", aiohttp.client.URL(TOKEN_URL))]) == 1


async def test_connection_error(mock):
    mock.get(API + "bike", exception=aiohttp.ClientConnectionError("boom"))
    async with aiohttp.ClientSession() as session:
        with pytest.raises(GeocoverConnectionError):
            await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_bikes()


async def test_full_login_flow(mock):
    saved = []
    mock.get(f"{IDS_API}/client/client-1/setting/loginpage", payload=LOGIN_SETTINGS)
    mock.post(TOKEN_URL, payload={"code": "IDSCODE"})
    mock.post(TOKEN_URL, payload=token_response(1))
    async with aiohttp.ClientSession() as session:
        client = GeocoverClient(session, client_id="client-1", client_secret="secret", on_tokens_updated=saved.append)
        req = await client.async_start_login()
        pasted = f"https://login.ids.conneq.tech/redirect?code=IDPCODE&state={req.state}"
        tokens = await client.async_finish_login(req, pasted)
    assert tokens.refresh_token == "rt_1" and saved == [tokens]
    step1, step2 = mock.requests[("POST", aiohttp.client.URL(TOKEN_URL))]
    assert step1.kwargs["json"]["grant_type"] == "idp_authorization_code"
    assert step1.kwargs["json"]["code"] == "IDPCODE"
    assert step2.kwargs["data"]["code"] == "IDSCODE"
    assert step2.kwargs["data"]["code_verifier"] == req.code_verifier


async def test_login_with_expired_code(mock, login_settings):
    from pygeocover import LoginRequest
    mock.post(TOKEN_URL, status=400, payload={"detail": "invalid code"})
    async with aiohttp.ClientSession() as session:
        client = GeocoverClient(session, client_secret="secret")
        with pytest.raises(GeocoverLoginError):
            await client.async_finish_login(LoginRequest.create(login_settings), "IDPCODE")


async def test_latest_ride_sorted_newest_first(mock):
    mock.get(re.compile(re.escape(API + "v2/bike/1/ride") + r"\?.*"),
             payload={"meta": {"limit": 1, "offset": 0, "total_records": 678},
                      "data": [ride(678, "2026-09-28T16:13:36+0000")]})
    async with aiohttp.ClientSession() as session:
        latest = await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_latest_ride(1)
    assert latest.id == 678
    call = [c for k, calls in mock.requests.items() for c in calls][0]
    # syntaxe de l'app (service n1 : new String[]{"start_date;desc"})
    assert call.kwargs["params"] == {"limit": 1, "offset": 0, "order": "start_date;desc"}


async def test_no_ride(mock):
    mock.get(re.compile(re.escape(API + "v2/bike/1/ride") + r"\?.*"),
             payload={"meta": {"limit": 1, "offset": 0, "total_records": 0}, "data": []})
    async with aiohttp.ClientSession() as session:
        assert await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_latest_ride(1) is None


async def test_locations_sends_iso_dates(mock):
    mock.get(re.compile(re.escape(API + "bike/1/location") + r"\?.*"), payload=[])
    start = datetime(2026, 9, 27, tzinfo=timezone.utc)
    end = datetime(2026, 9, 28, tzinfo=timezone.utc)
    async with aiohttp.ClientSession() as session:
        await GeocoverClient(session, fresh_tokens(), client_secret="secret").async_get_locations(1, start, end)
    call = [c for k, calls in mock.requests.items() for c in calls][0]
    assert call.kwargs["params"] == {"from": "2026-09-27T00:00:00+0000", "till": "2026-09-28T00:00:00+0000"}
