"""Mobile-app OAuth2 login for My Orange.

Replaces the old browser/cookie login. We authenticate the way the MyOrange
Android app does — a password grant against ``/accounts/token`` using the app's
built-in client credentials — and then keep a refresh token for silent renewal.
No cookies, no reCAPTCHA, no 2FA, so the session persists indefinitely.

Auth flow + client credentials adapted from HAForgeLabs/utilitati_romania
(MIT, © 2026 Marius Onițiu; portions © Cristian Necrea).
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_DNS, uuid4, uuid5

from aiohttp import ClientError, ClientSession, ClientTimeout

from .api import OrangeAuthError, OrangeError
from .const import (
    APP_USER_AGENT,
    APP_VERSION,
    ENDPOINT_TOKEN,
    OAUTH_BASE,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OAUTH_SCOPE,
)

_LOGGER = logging.getLogger(__name__)


class OrangeOAuth:
    """Holds the OAuth session and mints/refreshes access tokens on demand."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        refresh_token: str | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = refresh_token
        self._expires_at: int | None = None
        self._device_id = str(
            uuid5(NAMESPACE_DNS, f"ha-orange-ro-{username.lower().strip()}")
        )
        self._profile_session_id = uuid4().hex.upper()

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    @property
    def profile_session_id(self) -> str:
        return self._profile_session_id

    def _basic_auth(self) -> str:
        raw = f"{OAUTH_CLIENT_ID}:{OAUTH_CLIENT_SECRET}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _token_valid(self) -> bool:
        if not self._access_token or not self._expires_at:
            return False
        now = int(datetime.now(tz=UTC).timestamp())
        return now < (self._expires_at - 90)

    async def async_access_token(self) -> str:
        """Return a valid bearer token, refreshing/logging in as needed."""
        if not self._token_valid():
            await self.async_login()
        assert self._access_token is not None
        return self._access_token

    def invalidate(self) -> None:
        self._access_token = None

    async def async_login(self) -> None:
        """Obtain tokens — refresh grant first, falling back to password grant."""
        if self._refresh_token:
            try:
                await self._request_token(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": self._refresh_token,
                        "scope": OAUTH_SCOPE,
                    }
                )
                return
            except OrangeAuthError:
                _LOGGER.debug("Orange refresh token rejected; falling back to password")
                self._refresh_token = None

        await self._request_token(
            {
                "access_type": "offline",
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
                "scope": OAUTH_SCOPE,
            }
        )

    async def _request_token(self, payload: dict[str, Any]) -> None:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Authorization": self._basic_auth(),
            "Content-Type": "application/json",
            "User-Agent": APP_USER_AGENT,
            "X-App-Version": APP_VERSION,
            "X-Device-Id": self._device_id,
            "X-Device-Model": "Home Assistant",
            "X-Device-Os": "Android: 25 (7.1.2)",
        }
        try:
            async with self._session.post(
                f"{OAUTH_BASE}{ENDPOINT_TOKEN}",
                headers=headers,
                json=payload,
                timeout=ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                if resp.status in (400, 401, 403):
                    raise OrangeAuthError(f"Orange login failed: HTTP {resp.status}")
                if resp.status >= 400:
                    raise OrangeError(f"Orange token HTTP {resp.status}: {text[:300]}")
                data = await resp.json(content_type=None)
        except ClientError as err:
            raise OrangeError(f"Network error during Orange login: {err}") from err

        access = str((data or {}).get("access_token") or "").strip()
        if not access:
            raise OrangeAuthError("Orange login failed: no access_token")
        try:
            expires_in = int(data.get("expires_in") or 3599)
        except (TypeError, ValueError):
            expires_in = 3599

        self._access_token = access
        self._refresh_token = str(data.get("refresh_token") or "").strip() or self._refresh_token
        self._expires_at = int(datetime.now(tz=UTC).timestamp()) + max(expires_in, 300)
