"""Constantes de l'API Geocover (Conneqtech, marque blanche Decathlon)."""
from __future__ import annotations

DEFAULT_BRAND = "decathlon"

# Client OAuth de l'app Android com.conneqtech.decathlon, identique pour tous ses utilisateurs.
# Secret embarqué dans une app publique : non confidentiel au sens de la RFC 8252 §8.5.
DEFAULT_CLIENT_ID = "5c0d36ce-7396-46f0-bcc0-3c6e16c0d2b6"
DEFAULT_CLIENT_SECRET = "_NU4.j2A!f!YawfpDFKdWBDQemuMtrYa"
APP_REDIRECT_URI = "tech.conneq.decathlon://decathlon.app.ids.conneq.tech"

IDS_API = "https://api.ids.conneq.tech"
TOKEN_URL = IDS_API + "/oauth"

# redirectURI placée dans le `state` de login : volontairement non autorisée pour que
# la page login.ids.conneq.tech échoue sans consommer le code Decathlon (voir auth.py).
UNROUTABLE_REDIRECT_URI = "https://localhost/pygeocover"

# marge avant expiration à partir de laquelle on rafraîchit l'access_token (s)
TOKEN_REFRESH_MARGIN = 300
REQUEST_TIMEOUT = 30


def bike_api_url(brand: str = DEFAULT_BRAND) -> str:
    return f"https://{brand}.api.bike.conneq.tech/"
