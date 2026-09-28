"""Connexion OAuth2 + PKCE et jetons Conneqtech.

Seule redirect_uri autorisée pour le client de l'app : `tech.conneq.decathlon://…`,
qu'un navigateur de bureau ne sait pas ouvrir. On passe donc directement par l'IdP
Decathlon avec un `state` (même format que la page login.ids.conneq.tech) dont la
redirectURI n'est pas autorisée : au retour, la page
`https://login.ids.conneq.tech/redirect?code=…&state=…` échoue (« Whoops! ») AVANT
de consommer le code Decathlon. L'utilisateur colle cette URL, puis on fait nous-mêmes :
  1. POST /oauth (JSON, grant_type=idp_authorization_code) -> {code}
  2. POST /oauth (form, grant_type=authorization_code + code_verifier) -> jetons
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from .const import APP_REDIRECT_URI, DEFAULT_CLIENT_ID, TOKEN_REFRESH_MARGIN, UNROUTABLE_REDIRECT_URI
from .exceptions import GeocoverLoginError


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch (s)

    @classmethod
    def from_response(cls, data: Dict[str, Any], now: Optional[float] = None) -> "TokenSet":
        now = time.time() if now is None else now
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=now + float(data.get("expires_in") or 0),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenSet":
        return cls(
            access_token=data.get("access_token") or "",
            refresh_token=data["refresh_token"],
            expires_at=float(data.get("expires_at") or 0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def needs_refresh(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return not self.access_token or self.expires_at - TOKEN_REFRESH_MARGIN <= now


@dataclass
class LoginRequest:
    """Connexion en cours ; sérialisable (to_dict) pour être gardée entre deux étapes."""

    url: str
    state: str
    code_verifier: str
    code_challenge: str
    nonce: str
    client_id: str
    issuer_id: str
    idp_redirect_uri: str

    @classmethod
    def create(cls, settings: Dict[str, Any], client_id: str = DEFAULT_CLIENT_ID) -> "LoginRequest":
        """`settings` = GET api.ids.conneq.tech/client/{client_id}/setting/loginpage."""
        verifier = secrets.token_urlsafe(64)
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        nonce = secrets.token_urlsafe(16)
        state = _b64url(json.dumps({
            "client_id": client_id,
            "redirectURI": UNROUTABLE_REDIRECT_URI,
            "nonce": secrets.token_hex(3),
            "state": secrets.token_urlsafe(16),
            "appCodeChallenge": challenge,
            "appCodeChallengeMethod": "S256",
            "appNonce": nonce,
        }, separators=(",", ":")).encode())
        idp_uri = settings["idp_uri"]
        url = idp_uri + ("&" if "?" in idp_uri else "?") + urlencode({
            "client_id": settings["idp_client_id"],
            "redirect_uri": settings["idp_redirect_uri"],
            "response_type": "code",
            "scope": settings["idp_scopes"],
            "state": state,
        })
        return cls(
            url=url, state=state, code_verifier=verifier, code_challenge=challenge,
            nonce=nonce, client_id=client_id, issuer_id=settings["idp_issuer_id"],
            idp_redirect_uri=settings["idp_redirect_uri"],
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoginRequest":
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def extract_code(self, pasted: str) -> str:
        """Code Decathlon depuis l'URL de la page d'erreur collée (ou le code seul)."""
        pasted = (pasted or "").strip()
        if not pasted:
            raise GeocoverLoginError("Rien n'a été collé.")
        if "code=" not in pasted:
            if "/" in pasted or "?" in pasted or " " in pasted:
                raise GeocoverLoginError("Aucun paramètre code= dans l'adresse collée.")
            return pasted
        query = urlparse(pasted).query or pasted.split("?", 1)[-1]
        params = parse_qs(query)
        code = params.get("code", [""])[0]
        state = params.get("state", [None])[0]
        if not code:
            raise GeocoverLoginError("Paramètre code vide dans l'adresse collée.")
        if state is not None and state != self.state:
            raise GeocoverLoginError("Cette adresse ne correspond pas à la connexion en cours "
                                     "(state différent) : relancez la connexion.")
        return code

    def idp_exchange_payload(self, idp_code: str) -> Dict[str, Any]:
        """Étape 1 : corps JSON de POST /oauth (identique à la page login.ids)."""
        return {
            "client_id": self.client_id,
            "issuer_id": self.issuer_id,
            "code": idp_code,
            "redirect_uri": APP_REDIRECT_URI,
            "idp_redirect_uri": self.idp_redirect_uri,
            "grant_type": "idp_authorization_code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "nonce": self.nonce,
        }

    def token_payload(self, code: str, client_secret: str) -> Dict[str, str]:
        """Étape 2 : formulaire de POST /oauth (ce que fait AppAuth dans l'app)."""
        return {
            "client_id": self.client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": APP_REDIRECT_URI,
            "code_verifier": self.code_verifier,
        }
