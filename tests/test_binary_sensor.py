"""Behavioural tests for the internet-reachable binary sensor."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


def _entity_id(hass: HomeAssistant, mac: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"glinet4_binary_sensor/{mac}/internet"
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_internet_sensor_on_when_active_interface_online(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Connectivity is on when an up interface reports online."""
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, profile.factory_mac)
    interfaces = profile.load("network_interfaces_status")
    if interfaces is None:
        assert entity_id is None
        return
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["active_interfaces"] == ["wan"]


async def test_internet_sensor_off_when_active_interface_offline(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Connectivity drops when the active interface loses online."""
    interfaces = profile.load("network_interfaces_status")
    if interfaces is None:
        return
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, profile.factory_mac)

    degraded = [
        {**entry, "online": False} if entry["up"] else entry for entry in interfaces
    ]
    mock_glinet.network_interfaces_status.return_value = degraded
    # network_interfaces_status is part of the hub's WAN poll.
    coordinator = mock_config_entry.runtime_data.main
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "off"


def _fw_entity_id(hass: HomeAssistant, mac: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"glinet4_binary_sensor/{mac}/{key}"
    )


async def test_firewall_wan_access_sensors_reflect_exposure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """WAN ssh/https/ping exposure sensors mirror the firewall config."""
    # Clear the "endpoint absent" side effect the profile wired in by default.
    mock_glinet.firewall_wan_access.side_effect = None
    mock_glinet.firewall_wan_access.return_value = {
        "enable_https": True,
        "enable_ping": False,
        "enable_ssh": True,
    }
    await _setup(hass, mock_config_entry)

    mac = profile.factory_mac
    assert hass.states.get(_fw_entity_id(hass, mac, "wan_ssh")).state == "on"
    assert hass.states.get(_fw_entity_id(hass, mac, "wan_https")).state == "on"
    assert hass.states.get(_fw_entity_id(hass, mac, "wan_ping")).state == "off"


async def test_firewall_dmz_sensor_reports_state_and_target(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """The DMZ sensor reflects enablement and exposes the target IP."""
    mock_glinet.firewall_dmz.side_effect = None
    mock_glinet.firewall_dmz.return_value = {
        "enabled": True,
        "dmz_ip": "192.168.8.150",
    }
    await _setup(hass, mock_config_entry)

    state = hass.states.get(_fw_entity_id(hass, profile.factory_mac, "dmz"))
    assert state.state == "on"
    assert state.attributes["destination_ip"] == "192.168.8.150"


async def test_firewall_sensors_absent_when_unsupported(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,  # noqa: ARG001  (leaves firewall endpoints raising)
    profile: Profile,
) -> None:
    """A router that doesn't answer the firewall reads gets no firewall sensors."""
    await _setup(hass, mock_config_entry)
    mac = profile.factory_mac
    for key in ("wan_ssh", "wan_https", "wan_ping", "dmz"):
        assert _fw_entity_id(hass, mac, key) is None
