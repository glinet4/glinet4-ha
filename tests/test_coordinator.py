"""Tests for the GL-iNet DataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

from gli4py.error_handling import AuthenticationError, NonZeroResponse, TokenError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.coordinator import GLinetData, GLinetUpdateCoordinator
from homeassistant.core import HomeAssistant

from .conftest import Profile


def _coordinator(entry: MockConfigEntry) -> GLinetUpdateCoordinator:
    coordinator = entry.runtime_data
    assert isinstance(coordinator, GLinetUpdateCoordinator)
    return coordinator


async def test_data_snapshot_populated(
    hass: HomeAssistant, init_integration: MockConfigEntry, profile: Profile
) -> None:
    """The first refresh builds a GLinetData snapshot matching the profile."""
    coordinator = _coordinator(init_integration)
    data = coordinator.data
    assert isinstance(data, GLinetData)

    expected = profile.manifest["expected"]
    semantic = profile.manifest["semantic"]

    assert data.system_status["uptime"] == semantic["uptime_seconds"]
    assert data.system_status["cpu"]["temperature"] == int(semantic["cpu_temp"])
    assert data.connected_devices == expected["connected_client_count"]
    assert len(data.devices) == expected["tracked_device_count"]
    assert len(data.wifi_ifaces) == expected["wifi_iface_count"]
    assert len(data.wireguard_clients) == expected["wireguard_client_count"]
    assert len(data.wireguard_connections) == expected["wireguard_connection_count"]
    # Tailscale connection is only known when the feature is present; otherwise
    # the coordinator never sets it and it stays None.
    capabilities = profile.manifest["capabilities"]
    expected_tailscale = (
        capabilities["tailscale_connected"] if capabilities["has_tailscale"] else None
    )
    assert data.tailscale_connection is expected_tailscale


async def test_identity_from_router_info(
    hass: HomeAssistant, init_integration: MockConfigEntry, profile: Profile
) -> None:
    """Device identity is read from router_info."""
    coordinator = _coordinator(init_integration)
    assert coordinator.factory_mac == profile.factory_mac
    assert coordinator.model == profile.manifest["model"]
    assert coordinator.device_info["sw_version"] == profile.manifest["firmware_version"]


async def test_update_failed_marks_unsuccessful(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """When the status call fails, the refresh is marked unsuccessful."""
    coordinator = _coordinator(init_integration)
    assert coordinator.last_update_success is True

    mock_glinet.router_get_status.return_value = None
    await coordinator.async_refresh()

    assert coordinator.last_update_success is False


async def test_wan_token_error_is_transient(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A token error must not permanently disable WAN polling.

    TokenError subclasses NonZeroResponse, so a mis-ordered except chain would
    treat an expired token as "endpoints unsupported" and never poll again.
    """
    wan_status = profile.load("wan_status")
    if wan_status is None:
        return  # profile's firmware has no WAN endpoints; nothing to protect
    coordinator = _coordinator(init_integration)
    assert coordinator.data.wan_status == wan_status

    mock_glinet.wan_status.side_effect = TokenError("token expired")
    await coordinator.async_refresh()
    mock_glinet.wan_status.side_effect = None
    mock_glinet.wan_status.return_value = wan_status
    await coordinator.async_refresh()
    assert coordinator.data.wan_status == wan_status


async def test_wan_absence_probed_once(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Firmware without WAN endpoints is probed once, then left alone."""
    wan_status = profile.load("wan_status")
    if wan_status is not None:
        return  # covered by the supported-path tests
    coordinator = _coordinator(init_integration)
    assert coordinator.data.wan_status == {}
    calls_after_setup = mock_glinet.wan_status.call_count

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert mock_glinet.wan_status.call_count == calls_after_setup


async def test_wan_auth_error_on_first_probe_is_transient(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """An auth error on the very first WAN probe must not disable the endpoints."""
    wan_status = profile.load("wan_status")
    if wan_status is None:
        return
    coordinator = _coordinator(init_integration)

    # Simulate the entry starting during an auth hiccup: rebuild state as if
    # the first poll had failed with -32000.
    mock_glinet.wan_status.side_effect = AuthenticationError("-32000")
    mock_glinet.wan_speed.side_effect = AuthenticationError("-32000")
    await coordinator.async_refresh()
    mock_glinet.wan_status.side_effect = None
    mock_glinet.wan_speed.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.data.wan_status == wan_status


async def test_wan_transient_error_keeps_last_good_values(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A transient router error after success must not wipe WAN data."""
    wan_status = profile.load("wan_status")
    if wan_status is None:
        return
    coordinator = _coordinator(init_integration)
    assert coordinator.data.wan_status == wan_status

    mock_glinet.wan_status.side_effect = NonZeroResponse("-7 transient")
    mock_glinet.wan_speed.side_effect = NonZeroResponse("-7 transient")
    await coordinator.async_refresh()
    assert coordinator.data.wan_status == wan_status
    assert coordinator.data.wan_speed == profile.load("wan_speed")


async def test_wan_endpoints_probed_independently(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A firmware missing only the speed endpoint still reports WAN status."""
    wan_status = profile.load("wan_status")
    if wan_status is None:
        return
    coordinator = _coordinator(init_integration)

    mock_glinet.wan_speed.side_effect = NonZeroResponse("-32601 method not found")
    await coordinator.async_refresh()
    assert coordinator.data.wan_status == wan_status


async def test_tailscale_connection_cleared_when_unconfigured(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Unconfiguring tailscale must clear the stale connection flag."""
    if not profile.manifest["capabilities"]["has_tailscale"]:
        return
    coordinator = _coordinator(init_integration)
    assert coordinator.data.tailscale_connection is not None

    mock_glinet.tailscale_configured.return_value = False
    await coordinator.async_refresh()
    assert coordinator.data.tailscale_connection is None
    assert coordinator.data.tailscale_state is None
