"""
GitHub App authentication — mint App JWTs and exchange for installation access tokens.
All GitHub API calls go through here; tokens are cached until expiry.
Never expose tokens to the browser.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_cached_token: str | None = None
_token_expires_at: float = 0.0


def _get_settings():
    from django.conf import settings
    return settings


def mint_app_jwt() -> str:
    """Create a short-lived GitHub App JWT (RS256, valid 10 minutes)."""
    try:
        import jwt  # PyJWT
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as e:
        raise RuntimeError(
            "PyJWT and cryptography are required for GitHub App auth. "
            "Install them: pip install PyJWT cryptography"
        ) from e

    s = _get_settings()
    if not s.GITHUB_APP_ID or not s.GITHUB_APP_PRIVATE_KEY:
        raise RuntimeError(
            "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must be set in settings/env."
        )

    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued 60s ago to absorb clock drift
        "exp": now + (10 * 60),  # 10-minute lifetime (GitHub max)
        "iss": str(s.GITHUB_APP_ID),
    }

    private_key_pem = s.GITHUB_APP_PRIVATE_KEY
    if isinstance(private_key_pem, str):
        private_key_pem = private_key_pem.encode()

    # Support PEM content with escaped newlines from env vars
    if b"\\n" in private_key_pem:
        private_key_pem = private_key_pem.replace(b"\\n", b"\n")

    token = jwt.encode(payload, private_key_pem, algorithm="RS256")
    return token if isinstance(token, str) else token.decode()


def get_installation_token() -> str:
    """Return a valid installation access token, refreshing if needed."""
    global _cached_token, _token_expires_at

    # Tokens are valid for 1 hour; refresh 5 minutes early
    if _cached_token and time.time() < _token_expires_at - 300:
        return _cached_token

    import requests as _requests

    s = _get_settings()
    if not s.GITHUB_APP_INSTALLATION_ID:
        raise RuntimeError("GITHUB_APP_INSTALLATION_ID must be set in settings/env.")

    app_jwt = mint_app_jwt()
    resp = _requests.post(
        f"https://api.github.com/app/installations/{s.GITHUB_APP_INSTALLATION_ID}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    _cached_token = data["token"]
    # Parse expiry from response ("expires_at": "2024-01-01T00:00:00Z")
    expires_str = data.get("expires_at", "")
    if expires_str:
        try:
            dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            _token_expires_at = dt.timestamp()
        except ValueError:
            _token_expires_at = time.time() + 3600
    else:
        _token_expires_at = time.time() + 3600

    logger.info("GitHub installation token refreshed; expires at %s", expires_str)
    return _cached_token


def github_headers() -> dict:
    """Return request headers for authenticated GitHub API calls."""
    return {
        "Authorization": f"Bearer {get_installation_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
