"""OAuth for an MCP server that requires a login (the public database MCP): dynamic client registration and an
authorization code with PKCE, logged in once with `mcp-login`, then kept fresh with the refresh token.

The browser that logs in can be on another machine than the benchmark: the redirect goes to a local address that
needn't load, and the URL it lands on is pasted back. Tokens are stored in a private file outside results/
(`MCP_OAUTH_FILE`, default `.mcp-oauth.json`, gitignored) and masked wherever results are written.
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .persist import secret_file_lock, write_secret_json
from .redact import add_secret

DEFAULT_FILE = ".mcp-oauth.json"
REDIRECT_URI = "http://127.0.0.1:8976/callback"
CLIENT_NAME = "cbioportal-mcp-qa"
# Renew this long before the access token expires.
EXPIRY_MARGIN_S = 120


def token_file() -> Path:
    return Path(os.environ.get("MCP_OAUTH_FILE") or DEFAULT_FILE)


def discover(resource_url: str, http: httpx.Client) -> dict:
    """The authorization server metadata for an MCP endpoint (RFC 9728 protected resource, then RFC 8414)."""
    u = urlparse(resource_url)
    origin = f"{u.scheme}://{u.netloc}"
    resource = http.get(f"{origin}/.well-known/oauth-protected-resource{u.path}")
    resource.raise_for_status()
    issuer = resource.json()["authorization_servers"][0].rstrip("/")
    i = urlparse(issuer)
    meta = http.get(f"{i.scheme}://{i.netloc}/.well-known/oauth-authorization-server{i.path}")
    meta.raise_for_status()
    return meta.json() | {"scopes": resource.json().get("scopes_supported") or []}


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _code_from(pasted: str, state: str) -> str:
    """The authorization code from the pasted redirect URL (or the bare code)."""
    pasted = pasted.strip()
    if "://" not in pasted and "?" not in pasted:
        return pasted
    query = parse_qs(urlparse(pasted).query)
    if "error" in query:
        raise RuntimeError(f"login failed: {query['error'][0]} {query.get('error_description', [''])[0]}")
    if query.get("state", [None])[0] != state:
        raise RuntimeError("login failed: the pasted URL is from another login attempt (state mismatch)")
    if "code" not in query:
        raise RuntimeError("no ?code= in the pasted URL")
    return query["code"][0]


def login(resource_url: str, ask=input, say=print, path: Path | None = None) -> Path:
    """Register a client, have the user log in in a browser, store the tokens. Returns the token file."""
    path = path or token_file()
    with httpx.Client(timeout=30) as http:
        meta = discover(resource_url, http)
        scope = " ".join(meta["scopes"])
        reg = http.post(
            meta["registration_endpoint"],
            json={
                "client_name": CLIENT_NAME,
                "redirect_uris": [REDIRECT_URI],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
                "scope": scope,
            },
        )
        reg.raise_for_status()
        client = reg.json()
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(16)
        params = {
            "response_type": "code",
            "client_id": client["client_id"],
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": scope,
            "resource": resource_url,
        }
        say(
            f"Open this URL in a browser and log in:\n\n  {meta['authorization_endpoint']}?{urlencode(params)}\n"
        )
        say(
            f"It then redirects to {REDIRECT_URI}?code=... — that page won't load unless the benchmark runs on "
            "the same machine as the browser; copy the URL from the address bar."
        )
        code = _code_from(ask("Paste the URL it redirected to: "), state)
        resp = http.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "client_id": client["client_id"],
                **({"client_secret": client["client_secret"]} if client.get("client_secret") else {}),
                "resource": resource_url,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"token exchange failed: HTTP {resp.status_code}")
    stored = {
        "resource": resource_url,
        "token_endpoint": meta["token_endpoint"],
        "client_id": client["client_id"],
        "client_secret": client.get("client_secret"),
        **_tokens(resp.json()),
    }
    write_secret_json(path, stored)
    return path


def _tokens(payload: dict, previous: dict | None = None) -> dict:
    if not payload.get("access_token"):
        raise RuntimeError("the token endpoint answered without an access token: run `mcp-login` again")
    return {
        "access_token": payload["access_token"],
        # A refresh response may omit the refresh token: the old one stays valid.
        "refresh_token": payload.get("refresh_token") or (previous or {}).get("refresh_token"),
        "expires_at": time.time() + float(payload.get("expires_in") or 3600),
    }


class OAuthTokens:
    """The access token for one MCP endpoint from the token file, renewed with the refresh token when it is about
    to expire or the server rejected it. Safe across threads and processes: a renewal happens under a file lock,
    after re-reading the file, so a token another process already renewed (and its rotated refresh token) is used
    rather than renewed again. Renewals are written back to the file."""

    def __init__(self, resource_url: str, path: Path | None = None):
        self.path = path or token_file()
        self.resource_url = resource_url
        if not self.path.is_file():
            raise RuntimeError(
                f"no MCP login for {resource_url}: run `cbioportal-mcp-qa mcp-login` first ({self.path} missing)"
            )
        self.data = json.loads(self.path.read_text())
        if self.data.get("resource", "").rstrip("/") != resource_url.rstrip("/"):
            raise RuntimeError(
                f"{self.path} is a login for {self.data.get('resource')}, not {resource_url}; run `mcp-login` again"
            )
        self._lock = threading.Lock()
        self._mask()

    def _mask(self) -> None:
        for key in ("access_token", "refresh_token", "client_secret"):
            add_secret(self.data.get(key))

    def _expiring(self) -> bool:
        return time.time() > self.data["expires_at"] - EXPIRY_MARGIN_S

    def get(self, renew: bool = False) -> str:
        with self._lock:
            if not (renew or self._expiring()):
                return self.data["access_token"]
            rejected = self.data["access_token"]
            with secret_file_lock(self.path):
                stored = json.loads(self.path.read_text())
                if (
                    stored.get("access_token") != rejected
                    and stored.get("expires_at", 0) > self.data["expires_at"]
                ):
                    self.data = stored
                    self._mask()
                if self.data["access_token"] == rejected and (renew or self._expiring()):
                    self._refresh()
            return self.data["access_token"]

    def _refresh(self) -> None:
        if not self.data.get("refresh_token"):
            raise RuntimeError("the MCP login expired and has no refresh token: run `mcp-login` again")
        resp = httpx.post(
            self.data["token_endpoint"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.data["refresh_token"],
                "client_id": self.data["client_id"],
                **({"client_secret": self.data["client_secret"]} if self.data.get("client_secret") else {}),
                "resource": self.resource_url,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"renewing the MCP login failed (HTTP {resp.status_code}): run `cbioportal-mcp-qa mcp-login` again"
            )
        self.data |= _tokens(resp.json(), self.data)
        self._mask()
        write_secret_json(self.path, self.data)
