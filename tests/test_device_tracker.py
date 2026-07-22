"""Behavioural tests for GL.iNet device trackers.

Tracker states and registry entries are covered by ``tests/test_snapshots.py``;
this module keeps the discovery behaviour - one tracker per named client,
unnamed clients excluded, and clients appearing after setup picked up on the
next refresh. ``ScannerEntity`` trackers are disabled by default, so these
assert on the registry / coordinator snapshot rather than live states.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import DOMAIN
from custom_components.glinet4.coordinator import GLinetSubCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac

from .conftest import Profile


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_enabled_tracker_creates_device_for_client(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,  # noqa: ARG001  (patches the client used at setup)
    profile: Profile,
) -> None:
    """Enabling a tracker creates a device keyed by the client's MAC connection.

    HA's ScannerEntity never creates a device itself (device_info is final None);
    the integration creates it explicitly when the entity is enabled, giving the
    #51 "turn the tracker on and it becomes a device" outcome without creating
    devices for clients the user never enables.
    """
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    trackers = [
        entry
        for entry in er.async_entries_for_config_entry(
            ent_reg, mock_config_entry.entry_id
        )
        if entry.domain == "device_tracker"
    ]
    if not trackers:
        pytest.skip("profile has no tracked clients")

    for tracker in trackers:
        assert tracker.device_id is not None, f"{tracker.unique_id} has no device"
        device = dev_reg.async_get(tracker.device_id)
        assert device is not None
        # Keyed by the client's MAC connection so it merges with any existing
        # HA device for the same client rather than duplicating it.
        client_macs = {
            value
            for (kind, value) in device.connections
            if kind == CONNECTION_NETWORK_MAC
        }
        assert format_mac(tracker.unique_id) in client_macs
        # Standalone: client devices are not nested under the router.
        assert device.via_device_id is None


async def test_trackers_created(
    hass: HomeAssistant, init_integration: MockConfigEntry, profile: Profile
) -> None:
    """A tracker is registered for every named client from the router."""
    registry = er.async_get(hass)
    trackers = [
        entry
        for entry in er.async_entries_for_config_entry(
            registry, init_integration.entry_id
        )
        if entry.domain == "device_tracker"
    ]
    assert len(trackers) == profile.manifest["expected"]["tracked_device_count"]


async def test_unnamed_client_excluded(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A client with neither alias nor name is not tracked."""
    unnamed_mac = "00:11:22:aa:bb:cc"
    clients = profile.load("connected_clients")
    clients[unnamed_mac] = {
        "mac": unnamed_mac,
        "name": "",
        "online": True,
        "type": 0,
        "ip": "192.0.2.50",
    }
    mock_glinet.connected_clients.return_value = clients

    coordinator: GLinetSubCoordinator = init_integration.runtime_data.trackers
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "device_tracker", DOMAIN, unnamed_mac
    )
    assert entity_id is None


async def test_new_client_discovered_on_refresh(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A client appearing after setup is added on the next refresh."""
    new_mac = "00:11:22:99:99:99"
    clients = profile.load("connected_clients")
    clients[new_mac] = {
        "mac": new_mac,
        "name": "new-device",
        "online": True,
        "type": 0,
        "ip": "192.0.2.99",
    }
    mock_glinet.connected_clients.return_value = clients

    coordinator: GLinetSubCoordinator = init_integration.runtime_data.trackers
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "device_tracker", DOMAIN, new_mac
    )
    assert entity_id is not None
    # The tracker is disabled by default, so verify presence via the coordinator
    # snapshot (the source of the "home" state once the user enables the entity).
    assert coordinator.data.devices[new_mac].is_connected is True
