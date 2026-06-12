"""Config flow for Orange Romania (mobile OAuth: e-mail + password)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OrangeApiClient, OrangeAuthError, OrangeError
from .auth import OrangeOAuth
from .const import AUTH_PASSWORD, CONF_AUTH_METHOD, CONF_REFRESH_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrangeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Orange Romania config and re-auth flows."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    async def _try_login(
        self, username: str, password: str
    ) -> tuple[dict[str, Any], str | None]:
        """Validate credentials; return (user_info, refresh_token)."""
        session = async_create_clientsession(self.hass)
        auth = OrangeOAuth(session, username, password)
        user = await OrangeApiClient(session, auth).async_validate()
        return user, auth.refresh_token

    def _entry_data(
        self, username: str, password: str, refresh_token: str | None
    ) -> dict[str, Any]:
        return {
            CONF_AUTH_METHOD: AUTH_PASSWORD,
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
            CONF_REFRESH_TOKEN: refresh_token,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            try:
                user, refresh_token = await self._try_login(username, password)
            except OrangeAuthError:
                errors["base"] = "invalid_auth"
            except OrangeError:
                errors["base"] = "cannot_connect"
            else:
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data_updates=self._entry_data(username, password, refresh_token),
                    )
                await self.async_set_unique_id(
                    str(user.get("sub") or user.get("ssoId") or username.lower())
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user.get("name") or username,
                    data=self._entry_data(username, password, refresh_token),
                )

        default_user = (
            self._reauth_entry.data.get(CONF_USERNAME, "") if self._reauth_entry else ""
        )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=default_user): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_user()
