"""The GL.iNet integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac

from .const import DOMAIN
from .coordinator import GLinetUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry

    from .coordinator import GlinetConfigEntry

PLATFORMS = [
    "binary_sensor",
    "button",
    "device_tracker",
    "select",
    "sensor",
    "switch",
    "update",
]


async def async_setup_entry(hass: HomeAssistant, entry: GlinetConfigEntry) -> bool:
    """Set up GL.iNet from a config entry.

    Called by home assistant on initial config, restart and
    component reload.
    """
    coordinator = GLinetUpdateCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GlinetConfigEntry) -> bool:
    """Unload a config entry.

    The coordinator's polling timer is owned by Home Assistant and torn down
    automatically with the config entry, so only the platforms need unloading.
    """
    entry.runtime_data.async_clear_issues()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: GlinetConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow removing a client device that is no longer connected.

    The router hub (identified by ``(DOMAIN, unique_id)``) can't be removed on
    its own — it goes with the config entry. A tracked client device can be
    removed once it is no longer connected; a still-connected client is kept,
    since it would just reappear on the next poll.
    """
    if any(identifier[0] == DOMAIN for identifier in device_entry.identifiers):
        return False

    device_macs = {
        format_mac(mac)
        for domain, mac in device_entry.connections
        if domain == CONNECTION_NETWORK_MAC
    }
    coordinator = config_entry.runtime_data
    connected_macs = {
        format_mac(mac)
        for mac, device in coordinator.data.devices.items()
        if device.is_connected
    }
    return device_macs.isdisjoint(connected_macs)
