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

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import API_BASE, USER_AGENT

_LOGGER = logging.getLogger(__name__)


class OrangeError(Exception):
    """Base error for the Orange client."""


class OrangeAuthError(OrangeError):
    """Raised when the session cookie is missing/expired/invalid."""


class OrangeApiClient:
    """Calls the My Orange endpoints the web dashboard uses."""

    def __init__(self, session: ClientSession, cookie: str) -> None:
        self._session = session
        self._cookie = cookie.strip()

    @property
    def cookie(self) -> str:
        return self._cookie

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Cookie": self._cookie,
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.orange.ro/myaccount/reshape/",
        }

    async def _get(self, path: str) -> Any:
        """GET ``{API_BASE}/{path}`` and return parsed JSON."""
        url = f"{API_BASE}/{path.lstrip('/')}"
        try:
            async with self._session.get(
                url, headers=self._headers(), allow_redirects=False
            ) as resp:
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
