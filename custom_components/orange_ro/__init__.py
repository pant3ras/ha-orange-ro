"""The Orange Romania integration.

Author: PanTeraS
Mobile OAuth login adapted from HAForgeLabs/utilitati_romania (MIT).
"""

from __future__ import annotations

__author__ = "PanTeraS"

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OrangeApiClient
from .auth import OrangeOAuth
from .const import CONF_REFRESH_TOKEN, DOMAIN
from .coordinator import OrangeDataCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type OrangeConfigEntry = ConfigEntry[OrangeDataCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: OrangeConfigEntry) -> bool:
    """Set up Orange Romania from a config entry."""
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    if not username or not password:
        # Pre-OAuth (cookie/web) entry — needs a one-time re-auth to collect
        # credentials for the mobile OAuth flow.
        raise ConfigEntryAuthFailed("Orange now signs in with e-mail + password")

    session = async_create_clientsession(hass)
    auth = OrangeOAuth(
        session, username, password, refresh_token=entry.data.get(CONF_REFRESH_TOKEN)
    )
    client = OrangeApiClient(session, auth)
    coordinator = OrangeDataCoordinator(hass, entry, client, auth)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OrangeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
