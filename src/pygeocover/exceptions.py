"""Exceptions de pygeocover."""
from __future__ import annotations


class GeocoverError(Exception):
    """Erreur de base."""


class GeocoverConnectionError(GeocoverError):
    """Serveur injoignable ou délai dépassé (erreur transitoire)."""


class GeocoverAuthError(GeocoverError):
    """Jetons invalides ou expirés : une nouvelle connexion est nécessaire."""


class GeocoverLoginError(GeocoverError):
    """Échec de la connexion (code expiré, URL collée invalide…)."""


class GeocoverApiError(GeocoverError):
    """Réponse d'erreur de l'API (hors authentification)."""

    def __init__(self, status: int, detail: str = "") -> None:
        super().__init__(f"HTTP {status}: {detail}" if detail else f"HTTP {status}")
        self.status = status
        self.detail = detail
