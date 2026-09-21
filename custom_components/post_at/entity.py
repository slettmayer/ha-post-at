"""Shared entity plumbing."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import PostAtConfigEntry


def device_info(entry: PostAtConfigEntry) -> DeviceInfo:
    """One service device shared by every sensor."""
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        name="Österreichische Post",
        configuration_url="https://www.post.at/s/item-overview",
    )


__all__ = ["ATTRIBUTION", "device_info"]
