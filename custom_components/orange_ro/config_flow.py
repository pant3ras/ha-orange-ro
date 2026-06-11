"""Config flow for Orange Romania (session-cookie auth)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OrangeApiClient, OrangeAuthError, OrangeError
from .const import CONF_COOKIE, DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrangeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Orange Romania config and re-auth flow."""

    VERSION = 1

    async def _validate(self, cookie: str) -> dict[str, Any]:
        """Validate a cookie and return the logged-in user block."""
        session = async_get_clientsession(self.hass)
        client = OrangeApiClient(session, cookie)
        return await client.async_validate()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial setup: collect the session cookie."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cookie = user_input[CONF_COOKIE].strip()
            try:
                user = await self._validate(cookie)
            except OrangeAuthError:
                errors["base"] = "invalid_auth"
            except OrangeError:
                errors["base"] = "cannot_connect"
            else:
                sso_id = str(user.get("ssoId", "orange"))
                await self.async_set_unique_id(sso_id)
                self._abort_if_unique_id_configured()
                username = user.get("username") or "Orange Romania"
                return self.async_create_entry(
                    title=username, data={CONF_COOKIE: cookie}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_COOKIE): str}),
            errors=errors,
            description_placeholders={
                "url": "https://www.orange.ro/myaccount/reshape/"
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when the stored cookie expires."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to paste a fresh cookie."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            cookie = user_input[CONF_COOKIE].strip()
            try:
                await self._validate(cookie)
            except OrangeAuthError:
                errors["base"] = "invalid_auth"
            except OrangeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_COOKIE: cookie}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_COOKIE): str}),
            errors=errors,
        )
