# pygeocover

Client Python **asynchrone** (aiohttp) non officiel pour l'API grand public
**Decathlon Geocover** (plateforme Conneqtech), destiné à l'intégration Home Assistant.

## Installation locale
```bash
python3 -m pip install --user -e ".[test]"
```

## Ligne de commande
Configuration : `geocover.json` dans le dossier courant (ou `--config`, ou `$PYGEOCOVER_CONFIG`),
créé au premier `login` et contenant vos jetons. **Fichier privé**, ignoré par git.

```bash
python3 -m pygeocover login          # connexion (voir ci-dessous)
python3 -m pygeocover                # état : position, batterie, santé, dernier trajet
python3 -m pygeocover rides 10       # 10 derniers trajets
python3 -m pygeocover locations 24   # positions des dernières 24 h
```

### Connexion
Le navigateur s'ouvre sur la connexion Decathlon. À la fin, une page Conneqtech
« Whoops! Looks like something went wrong » s'affiche : **c'est voulu**. Copiez son adresse
(`https://login.ids.conneq.tech/redirect?code=…`) et collez-la dans le terminal rapidement.
Explication technique dans `auth.py`.

## Utilisation en Python
```python
import aiohttp
from pygeocover import GeocoverClient, TokenSet

async with aiohttp.ClientSession() as session:
    client = GeocoverClient(session,
                            TokenSet.from_dict(saved),          # ou None avant connexion
                            on_tokens_updated=persist)          # OBLIGATOIRE : refresh_token rotatif
    # connexion : req = await client.async_start_login(); ouvrir req.url ;
    #             await client.async_finish_login(req, url_collee)
    bikes = await client.async_get_bikes()   # position + batterie + odomètre + géofences
```

| Méthode | Endpoint |
|---|---|
| `async_get_user()` | `GET user/me` |
| `async_get_bikes()` / `async_get_bike(id)` | `GET bike`, `GET bike/{id}` |
| `async_get_locations(id, start, end)` | `GET bike/{id}/location?from=&till=` (ISO 8601) |
| `async_get_battery(id)` | `GET bike/{id}/battery/current-state` |
| `async_get_state(id)` | `GET bike/{id}/state` |
| `async_get_health(id)` | `GET bike/{id}/health` |
| `async_get_geofences(id)` | `GET bike/{id}/geofence` |
| `async_get_rides(id, limit, offset)` / `async_get_latest_ride(id)` | `GET v2/bike/{id}/ride` |

Exceptions : `GeocoverAuthError` (reconnexion nécessaire), `GeocoverConnectionError`
(transitoire), `GeocoverApiError`, `GeocoverLoginError`.

## Points d'attention
- **refresh_token rotatif à usage unique** : chaque rafraîchissement l'invalide ; le client appelle
  `on_tokens_updated` à chaque nouveau jeton, l'appelant doit le persister immédiatement.
  Un même refresh_token ne doit être utilisé que par **un seul** programme à la fois.
- `Accept: application/json` obligatoire (sinon HTTP 406) — géré par le client.
- Trajets : tri par `order=start_date;desc` (syntaxe `champ;sens` trouvée dans l'APK,
  service `n1`) ; sans ce paramètre le serveur renvoie du plus ancien au plus récent.
  Filtres (non utilisés) au format `filter[]=or;bike_id;eq;<id>`.
- `client_id` / `client_secret` : ceux de l'app Android, identiques pour tous ses utilisateurs, inclus
  par défaut (secret « non confidentiel » au sens de la RFC 8252 §8.5). Surchargeables.

## Tests
```bash
PYTHONPATH=src python3 -m pytest -q
```
