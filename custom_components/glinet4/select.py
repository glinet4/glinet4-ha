"""Select entities for GL.iNet component."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .utils import async_run_action

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Updates flow through the DataUpdateCoordinator.
PARALLEL_UPDATES = 0

NO_EXIT_NODE = "none"


async def async_setup_entry(
    _: HomeAssistant, entry: GlinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up selects."""
    coordinator = entry.runtime_data
    if coordinator.data.tailscale_state is not None:
        async_add_entities([TailscaleExitNodeSelect(coordinator)])


class TailscaleExitNodeSelect(
    CoordinatorEntity["GLinetUpdateCoordinator"], SelectEntity
):
    """Route the router's traffic through a tailnet exit node."""

    _attr_translation_key = "tailscale_exit_node"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GLinetUpdateCoordinator) -> None:
        """Initialize the exit-node select."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"glinet4_select/{coordinator.factory_mac}/tailscale_exit_node"
        )

    def _labels(self) -> dict[str, str]:
        """Map an option label to its node's tailscale IP."""
        labels = {
            f"{node.get('location') or node['ip']} ({node['ip']})": node["ip"]
            for node in self.coordinator.data.tailscale_exit_nodes
            if node.get("ip")
        }
        # An exit node can be active yet missing from the advertised list
        # (e.g. it stopped advertising); keep it selectable so state is honest.
        active = self.coordinator.data.tailscale_config.get("exit_node_ip")
        if active and active not in labels.values():
            labels[active] = active
        return labels

    @property
    def options(self) -> list[str]:
        """Return the selectable exit nodes."""
        return [NO_EXIT_NODE, *self._labels()]

    @property
    def current_option(self) -> str:
        """Return the label of the active exit node."""
        active = self.coordinator.data.tailscale_config.get("exit_node_ip")
        if not active:
            return NO_EXIT_NODE
        for label, ip in self._labels().items():
            if ip == active:
                return label
        return NO_EXIT_NODE

    async def async_select_option(self, option: str) -> None:
        """Set (or clear) the exit node."""
        ip = None if option == NO_EXIT_NODE else self._labels().get(option)
        await async_run_action(
            self.coordinator.api.tailscale_set_exit_node(ip),
            device=self.coordinator.device_name,
        )
        await self.coordinator.async_request_refresh()
