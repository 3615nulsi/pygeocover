"""pygeocover exceptions.

Every exception raised by the library derives from `GeocoverError`.
"""
from __future__ import annotations

from typing import Optional


class GeocoverError(Exception):
    """Base class."""


class GeocoverConnectionError(GeocoverError):
    """Server unreachable or timeout (transient)."""


class GeocoverAuthError(GeocoverError):
    """Tokens rejected or expired: the user must sign in again."""


class GeocoverLoginError(GeocoverError):
    """Sign-in failed (expired code, invalid pasted address…)."""


class GeocoverResponseError(GeocoverError):
    """The server answered, but not with the expected format (API change?)."""


class GeocoverApiError(GeocoverError):
    """Error response of the API (other than authentication).

    `error` is the OAuth error code (e.g. ``invalid_grant``) when the body has one;
    `retry_after` is the delay requested by the server, in seconds, if any.
    """

    def __init__(
        self,
        status: int,
        detail: str = "",
        *,
        error: Optional[str] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(f"HTTP {status}: {detail}" if detail else f"HTTP {status}")
        self.status = status
        self.detail = detail
        self.error = error
        self.retry_after = retry_after


class GeocoverRateLimitError(GeocoverApiError):
    """HTTP 429: too many requests; wait `retry_after` seconds if given."""
