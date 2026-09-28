"""Outil en ligne de commande : `python3 -m pygeocover <commande>`.

Commandes :
  login                 connexion interactive (navigateur + coller l'adresse de la page d'erreur)
  login-url             étape 1 seule : affiche l'URL de connexion
  login-finish URL      étape 2 seule : termine la connexion avec l'URL collée
  status                vélos : position, batterie, état, santé, dernier trajet (défaut)
  locations [HEURES]    historique des positions (24 h par défaut)
  rides [N]             N derniers trajets (5 par défaut)

Fichier de configuration JSON (option --config, défaut ./geocover.json) :
  créé au premier `login` ; les jetons y sont réécrits
  à chaque rafraîchissement (refresh_token rotatif). Fichier PRIVÉ : ne jamais le partager.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import warnings
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

# Python système macOS (LibreSSL) : avertissement urllib3/aiohttp sans conséquence ici
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import aiohttp  # noqa: E402

from .auth import LoginRequest, TokenSet  # noqa: E402
from .client import GeocoverClient  # noqa: E402
from .const import DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET  # noqa: E402
from .exceptions import GeocoverError  # noqa: E402


class Config:
    def __init__(self, path: Path) -> None:
        self.path = path
        # créé au premier `login` ; client_id/client_secret facultatifs (défauts de l'app)
        self.data: Dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)  # écriture atomique : ne jamais perdre le refresh_token

    def tokens(self) -> TokenSet | None:
        return TokenSet.from_dict(self.data) if self.data.get("refresh_token") else None

    def store_tokens(self, tokens: TokenSet) -> None:
        self.data.update(tokens.to_dict())
        self.save()


def _client(session: aiohttp.ClientSession, cfg: Config) -> GeocoverClient:
    return GeocoverClient(
        session, cfg.tokens(),
        client_id=cfg.data.get("client_id", DEFAULT_CLIENT_ID),
        client_secret=cfg.data.get("client_secret", DEFAULT_CLIENT_SECRET),
        on_tokens_updated=cfg.store_tokens,
    )


def _fmt(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%d/%m/%Y %H:%M") if dt else "—"


async def cmd_login(client: GeocoverClient, cfg: Config, interactive: bool, pasted: str = "") -> None:
    if interactive or not pasted:
        request = await client.async_start_login()
        cfg.data["pending_login"] = request.to_dict()
        cfg.save()
        if not interactive:
            print(request.url)
            return
        print("1) Connectez-vous à votre compte Decathlon dans le navigateur :\n\n   "
              + request.url + "\n")
        webbrowser.open(request.url)
        print("2) À la fin, une page « Whoops! Looks like something went wrong » s'affiche : c'est")
        print("   normal. Copiez l'adresse complète de cette page (https://login.ids.conneq.tech/")
        print("   redirect?code=…) et collez-la ici rapidement (le code expire vite).\n")
        pasted = input("Adresse de la page d'erreur : ")
    pending = cfg.data.get("pending_login")
    if not pending:
        sys.exit("Aucune connexion en cours : lancez d'abord `login-url`.")
    await client.async_finish_login(LoginRequest.from_dict(pending), pasted)
    cfg.data.pop("pending_login", None)
    cfg.save()
    print(f"[ok] connecté — jetons enregistrés dans {cfg.path}")


async def cmd_status(client: GeocoverClient) -> None:
    user = await client.async_get_user()
    print(f"Compte : {user.name} ({user.country})")
    for bike in await client.async_get_bikes():
        loc = bike.last_location
        state = await client.async_get_state(bike.id)
        health = await client.async_get_health(bike.id)
        battery = await client.async_get_battery(bike.id)
        ride = await client.async_get_latest_ride(bike.id)
        print(f"\n=== {bike.name} (id {bike.id}) ===")
        print(f"  batterie        : {bike.battery_percentage} %  (autonomie {battery.range_km} km,"
              f" en charge : {battery.charging})")
        if loc:
            print(f"  position        : {loc.lat}, {loc.lon}  le {_fmt(loc.date)}")
            print(f"  en mouvement    : {loc.is_moving}  (vitesse {loc.speed})")
        print(f"  odomètre        : {bike.odometer_km} km")
        if state:
            print(f"  allumé          : {state.powered_on}  |  verrouillé : {state.ecu_locked}")
        print(f"  dernière connexion : {_fmt(health.last_connection)}  |  dernier GPS : "
              f"{_fmt(health.last_gps)}  |  batterie traceur : {health.gps_battery} %")
        for g in bike.geofences:
            print(f"  géofence        : {g.name} ({g.lat}, {g.lon}, r={g.radius} m, active={g.active})")
        if ride:
            print(f"  dernier trajet  : {_fmt(ride.start_date)} → {_fmt(ride.end_date)}, "
                  f"{ride.distance_km} km, {ride.avg_speed} km/h, +{ride.elevation_up} m")


async def cmd_locations(client: GeocoverClient, hours: int) -> None:
    end = datetime.now(timezone.utc)
    for bike in await client.async_get_bikes():
        points = await client.async_get_locations(bike.id, end - timedelta(hours=hours), end)
        print(f"=== {bike.name} : {len(points)} positions sur {hours} h ===")
        for p in points:
            print(f"  {_fmt(p.date)}  {p.lat:.6f}, {p.lon:.6f}  v={p.speed}  mouvement={p.is_moving}")


async def cmd_rides(client: GeocoverClient, count: int) -> None:
    for bike in await client.async_get_bikes():
        page = await client.async_get_rides(bike.id, limit=count)
        print(f"=== {bike.name} : {page.total} trajets au total, {len(page.rides)} derniers ===")
        for r in page.rides:
            minutes = round((r.active_time_s or 0) / 60)
            print(f"  {_fmt(r.start_date)}  {r.distance_km:>6} km  {minutes:>3} min  "
                  f"{r.avg_speed} km/h  +{r.elevation_up}/-{r.elevation_down} m")


async def run(args: argparse.Namespace) -> None:
    cfg = Config(Path(args.config))
    async with aiohttp.ClientSession() as session:
        client = _client(session, cfg)
        if args.command == "login":
            await cmd_login(client, cfg, interactive=True)
        elif args.command == "login-url":
            await cmd_login(client, cfg, interactive=False)
        elif args.command == "login-finish":
            if not args.arg:
                sys.exit("Usage : login-finish '<adresse de la page d'erreur>'")
            await cmd_login(client, cfg, interactive=False, pasted=args.arg)
        elif cfg.tokens() is None:
            sys.exit("Pas encore connecté : lancez `python3 -m pygeocover login`.")
        elif args.command == "locations":
            await cmd_locations(client, int(args.arg or 24))
        elif args.command == "rides":
            await cmd_rides(client, int(args.arg or 5))
        else:
            await cmd_status(client)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pygeocover", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="status",
                        choices=["login", "login-url", "login-finish", "status", "locations", "rides"])
    parser.add_argument("arg", nargs="?")
    parser.add_argument("--config", default=os.environ.get("PYGEOCOVER_CONFIG", "geocover.json"))
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except GeocoverError as err:
        sys.exit(f"Erreur : {err}")


if __name__ == "__main__":
    main()
