"""The Österreichische Post account integration."""

from __future__ import annotations

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import PostAtApiClient
from .auth import PostAtSession, SsoCookie
from .const import (
    CONF_LANGUAGE,
    CONF_SSO_COOKIE_NAME,
    CONF_SSO_COOKIE_VALUE,
    PLATFORMS,
    default_language,
)
from .coordinator import PostAtConfigEntry, PostAtCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: PostAtConfigEntry) -> bool:
    """Set up the post.at account from a config entry."""
    # A private session, and deliberately a cookie-less one. aiohttp's
    # CookieJar mangles B2C's cookies (see auth.cookie_header), so auth.py
    # tracks them itself and writes the Cookie header by hand.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
    auth = PostAtSession(
        session,
        SsoCookie(entry.data[CONF_SSO_COOKIE_NAME], entry.data[CONF_SSO_COOKIE_VALUE]),
    )
    language = entry.options.get(CONF_LANGUAGE) or default_language(
        hass.config.language
    )
    client = PostAtApiClient(session, auth, language)
    coordinator = PostAtCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reloading on an option change is not just tidiness: the coordinator
    # caches delivered parcels in `_settled`, and those hold text Post already
    # rendered in the old language.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: PostAtConfigEntry) -> None:
    """Reload the entry after its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PostAtConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
