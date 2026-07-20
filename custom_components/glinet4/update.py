"""Update entities for GL.iNet component."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetCoordinator

_LOGGER = logging.getLogger(__name__)

# Updates flow through the DataUpdateCoordinator.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    _: HomeAssistant, entry: GlinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up update entities."""
    # Firmware is checked online at most every 6h; the slow bucket drives it.
    coordinator = entry.runtime_data.slow
    if coordinator.data.firmware_check:
        async_add_entities([GLinetFirmwareUpdate(coordinator)])


class GLinetFirmwareUpdate(CoordinatorEntity["GLinetCoordinator"], UpdateEntity):
    """Indicates when the router has a firmware update available.

    Read-only: installing firmware from HA is deliberately unsupported.
    """

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_translation_key = "firmware"
    _attr_has_entity_name = True

    def __init__(self, coordinator: GLinetCoordinator) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"glinet4_update/{coordinator.factory_mac}/firmware"

    @property
    def installed_version(self) -> str | None:
        """Return the running firmware version."""
        version: str | None = self.coordinator.data.firmware_check.get(
            "current_version"
        )
        return version

    @property
    def latest_version(self) -> str | None:
        """Return the newest firmware version the router reports."""
        check = self.coordinator.data.firmware_check
        version: str | None = check.get("new_version") or check.get("current_version")
        return version
