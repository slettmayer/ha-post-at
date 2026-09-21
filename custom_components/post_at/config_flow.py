"""Config and reauth flows for the post.at account."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .auth import PostAtAuthError, PostAtInvalidCredentials, PostAtSession, SsoCookie
from .const import (
    CONF_EMAIL,
    CONF_SSO_COOKIE_NAME,
    CONF_SSO_COOKIE_VALUE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)
STEP_REAUTH = vol.Schema({vol.Required(CONF_PASSWORD): str})


class PostAtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in once, keep the session, forget the password."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials and exchange them for an SSO cookie."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            await self.async_set_unique_id(email.casefold())
            self._abort_if_unique_id_configured()
            cookie, error = await self._async_sign_in(email, user_input[CONF_PASSWORD])
            if cookie is not None:
                return self.async_create_entry(
                    title=email,
                    data={
                        CONF_EMAIL: email,
                        CONF_SSO_COOKIE_NAME: cookie.name,
                        CONF_SSO_COOKIE_VALUE: cookie.value,
                    },
                )
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth when the stored session stops minting tokens."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask only for the password; the email is already known."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            cookie, error = await self._async_sign_in(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if cookie is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_SSO_COOKIE_NAME: cookie.name,
                        CONF_SSO_COOKIE_VALUE: cookie.value,
                    },
                )
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH,
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )

    async def _async_sign_in(
        self, email: str, password: str
    ) -> tuple[SsoCookie | None, str | None]:
        """Run the sign-in journey, translating failures into form errors.

        A private session is used so B2C's cookies never land in Home
        Assistant's shared client session.
        """
        session = async_create_clientsession(self.hass)
        try:
            cookie = await PostAtSession(session).async_login(email, password)
        except PostAtInvalidCredentials:
            return None, "invalid_auth"
        except PostAtAuthError:
            _LOGGER.exception("post.at sign-in journey failed")
            return None, "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error signing in to post.at")
            return None, "unknown"
        return cookie, None
