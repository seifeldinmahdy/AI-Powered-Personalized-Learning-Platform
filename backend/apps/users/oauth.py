"""
Social OAuth — backend half of the authorization-code flow.

Each provider helper takes the `code` + `redirect_uri` the frontend used and
returns a normalized identity dict: {"email": str, "name": str}.

Client secrets are read from the environment (never sent to the browser):
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
    GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET
    FACEBOOK_CLIENT_ID / FACEBOOK_CLIENT_SECRET
"""

from __future__ import annotations

import os

import requests

TIMEOUT = 10


class OAuthError(Exception):
    """Raised when a provider exchange fails or returns no usable email."""


def _provider_credentials(provider: str) -> tuple[str, str]:
    key = provider.upper()
    client_id = os.getenv(f"{key}_CLIENT_ID", "")
    client_secret = os.getenv(f"{key}_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise OAuthError(f"{provider} sign-in is not configured on the server.")
    return client_id, client_secret


def _google(code: str, redirect_uri: str) -> dict:
    client_id, client_secret = _provider_credentials("google")
    token_res = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=TIMEOUT,
    )
    if not token_res.ok:
        raise OAuthError("Google rejected the authorization code.")
    access_token = token_res.json().get("access_token")
    if not access_token:
        raise OAuthError("Google did not return an access token.")

    info = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=TIMEOUT,
    ).json()
    email = info.get("email")
    if not email:
        raise OAuthError("Google account did not expose an email address.")
    return {"email": email, "name": info.get("name") or email.split("@")[0]}


def _github(code: str, redirect_uri: str) -> dict:
    client_id, client_secret = _provider_credentials("github")
    token_res = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=TIMEOUT,
    )
    if not token_res.ok:
        raise OAuthError("GitHub rejected the authorization code.")
    access_token = token_res.json().get("access_token")
    if not access_token:
        raise OAuthError("GitHub did not return an access token.")

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    profile = requests.get("https://api.github.com/user", headers=headers, timeout=TIMEOUT).json()
    email = profile.get("email")
    if not email:
        # Primary email may be private — fetch it from the emails endpoint.
        emails = requests.get("https://api.github.com/user/emails", headers=headers, timeout=TIMEOUT).json()
        if isinstance(emails, list):
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            verified = next((e for e in emails if e.get("verified")), None)
            email = (primary or verified or {}).get("email")
    if not email:
        raise OAuthError("No verified email found on the GitHub account.")
    name = profile.get("name") or profile.get("login") or email.split("@")[0]
    return {"email": email, "name": name}


def _facebook(code: str, redirect_uri: str) -> dict:
    client_id, client_secret = _provider_credentials("facebook")
    token_res = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=TIMEOUT,
    )
    if not token_res.ok:
        raise OAuthError("Facebook rejected the authorization code.")
    access_token = token_res.json().get("access_token")
    if not access_token:
        raise OAuthError("Facebook did not return an access token.")

    profile = requests.get(
        "https://graph.facebook.com/me",
        params={"fields": "id,name,email", "access_token": access_token},
        timeout=TIMEOUT,
    ).json()
    email = profile.get("email")
    if not email:
        raise OAuthError("Facebook account did not share an email address.")
    return {"email": email, "name": profile.get("name") or email.split("@")[0]}


_HANDLERS = {"google": _google, "github": _github, "facebook": _facebook}


def fetch_identity(provider: str, code: str, redirect_uri: str) -> dict:
    """Resolve an OAuth code to {"email", "name"} for the given provider."""
    handler = _HANDLERS.get(provider)
    if handler is None:
        raise OAuthError(f"Unsupported provider: {provider}")
    return handler(code, redirect_uri)
