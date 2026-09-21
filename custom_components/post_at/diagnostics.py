"""Diagnostics for the post.at account.

Identifying fields are dropped rather than redacted in place. A diagnostics
download is routinely attached to a public GitHub issue, and a tracking number
alone is enough to look a parcel -- and its delivery address -- up on Post's
own site.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_SSO_COOKIE_NAME, CONF_SSO_COOKIE_VALUE
from .coordinator import PostAtConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_SSO_COOKIE_NAME, CONF_SSO_COOKIE_VALUE}

# Kept from each parcel: enough to debug a mapping or a timing bug, nothing
# that identifies the parcel or its recipient. `trackingStateKey` is the whole
# point of a status report, so it stays.
_KEEP = (
    "status",
    "trackingStateKey",
    "raw_status",
    "status_text",
    "eta_start",
    "eta_end",
    "eta_text",
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PostAtConfigEntry
) -> dict[str, Any]:
    """Return a redacted snapshot of the entry and the current parcels.

    ``runtime_data`` is deleted when an entry unloads, and Home Assistant
    serves a diagnostics download whatever state the entry is in. Reading it
    unguarded would raise -- and so return HTTP 500 -- for a disabled entry or
    one stuck in ``setup_retry``, which is exactly the state a user is in when
    they are asked to attach diagnostics to an issue.
    """
    coordinator = getattr(entry, "runtime_data", None)
    diagnostics: dict[str, Any] = {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "state": str(entry.state),
    }
    if coordinator is None:
        return diagnostics
    return diagnostics | {
        "update_interval": str(coordinator.update_interval),
        "last_update_success": coordinator.last_update_success,
        "parcel_count": len(coordinator.data or []),
        "parcels": [
            {key: parcel.as_attribute().get(key) for key in _KEEP}
            for parcel in coordinator.data or []
        ],
    }
