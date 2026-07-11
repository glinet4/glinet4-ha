"""Binary sensors for GL-iNet component."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Updates flow through the DataUpdateCoordinator.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    _: HomeAssistant, entry: GlinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    if coordinator.data.network_interfaces:
        async_add_entities([InternetBinarySensor(coordinator)])


class InternetBinarySensor(
    CoordinatorEntity["GLinetUpdateCoordinator"], BinarySensorEntity
):
    """Whether the router's active WAN interface reports internet access."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Internet"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GLinetUpdateCoordinator) -> None:
        """Initialize the internet sensor."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"glinet4_binary_sensor/{coordinator.factory_mac}/internet"
        )

    @property
    def is_on(self) -> bool:
        """Return True when an active (up) interface reports online."""
        return any(
            entry.get("up") and entry.get("online")
            for entry in self.coordinator.data.network_interfaces
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the interfaces currently carrying traffic."""
        return {
            "active_interfaces": [
                entry.get("interface")
                for entry in self.coordinator.data.network_interfaces
                if entry.get("up")
            ]
        }
