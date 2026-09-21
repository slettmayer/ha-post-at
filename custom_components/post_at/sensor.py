"""Sensors for the post.at account.

One stable summary sensor rather than one entity per parcel. A dashboard can
bind to it for years, whereas per-parcel entity ids churn as parcels come and
go; automations use the bus events instead, which cover every parcel present
and future with nothing to update when one arrives.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PostAtConfigEntry, PostAtCoordinator
from .entity import ATTRIBUTION, device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PostAtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the three sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ParcelsInDeliverySensor(coordinator, entry),
            NextDeliverySensor(coordinator, entry),
            LastUpdateSensor(coordinator, entry),
        ]
    )


class PostAtSensor(CoordinatorEntity[PostAtCoordinator], SensorEntity):
    """Base class wiring every sensor to the shared device."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: PostAtCoordinator,
        entry: PostAtConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Attach the description and the shared device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"
        self._attr_device_info = device_info(entry)


class ParcelsInDeliverySensor(PostAtSensor):
    """How many parcels are on their way, with the full list as an attribute."""

    def __init__(
        self, coordinator: PostAtCoordinator, entry: PostAtConfigEntry
    ) -> None:
        """Describe the summary sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="parcels_in_delivery",
                translation_key="parcels_in_delivery",
            ),
        )

    @property
    def native_value(self) -> int:
        """The number of parcels still in flight."""
        return sum(1 for parcel in self.coordinator.data or [] if parcel.is_active)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Every parcel on the account, active and recently delivered."""
        return {
            "parcels": [parcel.as_attribute() for parcel in self.coordinator.data or []]
        }


class NextDeliverySensor(PostAtSensor):
    """The earliest expected delivery across all active parcels."""

    def __init__(
        self, coordinator: PostAtCoordinator, entry: PostAtConfigEntry
    ) -> None:
        """Describe the next-delivery sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="next_delivery",
                translation_key="next_delivery",
                device_class=SensorDeviceClass.TIMESTAMP,
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """The soonest ETA, or ``None`` when nothing is on its way."""
        etas = [
            parcel.eta_start
            for parcel in self.coordinator.data or []
            if parcel.is_active and parcel.eta_start is not None
        ]
        return min(etas) if etas else None


class LastUpdateSensor(PostAtSensor):
    """When post.at was last polled successfully."""

    def __init__(
        self, coordinator: PostAtCoordinator, entry: PostAtConfigEntry
    ) -> None:
        """Describe the diagnostic sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="last_update",
                translation_key="last_update",
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """The coordinator's last successful refresh time."""
        return self.coordinator.last_update_success_time
