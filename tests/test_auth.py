import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest

from pygeocover.auth import LoginRequest, TokenSet
from pygeocover.const import APP_REDIRECT_URI, UNROUTABLE_REDIRECT_URI
from pygeocover.exceptions import GeocoverLoginError


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_login_url_and_state(login_settings):
    req = LoginRequest.create(login_settings, "client-1")
    url = urlparse(req.url)
    assert f"{url.scheme}://{url.netloc}{url.path}" == login_settings["idp_uri"]
    qs = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert qs["client_id"] == "idp-client"
    assert qs["redirect_uri"] == login_settings["idp_redirect_uri"]
    assert qs["state"] == req.state
    # le state a le format attendu par login.ids.conneq.tech/redirect…
    state = json.loads(_b64decode(req.state))
    assert state["client_id"] == "client-1"
    assert state["appCodeChallenge"] == req.code_challenge
    # …avec une redirectURI non autorisée pour que la page échoue sans consommer le code
    assert state["redirectURI"] == UNROUTABLE_REDIRECT_URI
    assert state["redirectURI"] not in login_settings["login_page_allowed_redirect_uris"]
    # PKCE S256
    digest = hashlib.sha256(req.code_verifier.encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == req.code_challenge


def test_login_request_roundtrip(login_settings):
    req = LoginRequest.create(login_settings)
    assert LoginRequest.from_dict(json.loads(json.dumps(req.to_dict()))) == req


def test_extract_code(login_settings):
    req = LoginRequest.create(login_settings)
    url = f"https://login.ids.conneq.tech/redirect?code=ABC_123&state={req.state}"
    assert req.extract_code(url) == "ABC_123"
    assert req.extract_code("  " + url + "\n") == "ABC_123"
    assert req.extract_code("ABC_123") == "ABC_123"
    with pytest.raises(GeocoverLoginError):
        req.extract_code("https://login.ids.conneq.tech/redirect?code=X&state=autre")
    with pytest.raises(GeocoverLoginError):
        req.extract_code("https://login.ids.conneq.tech/redirect")
    with pytest.raises(GeocoverLoginError):
        req.extract_code("")


def test_payloads(login_settings):
    req = LoginRequest.create(login_settings, "client-1")
    idp = req.idp_exchange_payload("IDPCODE")
    assert idp["grant_type"] == "idp_authorization_code"
    assert idp["redirect_uri"] == APP_REDIRECT_URI and idp["code"] == "IDPCODE"
    assert idp["issuer_id"] == login_settings["idp_issuer_id"]
    tok = req.token_payload("IDSCODE", "secret")
    assert tok["grant_type"] == "authorization_code"
    assert tok["code_verifier"] == req.code_verifier and tok["client_secret"] == "secret"


def test_tokenset():
    tok = TokenSet.from_response({"access_token": "a", "refresh_token": "r", "expires_in": 14400}, now=1000)
    assert tok.expires_at == 15400
    assert not tok.needs_refresh(now=1000)
    assert tok.needs_refresh(now=15400 - 299)
    assert TokenSet.from_dict(tok.to_dict()) == tok
    assert TokenSet.from_dict({"refresh_token": "r"}).needs_refresh()
