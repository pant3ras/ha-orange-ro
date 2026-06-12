"""My Orange data client.

Authenticates with the mobile-app OAuth bearer token (see ``auth.py``) and
assembles the account snapshot the sensors consume. Core billing comes from the
mobile **v5** API (reliable with the bearer token); the richer per-line and
loyalty fields come from the legacy **v4** web API, fetched best-effort with the
same bearer token (they populate the extra sensors if the gateway accepts the
token, otherwise those sensors simply go unavailable).

The snapshot keeps the original v4-shaped structure so the sensor platform is
unchanged::

    {
      "user": {...},
      "profiles": {
        <profile_id>: {
          "info": {"name", "id"},
          "customer": {...},        # v4 customerInfo (Thank You)
          "invoice": {...},         # billing (v5, dates normalised to ms)
          "installments": [...],    # v4
          "transactions": [...],    # v4
          "subscribers": {
            <subscriber_id>: {"summary", "detail", "cronos", "extra"}
          }
        }
      }
    }
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from uuid import uuid4

from .const import (
    API_BASE_V4,
    APP_USER_AGENT,
    APP_VERSION,
    ENDPOINT_INVOICE_INFO,
    ENDPOINT_SUBSCRIBERS,
    ENDPOINT_USER_INFO,
    OAUTH_BASE,
    USER_AGENT,
)

if TYPE_CHECKING:
    from .auth import OrangeOAuth

_LOGGER = logging.getLogger(__name__)


class OrangeError(Exception):
    """Base error for the Orange client."""


class OrangeAuthError(OrangeError):
    """Raised when authentication fails."""


def _to_ms(value: Any) -> int | None:
    """Normalise a date/datetime/epoch value to epoch milliseconds.

    The sensors render the billing dates via an ``ms -> datetime`` helper, so we
    coerce whatever the v5 API returns (ISO string or epoch) to milliseconds.
    """
    if value is None or value == "":
        return None
    # Already numeric epoch?
    if isinstance(value, (int, float)):
        v = int(value)
        return v if v >= 10**12 else v * 1000  # seconds -> ms
    text = str(value).strip()
    if text.isdigit():
        v = int(text)
        return v if v >= 10**12 else v * 1000
    iso = text.replace("Z", "+00:00")
    # Orange sometimes uses a short "+03" offset on datetimes (never on plain
    # dates, so guard on the "T" to avoid mangling "YYYY-MM-DD").
    if "T" in iso and len(iso) >= 3 and iso[-3] in "+-" and iso[-2:].isdigit():
        iso = f"{iso}:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        try:
            dt = datetime.combine(date.fromisoformat(text[:10]), datetime.min.time())
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


class OrangeApiClient:
    """Reads My Orange data using an OAuth bearer token."""

    def __init__(self, session: ClientSession, auth: OrangeOAuth) -> None:
        self._session = session
        self._auth = auth

    # -- low-level requests ---------------------------------------------------

    def _mobile_headers(self, token: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "User-Agent": APP_USER_AGENT,
            "X-App-Version": APP_VERSION,
            "X-Profile-Session-Id": self._auth.profile_session_id,
            "X-Tracking-Id": str(uuid4()),
        }

    async def _get_json(
        self, endpoint: str, *, params: dict[str, Any] | None = None, retry: bool = True
    ) -> Any:
        token = await self._auth.async_access_token()
        url = endpoint if endpoint.startswith("http") else f"{OAUTH_BASE}{endpoint}"
        try:
            async with self._session.get(
                url,
                headers=self._mobile_headers(token),
                params=params,
                timeout=ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                if resp.status in (401, 403):
                    if retry:
                        self._auth.invalidate()
                        return await self._get_json(endpoint, params=params, retry=False)
                    raise OrangeAuthError(f"Unauthorized for {endpoint} (HTTP {resp.status})")
                if resp.status >= 400:
                    raise OrangeError(f"HTTP {resp.status} for {endpoint}: {text[:300]}")
                return await resp.json(content_type=None)
        except ClientError as err:
            raise OrangeError(f"Network error calling {endpoint}: {err}") from err

    async def _get_v4(self, path: str) -> Any:
        """Best-effort GET against the legacy v4 web API with the bearer token.

        Returns ``None`` on any failure (including the gateway rejecting the
        mobile token) so the optional/extra sensors degrade gracefully.
        """
        token = await self._auth.async_access_token()
        url = f"{API_BASE_V4}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.orange.ro/myaccount/reshape/",
        }
        try:
            async with self._session.get(
                url, headers=headers, timeout=ClientTimeout(total=30)
            ) as resp:
                if resp.status >= 400:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if "json" not in ctype:
                    return None
                return await resp.json(content_type=None)
        except ClientError:
            return None

    # -- v5 endpoints ---------------------------------------------------------

    async def async_user_info(self) -> dict[str, Any]:
        data = await self._get_json(ENDPOINT_USER_INFO)
        return data if isinstance(data, dict) else {}

    async def async_subscribers(self) -> list[dict[str, Any]]:
        data = await self._get_json(ENDPOINT_SUBSCRIBERS)
        lista = (data or {}).get("msisdnList") if isinstance(data, dict) else None
        return [s for s in lista if isinstance(s, dict)] if isinstance(lista, list) else []

    async def async_invoice_info(self, profile_id: str, msisdn: str) -> dict[str, Any]:
        endpoint = ENDPOINT_INVOICE_INFO.format(profile_id=profile_id, msisdn=msisdn)
        data = await self._get_json(endpoint)
        return data if isinstance(data, dict) else {}

    # -- validation / snapshot ------------------------------------------------

    async def async_validate(self) -> dict[str, Any]:
        """Log in and return the user block (used to derive the unique_id)."""
        await self._auth.async_login()
        user = await self.async_user_info()
        if not user:
            raise OrangeAuthError("Login did not resolve to a My Orange user")
        return user

    async def async_fetch_snapshot(self) -> dict[str, Any]:
        user = await self.async_user_info()
        account_name = user.get("name") or user.get("username") or "Orange"
        subscribers = await self.async_subscribers()

        profiles: dict[str, Any] = {}
        for sub in subscribers:
            profile_id = str(sub.get("profileId") or "").strip()
            sub_id = str(sub.get("subscriberId") or "").strip()
            msisdn = str(sub.get("msisdn") or "").strip()
            if not profile_id or not sub_id or not msisdn:
                continue

            profile = profiles.setdefault(
                profile_id,
                {
                    "info": {"name": account_name, "id": profile_id},
                    "customer": {},
                    "invoice": {},
                    "installments": [],
                    "transactions": [],
                    "subscribers": {},
                    "_billing_done": False,
                },
            )

            # Billing (v5) + Thank You / installments / transactions (v4) — once
            # per profile, on the first line we see for it.
            if not profile["_billing_done"]:
                profile["_billing_done"] = True
                await self._populate_billing(profile, profile_id, msisdn)

            # Per-line extras (v4, best effort).
            detail = (await self._get_v4(f"v4/subscribers/{sub_id}")) or {}
            cronos = (await self._get_v4(f"v4/{msisdn}/cronos")) or {}
            extra = (await self._get_v4(f"v4/msisdnExtraInfo/{msisdn}")) or {}
            # The v4 subscriber detail / cronos / msisdnExtra payloads are not
            # wrapped in a "data" envelope (the sensors read their fields at top
            # level), so store them raw.
            profile["subscribers"][sub_id] = {
                "summary": sub,
                "detail": detail if isinstance(detail, dict) else {},
                "cronos": cronos if isinstance(cronos, dict) else {},
                "extra": extra if isinstance(extra, dict) else {},
            }

        for profile in profiles.values():
            profile.pop("_billing_done", None)

        return {"user": user, "profiles": profiles}

    async def _populate_billing(
        self, profile: dict[str, Any], profile_id: str, msisdn: str
    ) -> None:
        try:
            resp = await self.async_invoice_info(profile_id, msisdn)
        except OrangeError as err:
            _LOGGER.debug("Orange invoiceInfo failed for %s: %s", profile_id, err)
            resp = {}
        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        info = data.get("invoiceInfo") if isinstance(data.get("invoiceInfo"), dict) else {}
        last_bill = data.get("lastBill") if isinstance(data.get("lastBill"), dict) else {}
        balance = data.get("balanceData") if isinstance(data.get("balanceData"), dict) else {}

        profile["invoice"] = {
            "totalBalanceAmount": balance.get("totalBalanceAmount"),
            "totalBalanceServices": balance.get("serviceBalanceAmount"),
            "totalBalanceInstallments": balance.get("installmentsBalanceAmount"),
            "lastBillIssuedAmount": info.get("lastBillIssuedAmount"),
            "lastBillIssueDate": _to_ms(info.get("lastBillIssueDate")),
            "dueDate": _to_ms(last_bill.get("dueDate")),
            "nextBillDate": _to_ms(info.get("nextBillDate")),
            "reference": last_bill.get("reference"),
        }

        # v4 extras for the profile (Thank You points, installments, history).
        customer = await self._get_v4(f"v4/profile/{profile_id}/customerInfo")
        if isinstance(customer, dict):
            profile["customer"] = customer.get("data", customer)
        installments = await self._get_v4(f"v4/profiles/{profile_id}/installmentsNew")
        if isinstance(installments, list):
            profile["installments"] = installments
        transactions = await self._get_v4(f"v4/profiles/{profile_id}/transactions")
        if isinstance(transactions, dict):
            profile["transactions"] = transactions.get("transactions") or []
