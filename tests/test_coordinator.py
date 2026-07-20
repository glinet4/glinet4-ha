"""Tests for the GL.iNet DataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

from glinet4.error_handling import AuthenticationError, NonZeroResponse, TokenError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.coordinator import (
    GLinetData,
    GLinetRuntimeData,
    GLinetUpdateCoordinator,
)
from homeassistant.core import HomeAssistant

from .conftest import Profile, async_refresh_all


def _runtime(entry: MockConfigEntry) -> GLinetRuntimeData:
    """Return the entry's four coordinators."""
    runtime_data = entry.runtime_data
    assert isinstance(runtime_data, GLinetRuntimeData)
    return runtime_data


def _coordinator(entry: MockConfigEntry) -> GLinetUpdateCoordinator:
    """Return the hub coordinator (the one that owns the API client)."""
    return _runtime(entry).main


async def test_data_snapshot_populated(
    hass: HomeAssistant, init_integration: MockConfigEntry, profile: Profile
) -> None:
    """The first refresh builds a GLinetData snapshot matching the profile.

    Each field is asserted on the coordinator that actually polls it: every
    coordinator returns the same ``GLinetData`` shape, but a snapshot only
    carries fresh values for the bucket that produced it.
    """
    runtime_data = _runtime(init_integration)
    main = runtime_data.main.data
    trackers = runtime_data.trackers.data
    slow = runtime_data.slow.data
    for data in (main, trackers, slow):
        assert isinstance(data, GLinetData)

    expected = profile.manifest["expected"]
    semantic = profile.manifest["semantic"]

    assert main.system_status["uptime"] == semantic["uptime_seconds"]
    assert main.system_status["cpu"]["temperature"] == int(semantic["cpu_temp"])
    assert trackers.connected_devices == expected["connected_client_count"]
    assert len(trackers.devices) == expected["tracked_device_count"]
    assert len(main.wifi_ifaces) == expected["wifi_iface_count"]
    assert len(main.wireguard_clients) == expected["wireguard_client_count"]
    assert len(main.wireguard_connections) == expected["wireguard_connection_count"]
    # Tailscale connection is only known when the feature is present; otherwise
    # the coordinator never sets it and it stays None.
    capabilities = profile.manifest["capabilities"]
    expected_tailscale = (
        capabilities["tailscale_connected"] if capabilities["has_tailscale"] else None
    )
    assert slow.tailscale_connection is expected_tailscale


async def test_identity_from_router_info(
    hass: HomeAssistant, init_integration: MockConfigEntry, profile: Profile
) -> None:
    """Device identity is read from router_info and proxied by the siblings."""
    runtime_data = _runtime(init_integration)
    main = runtime_data.main
    assert main.factory_mac == profile.factory_mac
    assert main.model == profile.manifest["model"]
    assert main.device_info["sw_version"] == profile.manifest["firmware_version"]

    # The siblings hold no identity of their own: they proxy the hub's, so an
    # entity gets the same device regardless of which bucket drives it.
    for sibling in (runtime_data.fast, runtime_data.trackers, runtime_data.slow):
        assert sibling.factory_mac == main.factory_mac
        assert sibling.model == main.model
        assert sibling.device_name == main.device_name
        assert sibling.device_info == main.device_info
        assert sibling.api is main.api


async def test_update_failed_marks_unsuccessful(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """When the status call fails, the refresh is marked unsuccessful."""
    coordinator = _coordinator(init_integration)
    assert coordinator.last_update_success is True

    mock_glinet.router_status.return_value = None
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
    # wan_status is polled by the hub (main) coordinator.
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
    runtime_data = _runtime(init_integration)

    # Simulate the entry starting during an auth hiccup: rebuild state as if
    # the first poll had failed with -32000. wan_status rides the hub and
    # wan_speed the fast coordinator, so drive both.
    mock_glinet.wan_status.side_effect = AuthenticationError("-32000")
    mock_glinet.wan_speed.side_effect = AuthenticationError("-32000")
    await async_refresh_all(init_integration)
    mock_glinet.wan_status.side_effect = None
    mock_glinet.wan_speed.side_effect = None
    await async_refresh_all(init_integration)
    assert runtime_data.main.data.wan_status == wan_status
    assert runtime_data.fast.data.wan_speed == profile.load("wan_speed")


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
    runtime_data = _runtime(init_integration)
    assert runtime_data.main.data.wan_status == wan_status
    assert runtime_data.fast.data.wan_speed == profile.load("wan_speed")

    mock_glinet.wan_status.side_effect = NonZeroResponse("-7 transient")
    mock_glinet.wan_speed.side_effect = NonZeroResponse("-7 transient")
    await async_refresh_all(init_integration)
    assert runtime_data.main.data.wan_status == wan_status
    assert runtime_data.fast.data.wan_speed == profile.load("wan_speed")


async def test_wan_endpoints_probed_independently(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A firmware missing only the speed endpoint still reports WAN status.

    The two endpoints also sit in different buckets (speed on the fast
    coordinator, status on the hub), so a failing speed poll must not take the
    hub's refresh down with it.
    """
    wan_status = profile.load("wan_status")
    if wan_status is None:
        return
    runtime_data = _runtime(init_integration)

    mock_glinet.wan_speed.side_effect = NonZeroResponse("-32601 method not found")
    await async_refresh_all(init_integration)
    assert runtime_data.main.data.wan_status == wan_status
    assert runtime_data.main.last_update_success is True


async def test_tailscale_connection_cleared_when_unconfigured(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Unconfiguring tailscale must clear the stale connection flag."""
    if not profile.manifest["capabilities"]["has_tailscale"]:
        return
    # Tailscale is polled by the slow coordinator.
    coordinator = _runtime(init_integration).slow
    assert coordinator.data.tailscale_connection is not None

    mock_glinet.tailscale_configured.return_value = False
    await coordinator.async_refresh()
    assert coordinator.data.tailscale_connection is None
    assert coordinator.data.tailscale_state is None
