"""Diagnostics support for the GL-iNet integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_MAC, CONF_PASSWORD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import GlinetConfigEntry

# Keys whose values are credentials or identify a device/network/person.
TO_REDACT = {
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_MAC,
    CONF_PASSWORD,
    "alias",
    "bssid",
    "ddns",
    "factory_mac",
    "guest_ip",
    "hostname",
    "ip",
    "iot_ip",
    "ipv6",
    "key",
    "lan_ip",
    "mac",
    "name",
    "public_ip",
    "sn",
    "sn_bak",
    "ssid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GlinetConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    snapshot: dict[str, Any] = {
        "system_status": data.system_status,
        "connected_devices": data.connected_devices,
        "tracked_devices": len(data.devices),
        "devices": [
            {
                "mac": device.mac,
                "interface_type": str(device.interface_type),
                "is_connected": device.is_connected,
            }
            for device in data.devices.values()
        ],
        "wifi_ifaces": {
            name: asdict(iface) for name, iface in data.wifi_ifaces.items()
        },
        "wireguard_clients": [
            asdict(client) for client in data.wireguard_clients.values()
        ],
        "tailscale_configured": bool(data.tailscale_config),
        "tailscale_connection": data.tailscale_connection,
    }

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "device": async_redact_data(
            {
                "model": coordinator.model,
                "firmware_version": coordinator.device_info.get("sw_version"),
                "factory_mac": coordinator.factory_mac,
            },
            TO_REDACT,
        ),
        "data": async_redact_data(snapshot, TO_REDACT),
    }
