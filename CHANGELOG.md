# Changelog

## [0.2.0] - unreleased

### Added
- `GeocoverResponseError`: raised instead of `KeyError`/`TypeError`/`ValueError`… when a
  response does not have the expected format (bikes, rides, tokens, login settings, JSON).
- `GeocoverRateLimitError` for HTTP 429; every `GeocoverApiError` now carries `error`
  (OAuth error code) and `retry_after` (seconds, from the `Retry-After` header).
- `language` parameter of `GeocoverClient` (`Accept-Language`, `fr` by default).
- `const.LOGIN_REDIRECT_URL`: address of the "Whoops!" page that ends the sign-in.

### Changed
- A refresh token is considered rejected (`GeocoverAuthError`) only on `invalid_grant`,
  401 or 403: other errors of the token endpoint no longer force a new sign-in.
- An unexpected answer to the code exchange raises `GeocoverResponseError`
  (was `GeocoverLoginError`).
- A ride list answered with HTTP 204 is treated as empty.
- Exception and log messages are in English.

## [0.1.0]
- First release.
