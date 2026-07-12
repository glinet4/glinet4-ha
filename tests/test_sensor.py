"""Behavioural tests for GL.iNet sensors.

Entity values and registry entries are covered by ``tests/test_snapshots.py``;
this module keeps the behaviour snapshots can't express - the uptime-stability
regression and the filter that drops sensors a model doesn't report.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from glinet4.enums import TailscaleConnection
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import DOMAIN
from custom_components.glinet4.coordinator import GLinetUpdateCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


def _entity_id(hass: HomeAssistant, mac: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{mac}/system_{key}"
    )


async def _setup_at(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> GLinetUpdateCoordinator:
    """Set up the integration with the clock frozen and return the coordinator.

    Freezing before setup makes the uptime sensor's derived boot time
    deterministic across machines.
    """
    freezer.move_to("2026-01-01 00:00:00+00:00")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_wan_ip_sensor_reports_address_without_prefix(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The WAN IP sensor reports the bare address; absent on old firmware."""
    await _setup_at(hass, mock_config_entry, freezer)
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{profile.factory_mac}/wan_ip"
    )
    wan_status = profile.load("wan_status")
    if wan_status is None:
        assert entity_id is None
        return
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == wan_status["ipv4"]["ip"].split("/")[0]
    assert state.attributes["gateway"] == wan_status["ipv4"]["gateway"]
    assert state.attributes["protocol"] == wan_status["protocol"]


async def test_wan_speed_sensors_report_rates(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """WAN download/upload sensors report bytes per second; absent otherwise."""
    await _setup_at(hass, mock_config_entry, freezer)
    registry = er.async_get(hass)
    download_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{profile.factory_mac}/wan_download_speed"
    )
    upload_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{profile.factory_mac}/wan_upload_speed"
    )
    wan_speed = profile.load("wan_speed")
    if wan_speed is None:
        assert download_id is None
        assert upload_id is None
        return
    assert download_id is not None
    assert upload_id is not None
    assert hass.states.get(download_id).state == str(wan_speed["speed_rx"])
    assert hass.states.get(upload_id).state == str(wan_speed["speed_tx"])


async def test_tailscale_status_sensor_reflects_connection_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The tailscale status sensor mirrors the connection state enum."""
    coordinator = await _setup_at(hass, mock_config_entry, freezer)
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{profile.factory_mac}/tailscale_status"
    )
    if not profile.manifest["capabilities"]["has_tailscale"]:
        assert entity_id is None
        return
    assert entity_id is not None
    expected = profile.manifest["endpoints"]["tailscale_connection_state"].lower()
    state = hass.states.get(entity_id)
    assert state.state == expected
    assert "auth_url" not in state.attributes

    # The router drops to LOGIN_REQUIRED (e.g. after the firmware's
    # 'tailscale up --reset' discards node auth) and offers a login URL.
    mock_glinet.tailscale_connection_state.return_value = (
        TailscaleConnection.LOGIN_REQUIRED
    )
    mock_glinet.tailscale_auth_url.return_value = (
        "https://login.tailscale.com/a/testtest"
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "login_required"
    assert state.attributes["auth_url"] == "https://login.tailscale.com/a/testtest"


async def test_uptime_is_stable_across_polls(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The uptime timestamp must not flap when uptime ticks within tolerance.

    Regression test: the old sensor recomputed ``now - uptime`` on every read,
    so the boot timestamp drifted across minute boundaries between polls.
    """
    coordinator = await _setup_at(hass, mock_config_entry, freezer)
    uptime_id = _entity_id(hass, profile.factory_mac, "uptime")
    assert uptime_id is not None
    first = hass.states.get(uptime_id).state
    assert first not in (None, "unknown", "unavailable")

    # Next poll: uptime ticks forward a few seconds (well within tolerance).
    status = profile.load("router_get_status")
    status["system"]["uptime"] += 7
    mock_glinet.router_status.return_value = status
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(uptime_id).state == first


async def test_uptime_reanchors_on_reboot(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A reboot (uptime resets low) moves the boot timestamp."""
    coordinator = await _setup_at(hass, mock_config_entry, freezer)
    uptime_id = _entity_id(hass, profile.factory_mac, "uptime")
    first = hass.states.get(uptime_id).state

    status = profile.load("router_get_status")
    status["system"]["uptime"] = 60.0  # just rebooted
    mock_glinet.router_status.return_value = status
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(uptime_id).state != first


async def test_sensor_filtered_when_value_missing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A sensor whose value is unavailable on this model is not created."""
    status = profile.load("router_get_status")
    status["system"].pop("cpu", None)
    mock_glinet.router_status.return_value = status

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _entity_id(hass, profile.factory_mac, "cpu_temp") is None
    # A sensor with data is still created.
    assert _entity_id(hass, profile.factory_mac, "memory_use") is not None


async def test_load_average_zero_is_reported(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A load average of exactly 0 is reported, not dropped as unavailable.

    Regression: the old value_fn short-circuited on the falsy 0 and the sensor
    went unavailable.
    """
    status = profile.load("router_get_status")
    status["system"]["load_average"] = [0, 0, 0]
    mock_glinet.router_status.return_value = status

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    load1 = _entity_id(hass, profile.factory_mac, "load_avg1")
    assert load1 is not None
    state = hass.states.get(load1).state
    assert state not in ("unavailable", "unknown")
    assert float(state) == 0


async def test_wan_ip_sensor_survives_null_ipv4(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Firmware reports ipv4 as null when the WAN link is down; no crash."""
    wan_status = profile.load("wan_status")
    if wan_status is None:
        return
    coordinator = await _setup_at(hass, mock_config_entry, freezer)
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{profile.factory_mac}/wan_ip"
    )
    down = dict(wan_status)
    down["ipv4"] = None
    mock_glinet.wan_status.return_value = down
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unknown"
