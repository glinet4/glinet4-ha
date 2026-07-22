"""Support for GLinet routers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from propcache.api import cached_property

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetCoordinator
    from .models import ClientDevInfo

_LOGGER = logging.getLogger(__name__)

# Updates flow through the DataUpdateCoordinator, so the per-entity update
# throttle is unnecessary (0 = no limit).
PARALLEL_UPDATES = 0

DEFAULT_DEVICE_NAME = "Unknown device"


async def async_setup_entry(
    _: HomeAssistant,
    entry: GlinetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up device tracker for GLinet component."""
    # Client presence is latency-sensitive and costs one RPC of its own.
    coordinator = entry.runtime_data.trackers
    tracked: set[str] = set()

    @callback
    def add_new_entities() -> None:
        """Add tracker entities for devices not yet seen."""
        new_tracked = []
        for mac, device in coordinator.data.devices.items():
            if mac in tracked:
                continue
            new_tracked.append(GLinetDevice(coordinator, device))
            tracked.add(mac)
        if new_tracked:
            async_add_entities(new_tracked)

    # Discover new devices on every coordinator refresh (replaces the old
    # signal_device_new dispatcher), and add the ones already known now.
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))
    add_new_entities()


class GLinetDevice(CoordinatorEntity["GLinetCoordinator"], ScannerEntity):
    """Representation of a GLinet tracked device."""

    _attr_source_type: SourceType = SourceType.ROUTER

    def __init__(self, coordinator: GLinetCoordinator, device: ClientDevInfo) -> None:
        """Initialize a GLinet device."""
        super().__init__(coordinator)
        self._device: ClientDevInfo = device
        self._icon = "mdi:radar"
        self._attr_hostname: str = device.name or DEFAULT_DEVICE_NAME
        self._attr_ip_address: str | None = device.ip_address
        self._attr_mac_address: str = device.mac

    async def async_added_to_hass(self) -> None:
        """Create and attach a device for this client when the tracker is enabled.

        HA's ``ScannerEntity.device_info`` is ``@final`` and returns ``None`` --
        trackers never create a device on their own, they only attach to a
        device another integration already created. This hook runs only for
        *enabled*
        entities, so creating the device here gives each tracked client its own
        device the moment its tracker is turned on (#51), without creating
        devices for clients the user never enables. The MAC connection means it
        merges onto any existing device for the same client rather than
        duplicating it; ``default_name`` avoids clobbering that device's name.
        """
        await super().async_added_to_hass()
        config_entry = self.coordinator.config_entry
        if config_entry is None:  # pragma: no cover - always set in practice
            return
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=config_entry.entry_id,
            connections={(CONNECTION_NETWORK_MAC, format_mac(self._attr_mac_address))},
            default_name=self._attr_hostname,
        )
        # HA's own attach logic ran before this hook and found no device (we had
        # not created it yet), so link this entity to the device explicitly.
        if self.registry_entry and self.registry_entry.device_id != device.id:
            er.async_get(self.hass).async_update_entity(
                self.entity_id, device_id=device.id
            )

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_mac_address

    @property
    def icon(self) -> str:
        """Icon."""
        return self._icon

    @property
    def name(self) -> str:
        """Return the name."""
        return self._attr_hostname

    @property
    def available(self) -> bool:
        """Trackers stay available across transient poll failures.

        Presence (home/away) is carried by is_connected + consider_home, so the
        tracker should not flip to ``unavailable`` just because one poll failed
        (which CoordinatorEntity.available would otherwise do).
        """
        return True

    @property
    def is_connected(self) -> bool:
        """Return true if the device is connected to the network."""
        return self._device.is_connected

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.ROUTER

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes."""
        attrs: dict[str, Any] = {}
        attrs["interface_type"] = str(self._device.interface_type)
        if self._device.last_activity:
            attrs["last_time_reachable"] = self._device.last_activity.isoformat(
                timespec="seconds"
            )
        return attrs

    @cached_property
    def hostname(self) -> str:
        """Return the hostname of device."""
        return self._attr_hostname

    @cached_property
    def ip_address(self) -> str | None:
        """Return the primary ip address of the device."""
        return self._attr_ip_address

    @cached_property
    def mac_address(self) -> str | None:
        """Return the mac address of the device."""
        return self._attr_mac_address
