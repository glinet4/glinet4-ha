"""Tests for GL.iNet integration setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from glinet4.error_handling import AuthenticationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import (
    DOMAIN,
    FAST_SCAN_INTERVAL,
    SCAN_INTERVAL,
    SLOW_SCAN_INTERVAL,
    TRACKER_SCAN_INTERVAL,
)
from custom_components.glinet4.coordinator import (
    GLinetData,
    GLinetRuntimeData,
    GLinetSubCoordinator,
    GLinetUpdateCoordinator,
)
from custom_components.glinet4.models import DeviceInterfaceType
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .conftest import build_mock_api, load_profile


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry loads, exposes all four coordinators, then unloads cleanly."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED

    runtime_data = entry.runtime_data
    assert isinstance(runtime_data, GLinetRuntimeData)
    # The hub owns the API client; the siblings are bound to it.
    assert isinstance(runtime_data.main, GLinetUpdateCoordinator)
    assert isinstance(runtime_data.fast, GLinetSubCoordinator)
    assert isinstance(runtime_data.trackers, GLinetSubCoordinator)
    assert isinstance(runtime_data.slow, GLinetSubCoordinator)
    assert runtime_data.all() == (
        runtime_data.main,
        runtime_data.fast,
        runtime_data.trackers,
        runtime_data.slow,
    )

    # Each bucket polls on its own cadence...
    assert runtime_data.main.update_interval == SCAN_INTERVAL
    assert runtime_data.fast.update_interval == FAST_SCAN_INTERVAL
    assert runtime_data.trackers.update_interval == TRACKER_SCAN_INTERVAL
    assert runtime_data.slow.update_interval == SLOW_SCAN_INTERVAL

    # ...but every one is primed with the same shared snapshot shape, so an
    # entity can read `.data.<field>` off whichever coordinator drives it.
    for coordinator in runtime_data.all():
        assert coordinator.last_update_success is True
        assert isinstance(coordinator.data, GLinetData)
        assert coordinator.config_entry is entry

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_when_unreachable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A failed first refresh (router unreachable) puts the entry in retry."""
    mock_glinet.router_status.return_value = None

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_failure_aborts_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A token renewal that fails authentication aborts setup and starts reauth."""
    # login succeeds during async_init (get_api + login) then fails when the
    # coordinator renews the token in async_setup.
    mock_glinet.login.side_effect = [None, None, AuthenticationError("bad creds")]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    # ConfigEntryAuthFailed drives the reauth flow added in config_flow.py.
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_wifi7_mlo_client_setup_succeeds(hass: HomeAssistant) -> None:
    """REGRESSION: a WiFi7/MLO client must not crash setup.

    The ``wifi7_mlo_client`` profile has a client reporting an interface ``type``
    past the end of the legacy index *and* ``iface: "MLO"``. The old
    ``list(DeviceInterfaceType)[type]`` lookup raised IndexError and the entry
    landed in SETUP_RETRY; the resolver now loads cleanly and labels it MLO.
    """
    profile = load_profile("wifi7_mlo_client")
    entry = MockConfigEntry(
        domain=DOMAIN,
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
        assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    mlo_device = entry.runtime_data.trackers.data.devices["00:11:22:00:00:99"]
    assert mlo_device.interface_type is DeviceInterfaceType.MLO
