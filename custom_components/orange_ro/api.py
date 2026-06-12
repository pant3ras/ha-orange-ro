"""Thin async client for the My Orange (orange.ro) JSON API.

Authentication is by session cookie: the user logs in through a browser and
pastes the ``Cookie`` request header. We replay that header verbatim on every
call. When the session expires Orange answers 401/403 (or redirects the API
call to an HTML login page), which we surface as ``OrangeAuthError`` so the
coordinator can drive a re-auth flow.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import API_BASE, USER_AGENT

_LOGGER = logging.getLogger(__name__)

# Browser entry point whose redirect chain re-mints an API session from the
# long-lived SSO cookies (served from /accounts on the same host).
REFRESH_URL = "https://www.orange.ro/myaccount/reshape/"
_MAX_REFRESH_HOPS = 15


class OrangeError(Exception):
    """Base error for the Orange client."""


class OrangeAuthError(OrangeError):
    """Raised when the session cookie is missing/expired/invalid."""


def _parse_cookie(header: str) -> dict[str, str]:
    """Parse a raw ``Cookie`` header string into an ordered name->value dict."""
    cookies: dict[str, str] = {}
    for part in (header or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


class OrangeApiClient:
    """Calls the My Orange endpoints the web dashboard uses."""

    def __init__(self, session: ClientSession, cookie: str) -> None:
        self._session = session
        self._cookies = _parse_cookie(cookie)

    @property
    def cookie(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    def update_cookie(self, cookie: str) -> None:
        """Replace the stored cookies (used after a re-auth / re-login)."""
        self._cookies = _parse_cookie(cookie)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Cookie": self.cookie,
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.orange.ro/myaccount/reshape/",
        }

    def _absorb(self, resp: ClientResponse) -> None:
        """Merge any rotated Set-Cookie values so the session stays valid.

        Orange's F5/ASP.NET stack hands back refreshed session cookies (TS*,
        ASP.NET_SessionId, ...) on most responses. Replaying the original stale
        cookie is what makes the session die after a few minutes, so we keep the
        jar current by absorbing each response's Set-Cookie.
        """
        for name, morsel in resp.cookies.items():
            if morsel.value:
                self._cookies[name] = morsel.value

    def _headers_html(self) -> dict[str, str]:
        """Headers for browser-style page navigation (the SSO redirect chain)."""
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cookie": self.cookie,
            "User-Agent": USER_AGENT,
        }

    async def async_refresh_session(self) -> None:
        """Re-mint the API session by replaying the SSO redirect chain.

        The myaccount API session is short-lived, but the SSO cookies under
        /accounts last much longer. Loading the reshape entry URL makes the
        server walk the OAuth redirect dance and, while the SSO session holds,
        hand back a brand-new API session without ever showing a login form —
        the same thing a browser does when revisiting the page after idling.
        We follow the chain hop by hop so every rotated Set-Cookie is absorbed.

        Raises OrangeAuthError if we land on the login form (SSO expired too).
        """
        url = REFRESH_URL
        for _ in range(_MAX_REFRESH_HOPS):
            try:
                async with self._session.get(
                    url, headers=self._headers_html(), allow_redirects=False
                ) as resp:
                    self._absorb(resp)
                    location = resp.headers.get("Location")
                    if resp.status in (301, 302, 303, 307, 308) and location:
                        url = urljoin(url, location)
                        continue
                    body = await resp.text()
            except ClientError as err:
                raise OrangeError(
                    f"Network error refreshing session at {url}: {err}"
                ) from err
            if "data-expected-kid" in body or "login-user" in body:
                raise OrangeAuthError(
                    "SSO session expired as well — a fresh cookie/login is required"
                )
            _LOGGER.debug("Session re-minted via SSO redirect chain (%s)", url)
            return
        raise OrangeError("Session refresh did not converge (redirect loop)")

    async def _get(self, path: str) -> Any:
        """GET ``{API_BASE}/{path}`` and return parsed JSON."""
        url = f"{API_BASE}/{path.lstrip('/')}"
        try:
            async with self._session.get(
                url, headers=self._headers(), allow_redirects=False
            ) as resp:
                self._absorb(resp)
                return await self._parse(resp, url)
        except ClientError as err:
            raise OrangeError(f"Network error calling {url}: {err}") from err

    @staticmethod
    async def _parse(resp: ClientResponse, url: str) -> Any:
        # An expired session is bounced to the login page (302) or rejected.
        if resp.status in (301, 302, 303, 307, 308):
            raise OrangeAuthError(f"Session expired (redirect from {url})")
        if resp.status in (401, 403):
            raise OrangeAuthError(f"Not authorized for {url} (HTTP {resp.status})")
        if resp.status == 404:
            return None
        if resp.status >= 400:
            raise OrangeError(f"HTTP {resp.status} for {url}")

        ctype = resp.headers.get("Content-Type", "")
        if "json" not in ctype:
            # The API only ever returns JSON when authenticated; HTML here means
            # we were silently served the login/landing page.
            raise OrangeAuthError(f"Non-JSON response from {url} (likely logged out)")
        return await resp.json(content_type=None)

    # -- Individual endpoints -------------------------------------------------

    async def async_get_user_data(self) -> dict[str, Any] | None:
        return await self._get("v4/userData")

    async def async_get_profiles(self) -> dict[str, Any] | None:
        return await self._get("v4/profiles")

    async def async_get_customer_info(self, profile_id: int | str) -> dict[str, Any] | None:
        return await self._get(f"v4/profile/{profile_id}/customerInfo")

    async def async_get_invoice_info(self, profile_id: int | str) -> dict[str, Any] | None:
        return await self._get(f"v4/profile/{profile_id}/invoiceInfo")

    async def async_get_installments(self, profile_id: int | str) -> Any:
        return await self._get(f"v4/profiles/{profile_id}/installmentsNew")

    async def async_get_subscribers(self, profile_id: int | str) -> Any:
        return await self._get(f"v4/subscribers?profileId={profile_id}")

    async def async_get_subscriber(self, subscriber_id: int | str) -> dict[str, Any] | None:
        return await self._get(f"v4/subscribers/{subscriber_id}")

    async def async_get_cronos(self, msisdn: str) -> dict[str, Any] | None:
        return await self._get(f"v4/{msisdn}/cronos")

    async def async_get_msisdn_extra(self, msisdn: str) -> dict[str, Any] | None:
        return await self._get(f"v4/msisdnExtraInfo/{msisdn}")

    async def async_get_transactions(self, profile_id: int | str) -> dict[str, Any] | None:
        return await self._get(f"v4/profiles/{profile_id}/transactions")

    # -- Validation -----------------------------------------------------------

    async def async_validate(self) -> dict[str, Any]:
        """Confirm the cookie is valid and return the logged-in user block.

        Raises OrangeAuthError if not logged in.
        """
        data = await self.async_get_user_data()
        user = (data or {}).get("data", {})
        if not user or not user.get("isUserLogged"):
            raise OrangeAuthError("Cookie did not resolve to a logged-in user")
        return user
