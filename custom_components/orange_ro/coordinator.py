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
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrangeDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls all available Orange account data on a schedule."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: OrangeApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch_all()
        except OrangeAuthError as err:
            # Triggers HA's re-auth flow so the user can paste a fresh cookie.
            raise ConfigEntryAuthFailed(str(err)) from err
        except OrangeError as err:
            raise UpdateFailed(str(err)) from err

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
