"""Tests for the GL-iNet DataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.coordinator import GLinetData, GLinetUpdateCoordinator
from homeassistant.core import HomeAssistant


def _coordinator(entry: MockConfigEntry) -> GLinetUpdateCoordinator:
    coordinator = entry.runtime_data
    assert isinstance(coordinator, GLinetUpdateCoordinator)
    return coordinator


async def test_data_snapshot_populated(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The first refresh builds a fully populated GLinetData snapshot."""
    coordinator = _coordinator(init_integration)
    data = coordinator.data
    assert isinstance(data, GLinetData)

    assert data.system_status["uptime"] == 695435.84
    assert data.system_status["cpu"]["temperature"] == 47
    # 14 named clients were captured from the live router.
    assert data.connected_devices == 14
    assert len(data.devices) == 14
    # 6 wifi interfaces captured.
    assert len(data.wifi_ifaces) == 6
    # Hand-authored WireGuard fixture has one connected client.
    assert len(data.wireguard_clients) == 1
    assert len(data.wireguard_connections) == 1
    assert data.tailscale_connection is True


async def test_identity_from_router_info(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Device identity is read from router_info."""
    coordinator = _coordinator(init_integration)
    assert coordinator.factory_mac == "00:11:22:00:00:01"
    assert coordinator.model == "MT6000"
    assert coordinator.device_info["sw_version"] == "4.9.0"


async def test_update_failed_marks_unsuccessful(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """When the status call fails, the refresh is marked unsuccessful."""
    coordinator = _coordinator(init_integration)
    assert coordinator.last_update_success is True

    mock_glinet.router_get_status.return_value = None
    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
