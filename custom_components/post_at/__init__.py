"""The Österreichische Post account integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import PostAtApiClient
from .auth import PostAtSession, SsoCookie
from .const import CONF_SSO_COOKIE_NAME, CONF_SSO_COOKIE_VALUE, PLATFORMS
from .coordinator import PostAtConfigEntry, PostAtCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: PostAtConfigEntry) -> bool:
    """Set up the post.at account from a config entry."""
    # A private session: the B2C journey sets cookies that have no business in
    # Home Assistant's shared jar.
    session = async_create_clientsession(hass)
    auth = PostAtSession(
        session,
        SsoCookie(entry.data[CONF_SSO_COOKIE_NAME], entry.data[CONF_SSO_COOKIE_VALUE]),
    )
    coordinator = PostAtCoordinator(hass, entry, PostAtApiClient(session, auth))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PostAtConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
