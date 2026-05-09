"""OAuth 2.0 Authorization Code + PKCE flow for OpenStreetMap API (OOB redirect)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from urllib.parse import urlencode

import httpx

from .config import (
    CREDENTIALS_PATH,
    OAUTH_REDIRECT_URI,
    OSM_AUTH_URL,
    OSM_TOKEN_URL,
    TOKEN_PATH,
    ensure_config_dirs,
)


def _generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def load_credentials() -> dict:
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"No credentials file found at {CREDENTIALS_PATH}\n"
            f"Create it with your OAuth client_id and client_secret:\n"
            f'{{"client_id": "YOUR_ID", "client_secret": "YOUR_SECRET"}}'
        )
    with CREDENTIALS_PATH.open("r", encoding="utf-8") as fh:
        creds = json.load(fh)
    if "client_id" not in creds:
        raise ValueError("credentials.json missing 'client_id'")
    return creds


def load_token() -> dict | None:
    if not TOKEN_PATH.exists():
        return None
    try:
        with TOKEN_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def save_token(token_data: dict) -> None:
    ensure_config_dirs()
    with TOKEN_PATH.open("w", encoding="utf-8") as fh:
        json.dump(token_data, fh, indent=2)
    if os.name != "nt":
        os.chmod(TOKEN_PATH, 0o600)


def get_access_token() -> str | None:
    token = load_token()
    if token is None:
        return None
    return token.get("access_token")


def build_auth_url() -> tuple[str, str, str]:
    """Build the OAuth authorization URL. Returns (url, verifier, state).

    The ``state`` value is generated per RFC 6749 §10.12 conventions but
    is **not** validated as a request/callback binding in this codebase.
    Reason: this client uses the out-of-band redirect URI
    ``urn:ietf:wg:oauth:2.0:oob``, where the user manually pastes the
    authorization code from the provider's response page. There is no
    redirect for the server to inspect, so there is nothing to compare
    the issued ``state`` against. The CSRF protection that ``state``
    provides for redirect-based flows therefore does not apply here;
    the actual protection is PKCE (RFC 7636), which binds the code
    exchange to a verifier never exposed to the browser.

    A future migration to a localhost callback redirect URI would let
    the server validate ``state`` properly. Until then, ``state`` is
    generated for protocol completeness, not enforcement.
    """
    creds = load_credentials()
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    params = urlencode({
        "client_id": creds["client_id"],
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "write_api read_prefs",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"{OSM_AUTH_URL}?{params}", verifier, state


def exchange_code(code: str, verifier: str) -> dict:
    """Exchange an authorization code for tokens and save them."""
    creds = load_credentials()
    payload = {
        "grant_type": "authorization_code",
        "client_id": creds["client_id"],
        "code": code,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "code_verifier": verifier,
    }
    if creds.get("client_secret"):
        payload["client_secret"] = creds["client_secret"]

    with httpx.Client() as client:
        resp = client.post(
            OSM_TOKEN_URL,
            data=payload,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        token_data = resp.json()

    save_token(token_data)
    return token_data


def login() -> dict:
    """Interactive CLI login — opens browser, prompts for code."""
    import webbrowser

    url, verifier, state = build_auth_url()
    print("Opening browser for OSM authorization...")
    # CodeQL flags the next line as `py/clear-text-logging-sensitive-data`
    # because `url` flows from `build_auth_url()`. Per RFC 6749 §4.1.1 the
    # OAuth 2.0 authorization URL contains no secrets — only the public
    # client_id, redirect_uri, scope, response_type, the SHA-256
    # `code_challenge` (a one-way hash of the secret PKCE verifier), and
    # the CSRF `state` token. The PKCE verifier itself never leaves this
    # process. Suppressing the alert at source so it stops re-triggering.
    print(f"  If the browser doesn't open, visit:\n  {url}")  # lgtm[py/clear-text-logging-sensitive-data]
    webbrowser.open(url)

    code = input("\nPaste the authorization code here: ").strip()
    if not code:
        raise RuntimeError("No authorization code provided.")

    token_data = exchange_code(code, verifier)
    print("Authentication successful. Token saved.")
    return token_data
