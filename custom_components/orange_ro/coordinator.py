"""Data update coordinator for Orange Romania.

One poll discovers every profile and line on the account and assembles a single
structured snapshot that the sensor platform reads from:

    {
      "user": {...},                     # currentUser block from userData
      "profiles": {
        <profile_id>: {
          "info": {...},                 # entry from /profiles
          "customer": {...},             # customerInfo (Thank You points etc.)
          "invoice": {...},              # invoiceInfo (billing)
          "installments": [...],
          "subscribers": {
            <subscriber_id>: {
              "summary": {...},          # entry from subscribers?profileId=
              "detail": {...},           # subscribers/{id}
              "cronos": {...},           # usage
              "extra": {...},            # msisdnExtraInfo
            }
          }
        }
      }
    }
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OrangeApiClient, OrangeAuthError, OrangeError
from .auth import OrangeLoginClient
from .const import (
    AUTH_COOKIE,
    CONF_AUTH_METHOD,
    CONF_COOKIE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class OrangeDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls all available Orange account data on a schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OrangeApiClient,
        login_client: OrangeLoginClient | None = None,
        credentials: tuple[str, str] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self.client = client
        self._login_client = login_client
        self._credentials = credentials

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self._fetch_all()
        except OrangeAuthError:
            data = await self._recover()
        except OrangeError as err:
            raise UpdateFailed(str(err)) from err
        self._persist_cookie()
        return data

    async def _recover(self) -> dict[str, Any]:
        """Try every headless way to restore the session before re-auth.

        1. Re-mint the API session off the long-lived SSO cookies (no
           credentials needed — works for the cookie method too).
        2. Full re-login with stored credentials (password method only).
        Only when both are exhausted do we bother the user with a re-auth.
        """
        try:
            _LOGGER.debug("API session expired; re-minting via SSO redirect chain")
            await self.client.async_refresh_session()
            return await self._fetch_all()
        except OrangeAuthError as err:
            sso_err = err
        except OrangeError as err:
            raise UpdateFailed(str(err)) from err

        if self._login_client and self._credentials:
            try:
                _LOGGER.debug("SSO refresh failed; attempting full re-login")
                cookie = await self._login_client.async_login(*self._credentials)
                self.client.update_cookie(cookie)
                return await self._fetch_all()
            except OrangeAuthError as relogin_err:
                raise ConfigEntryAuthFailed(str(relogin_err)) from relogin_err
            except OrangeError as relogin_err:
                raise UpdateFailed(str(relogin_err)) from relogin_err

        # Cookie method with a dead SSO session: a fresh cookie is needed.
        raise ConfigEntryAuthFailed(str(sso_err)) from sso_err

    def _persist_cookie(self) -> None:
        """Write the rotated cookie jar back to the config entry.

        Orange rotates session cookies on nearly every response; persisting
        the live jar means a Home Assistant restart resumes the session
        instead of replaying the long-dead cookie the user originally pasted.
        """
        if self.entry.data.get(CONF_AUTH_METHOD) != AUTH_COOKIE:
            return
        cookie = self.client.cookie
        if cookie and cookie != self.entry.data.get(CONF_COOKIE):
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_COOKIE: cookie}
            )

    async def _fetch_all(self) -> dict[str, Any]:
        user = await self.client.async_validate()

        profiles_resp = await self.client.async_get_profiles() or {}
        profile_entries = profiles_resp.get("profiles") or []

        result: dict[str, Any] = {"user": user, "profiles": {}}

        for prof in profile_entries:
            profile_id = prof.get("id")
            if profile_id is None:
                continue

            customer = await self.client.async_get_customer_info(profile_id)
            invoice = await self.client.async_get_invoice_info(profile_id)
            installments = await self.client.async_get_installments(profile_id) or []
            transactions = await self.client.async_get_transactions(profile_id) or {}

            subscribers_raw = await self.client.async_get_subscribers(profile_id) or []
            subscribers: dict[str, Any] = {}
            for sub in subscribers_raw:
                sub_id = sub.get("subscriberId")
                msisdn = sub.get("msisdn")
                if sub_id is None or not msisdn:
                    continue

                detail = await self.client.async_get_subscriber(sub_id)
                cronos = await self.client.async_get_cronos(msisdn)
                extra = await self.client.async_get_msisdn_extra(msisdn)

                subscribers[str(sub_id)] = {
                    "summary": sub,
                    "detail": detail or {},
                    "cronos": cronos or {},
                    "extra": extra or {},
                }

            result["profiles"][str(profile_id)] = {
                "info": prof,
                "customer": (customer or {}).get("data", {}),
                "invoice": (invoice or {}).get("data", {}),
                "installments": installments,
                "transactions": transactions.get("transactions") or [],
                "subscribers": subscribers,
            }

        return result
