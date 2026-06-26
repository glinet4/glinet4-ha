"""Tests for GL-iNet device trackers."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from custom_components.glinet.coordinator import GLinetUpdateCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import load_json


def _online_client() -> tuple[str, dict]:
    clients = load_json("connected_clients")
    for mac, info in clients.items():
        if info.get("online"):
            return mac, info
    raise AssertionError("fixture has no online client")


async def test_trackers_created(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A tracker is registered for every named client from the router.

    ``ScannerEntity`` trackers are disabled by default until the user enables
    them (no ``device_info``/pre-existing device), so assert on the entity
    registry rather than live states.
    """
    registry = er.async_get(hass)
    trackers = [
        entry
        for entry in er.async_entries_for_config_entry(
            registry, init_integration.entry_id
        )
        if entry.domain == "device_tracker"
    ]
    assert len(trackers) == len(load_json("connected_clients"))


async def test_online_client_is_home(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An online client is reported as home."""
    mac, _ = _online_client()
    entity_id = er.async_get(hass).async_get_entity_id("device_tracker", DOMAIN, mac)
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "home"


async def test_unnamed_client_excluded(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A client with neither alias nor name is not tracked."""
    unnamed_mac = "00:11:22:aa:bb:cc"
    clients = load_json("connected_clients")
    clients[unnamed_mac] = {
        "mac": unnamed_mac,
        "name": "",
        "online": True,
        "type": 0,
        "ip": "192.0.2.50",
    }
    mock_glinet.connected_clients.return_value = clients

    coordinator: GLinetUpdateCoordinator = init_integration.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "device_tracker", DOMAIN, unnamed_mac
    )
    assert entity_id is None


async def test_new_client_discovered_on_refresh(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A client appearing after setup is added on the next refresh."""
    new_mac = "00:11:22:99:99:99"
    clients = load_json("connected_clients")
    clients[new_mac] = {
        "mac": new_mac,
        "name": "new-device",
        "online": True,
        "type": 0,
        "ip": "192.0.2.99",
    }
    mock_glinet.connected_clients.return_value = clients

    coordinator: GLinetUpdateCoordinator = init_integration.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "device_tracker", DOMAIN, new_mac
    )
    assert entity_id is not None
    # The tracker is disabled by default, so verify presence via the coordinator
    # snapshot (the source of the "home" state once the user enables the entity).
    assert coordinator.data.devices[new_mac].is_connected is True
