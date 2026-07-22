"""Binary sensors for GL.iNet component."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetCoordinator, GLinetData

_LOGGER = logging.getLogger(__name__)

# Updates flow through the DataUpdateCoordinator.
PARALLEL_UPDATES = 0


class GLinetBinarySensorEntityDescription(
    BinarySensorEntityDescription, frozen_or_thawed=True
):
    """Describes a binary sensor deriving its state from the GLinetData snapshot."""

    value_fn: Callable[[GLinetData], bool | None]
    extra_attributes_fn: Callable[[GLinetData], dict[str, Any] | None] | None = None


# WAN-exposure sensors: security-relevant, a natural thing to alert on. All read
# from firewall_wan_access. DMZ reads firewall_dmz and carries the target IP.
FIREWALL_BINARY_SENSORS: list[GLinetBinarySensorEntityDescription] = [
    GLinetBinarySensorEntityDescription(
        key="wan_ssh",
        translation_key="wan_ssh",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.firewall_wan_access.get("enable_ssh"),
    ),
    GLinetBinarySensorEntityDescription(
        key="wan_https",
        translation_key="wan_https",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.firewall_wan_access.get("enable_https"),
    ),
    GLinetBinarySensorEntityDescription(
        key="wan_ping",
        translation_key="wan_ping",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.firewall_wan_access.get("enable_ping"),
    ),
    GLinetBinarySensorEntityDescription(
        key="dmz",
        translation_key="dmz",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.firewall_dmz.get("enabled"),
        # Only expose the target when there is one (mirrors tailscale_status);
        # avoids a bare destination_ip: None on a disabled/empty DMZ.
        extra_attributes_fn=lambda data: (
            {"destination_ip": dmz_ip}
            if (dmz_ip := data.firewall_dmz.get("dmz_ip"))
            else None
        ),
    ),
]


async def async_setup_entry(
    _: HomeAssistant, entry: GlinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data.main
    entities: list[BinarySensorEntity] = []

    # Internet reachability comes from network_interfaces (WAN status bucket).
    if coordinator.data.network_interfaces:
        entities.append(InternetBinarySensor(coordinator))

    # Firewall sensors ride the slow (configuration) bucket. Only create the ones
    # whose backing read is available on this router/firmware (value is not None);
    # a model without WAN-access/DMZ reads simply doesn't get them.
    slow = entry.runtime_data.slow
    entities.extend(
        GLinetDataBinarySensor(slow, description)
        for description in FIREWALL_BINARY_SENSORS
        if description.value_fn(slow.data) is not None
    )

    async_add_entities(entities)


class InternetBinarySensor(CoordinatorEntity["GLinetCoordinator"], BinarySensorEntity):
    """Whether the router's active WAN interface reports internet access."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "internet"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GLinetCoordinator) -> None:
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


class GLinetDataBinarySensor(
    CoordinatorEntity["GLinetCoordinator"], BinarySensorEntity
):
    """A binary sensor whose state derives from the full coordinator snapshot."""

    entity_description: GLinetBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: GLinetCoordinator,
        entity_description: GLinetBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor from its description."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"glinet4_binary_sensor/{coordinator.factory_mac}/{entity_description.key}"
        )

    @property
    def is_on(self) -> bool | None:
        """Return the sensor's boolean state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.entity_description.extra_attributes_fn is None:
            return None
        return self.entity_description.extra_attributes_fn(self.coordinator.data)
