"""The Orange Romania integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OrangeApiClient
from .const import CONF_COOKIE, DOMAIN
from .coordinator import OrangeDataCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type OrangeConfigEntry = ConfigEntry[OrangeDataCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: OrangeConfigEntry) -> bool:
    """Set up Orange Romania from a config entry."""
    session = async_get_clientsession(hass)
    client = OrangeApiClient(session, entry.data[CONF_COOKIE])
    coordinator = OrangeDataCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OrangeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
