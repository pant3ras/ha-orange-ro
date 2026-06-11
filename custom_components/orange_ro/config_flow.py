"""Config flow for Orange Romania (username/password or session cookie)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)

from .api import OrangeApiClient, OrangeAuthError, OrangeError
from .auth import OrangeLoginClient
from .const import AUTH_COOKIE, AUTH_PASSWORD, CONF_AUTH_METHOD, CONF_COOKIE, DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrangeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Orange Romania config and re-auth flows."""

    VERSION = 1

    async def _validate_cookie(self, cookie: str) -> dict[str, Any]:
        """Validate a cookie; return the logged-in user block."""
        client = OrangeApiClient(async_get_clientsession(self.hass), cookie)
        return await client.async_validate()

    async def _login_password(self, username: str, password: str) -> tuple[str, dict[str, Any]]:
        """Log in with credentials; return (cookie, user block)."""
        # Isolated cookie jar so the login redirects don't touch HA's shared jar.
        session = async_create_clientsession(self.hass)
        cookie = await OrangeLoginClient(session).async_login(username, password)
        user = await OrangeApiClient(async_get_clientsession(self.hass), cookie).async_validate()
        return cookie, user

    # -- Initial setup --------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose an authentication method."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["password", "cookie"],
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up with username and password (best-effort; may hit reCAPTCHA)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            try:
                _cookie, user = await self._login_password(username, password)
            except OrangeAuthError:
                errors["base"] = "invalid_auth"
            except OrangeError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(str(user.get("ssoId", "orange")))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user.get("username") or username,
                    data={
                        CONF_AUTH_METHOD: AUTH_PASSWORD,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_cookie(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up by pasting a browser session cookie."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cookie = user_input[CONF_COOKIE].strip()
            try:
                user = await self._validate_cookie(cookie)
            except OrangeAuthError:
                errors["base"] = "invalid_auth"
            except OrangeError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(str(user.get("ssoId", "orange")))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user.get("username") or "Orange Romania",
                    data={CONF_AUTH_METHOD: AUTH_COOKIE, CONF_COOKIE: cookie},
                )

        return self.async_show_form(
            step_id="cookie",
            data_schema=vol.Schema({vol.Required(CONF_COOKIE): str}),
            errors=errors,
            description_placeholders={"url": "https://www.orange.ro/myaccount/reshape/"},
        )

    # -- Re-auth (cookie expired / credentials changed) -----------------------

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Route re-auth to the method the entry was created with."""
        if entry_data.get(CONF_AUTH_METHOD) == AUTH_PASSWORD:
            return await self.async_step_reauth_password()
        return await self.async_step_reauth_cookie()

    async def async_step_reauth_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-enter credentials (or fix them if they changed)."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            try:
                await self._login_password(username, password)
            except OrangeAuthError:
                errors["base"] = "invalid_auth"
            except OrangeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_AUTH_METHOD: AUTH_PASSWORD,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="reauth_password",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth_cookie(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Paste a fresh cookie."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            cookie = user_input[CONF_COOKIE].strip()
            try:
                await self._validate_cookie(cookie)
            except OrangeAuthError:
                errors["base"] = "invalid_auth"
            except OrangeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_AUTH_METHOD: AUTH_COOKIE, CONF_COOKIE: cookie},
                )

        return self.async_show_form(
            step_id="reauth_cookie",
            data_schema=vol.Schema({vol.Required(CONF_COOKIE): str}),
            errors=errors,
        )
