"""Entity name and icon translations.

Covers two quality-scale rules:

* **entity-translations** — static entity names come from a ``translation_key``
  resolved through ``strings.json`` / ``translations/en.json`` (with
  placeholders for names that embed data), never a hard-coded English string.
* **icon-translations** — entity icons are declared in ``icons.json`` keyed by
  ``translation_key`` instead of a hard-coded ``_attr_icon``.

Pure-data names (a Wi-Fi SSID, a tracked client's hostname) are intentionally
exempt: they are data, not translatable labels, so they keep a dynamic name and
their own icon logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import DOMAIN
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import build_mock_api, load_profile

COMPONENT = Path(__file__).parent.parent / "custom_components" / "glinet4"

# translation_key -> English name, per platform. Placeholders (e.g. the client
# name) are substituted at runtime from _attr_translation_placeholders.
EXPECTED_NAMES: dict[str, dict[str, str]] = {
    "sensor": {
        "cpu_temp": "CPU temperature",
        "load_avg1": "Load avg (1m)",
        "load_avg5": "Load avg (5m)",
        "load_avg15": "Load avg (15m)",
        "memory_use": "Memory usage",
        "flash_use": "Flash usage",
        "uptime": "Uptime",
        "wan_ip": "WAN IP",
        "wan_download_speed": "WAN download speed",
        "wan_upload_speed": "WAN upload speed",
        "tailscale_status": "Tailscale status",
        "firewall_port_forwards": "Port forwards",
        "firewall_rules": "Firewall rules",
        "wireguard_server_peers": "WireGuard peers",
        "openvpn_server_users": "OpenVPN users",
    },
    "switch": {
        "flow_statistics": "Flow statistics",
        "leds": "LEDs",
        "tailscale": "Tailscale",
        "client_internet": "{client_name} internet",
        "wireguard_client": "WG Client {client_name}",
    },
    "select": {"tailscale_exit_node": "Tailscale exit node"},
    "update": {"firmware": "Firmware"},
    "binary_sensor": {
        "internet": "Internet",
        "wan_ssh": "WAN SSH",
        "wan_https": "WAN HTTPS",
        "wan_ping": "WAN ping",
        "dmz": "DMZ",
    },
    "button": {"reboot": "Reboot"},
}

# translation_key -> icons.json spec, per platform.
_CPU = "mdi:cpu-64-bit"
EXPECTED_ICONS: dict[str, dict[str, dict]] = {
    "sensor": {
        "cpu_temp": {"default": "mdi:thermometer"},
        "load_avg1": {"default": _CPU},
        "load_avg5": {"default": _CPU},
        "load_avg15": {"default": _CPU},
        "memory_use": {"default": "mdi:memory"},
        "flash_use": {"default": "mdi:harddisk"},
        "uptime": {"default": "mdi:clock"},
        "wan_ip": {"default": "mdi:ip-outline"},
        "wan_download_speed": {"default": "mdi:download"},
        "wan_upload_speed": {"default": "mdi:upload"},
        "tailscale_status": {"default": "mdi:vpn"},
        "firewall_port_forwards": {"default": "mdi:arrow-decision"},
        "firewall_rules": {"default": "mdi:wall-fire"},
        "wireguard_server_peers": {"default": "mdi:account-network"},
        "openvpn_server_users": {"default": "mdi:account-key"},
    },
    "switch": {
        "client_internet": {"default": "mdi:web"},
        "flow_statistics": {"default": "mdi:chart-box"},
        "tailscale": {"default": "mdi:vpn"},
        "wireguard_client": {"default": "mdi:vpn"},
        "leds": {
            "default": "mdi:led-off",
            "state": {"on": "mdi:led-on", "off": "mdi:led-off"},
        },
    },
    "select": {"tailscale_exit_node": {"default": "mdi:server-network"}},
    "button": {"reboot": {"default": "mdi:restart"}},
    "binary_sensor": {
        "wan_ssh": {"default": "mdi:console-network"},
        "wan_https": {"default": "mdi:web"},
        "wan_ping": {"default": "mdi:access-point-network"},
        "dmz": {"default": "mdi:wall"},
    },
}


def _load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename", ["strings.json", "translations/en.json"])
def test_translation_files_declare_entity_names(filename: str) -> None:
    """Every static entity name is declared in the translation files."""
    entity = _load(filename).get("entity", {})
    for platform, names in EXPECTED_NAMES.items():
        for key, label in names.items():
            assert entity.get(platform, {}).get(key, {}).get("name") == label, (
                f"{filename}: entity.{platform}.{key}.name should be {label!r}"
            )


def test_icons_json_declares_entity_icons() -> None:
    """Every icon is declared in icons.json keyed by translation_key."""
    icons = _load("icons.json").get("entity", {})
    for platform, keys in EXPECTED_ICONS.items():
        for key, spec in keys.items():
            assert icons.get(platform, {}).get(key) == spec, (
                f"icons.json: entity.{platform}.{key} should be {spec!r}"
            )


async def _setup_mt6000(hass: HomeAssistant) -> MockConfigEntry:
    """Set up every platform for the real mt6000 capture."""
    profile = load_profile("mt6000")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=profile.manifest["title"],
        unique_id=profile.factory_mac,
        data={
            CONF_HOST: "http://192.168.8.1",
            CONF_USERNAME: "root",
            CONF_PASSWORD: "test-password",
            CONF_API_TOKEN: "test-token",
        },
        options={CONF_CONSIDER_HOME: 180},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.glinet4.coordinator.GLinet",
        return_value=build_mock_api(profile),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_entity_names_resolve_from_translations(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Entities carry a translation_key and their name resolves through it.

    Proves the translation files are actually wired up (not merely present):
    the CPU temperature sensor — created for every profile — must be named via
    its ``translation_key``, so its friendly name resolves to the English label.
    """
    entry = await _setup_mt6000(hass)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    by_key = {(e.domain, e.translation_key): e for e in entries}

    cpu = by_key.get(("sensor", "cpu_temp"))
    assert cpu is not None, "cpu_temp sensor must use translation_key='cpu_temp'"

    state = hass.states.get(cpu.entity_id)
    assert state is not None
    assert state.attributes["friendly_name"].endswith("CPU temperature")


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_client_switch_name_uses_placeholder(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,  # noqa: ARG001
) -> None:
    """The per-client internet switch keeps its client name via a placeholder."""
    entry = await _setup_mt6000(hass)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    client_switches = [
        e
        for e in entries
        if e.domain == "switch" and e.translation_key == "client_internet"
    ]
    if not client_switches:
        pytest.skip("mt6000 capture has no named clients")

    state = hass.states.get(client_switches[0].entity_id)
    assert state is not None
    # "<client name> internet" — the client name must survive translation.
    assert state.attributes["friendly_name"].endswith(" internet")
    assert state.attributes["friendly_name"] != "internet"
