"""Button platform for the GL-iNet integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GLinetUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the button entities."""
    coordinator: GLinetUpdateCoordinator = entry.runtime_data
    async_add_entities([RebootButton(coordinator)])


class RebootButton(ButtonEntity):
    """Reboot button."""

    _attr_icon = "mdi:restart"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GLinetUpdateCoordinator) -> None:
        """Initialize a GLinet device."""
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"glinet_button/{coordinator.factory_mac}/reboot"
        )

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return "Reboot"

    async def async_press(self) -> None:
        """Reboot the router."""
        await self._coordinator.api.router_reboot()
