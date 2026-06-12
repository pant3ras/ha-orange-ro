"""Data update coordinator for Orange Romania."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OrangeApiClient, OrangeAuthError, OrangeError
from .auth import OrangeOAuth
from .const import CONF_REFRESH_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrangeDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls all available Orange account data on a schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: OrangeApiClient,
        auth: OrangeOAuth,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=DEFAULT_SCAN_INTERVAL
        )
        self.entry = entry
        self.client = client
        self._auth = auth

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.async_fetch_snapshot()
        except OrangeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OrangeError as err:
            raise UpdateFailed(str(err)) from err

        self._persist_refresh_token()
        return data

    def _persist_refresh_token(self) -> None:
        """Save the rotated refresh token so a restart resumes silently."""
        token = self._auth.refresh_token
        if token and token != self.entry.data.get(CONF_REFRESH_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_REFRESH_TOKEN: token}
            )
