"""The Orange Romania integration.

Author: PanTeraS
"""

from __future__ import annotations

__author__ = "PanTeraS"

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)

from .api import OrangeApiClient, OrangeAuthError, OrangeError
from .auth import OrangeLoginClient
from .const import AUTH_PASSWORD, CONF_AUTH_METHOD, CONF_COOKIE, DOMAIN
from .coordinator import OrangeDataCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type OrangeConfigEntry = ConfigEntry[OrangeDataCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: OrangeConfigEntry) -> bool:
    """Set up Orange Romania from a config entry."""
    login_client: OrangeLoginClient | None = None
    credentials: tuple[str, str] | None = None

    if entry.data.get(CONF_AUTH_METHOD) == AUTH_PASSWORD:
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]
        credentials = (username, password)
        # Isolated jar for the multi-redirect OAuth login.
        login_client = OrangeLoginClient(async_create_clientsession(hass))
        try:
            cookie = await login_client.async_login(username, password)
        except OrangeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OrangeError as err:
            raise ConfigEntryNotReady(str(err)) from err
    else:
        cookie = entry.data[CONF_COOKIE]

    client = OrangeApiClient(async_get_clientsession(hass), cookie)
    coordinator = OrangeDataCoordinator(
        hass, entry, client, login_client=login_client, credentials=credentials
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OrangeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
