"""Tests for GL-iNet sensors."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from custom_components.glinet.coordinator import GLinetUpdateCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import FACTORY_MAC, load_json


def _entity_id(hass: HomeAssistant, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet_sensor/{FACTORY_MAC}/system_{key}"
    )


async def test_system_sensor_values(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """System status sensors report values from the coordinator snapshot."""
    cpu = _entity_id(hass, "cpu_temp")
    assert cpu is not None
    assert hass.states.get(cpu).state == "47"

    load1 = _entity_id(hass, "load_avg1")
    assert hass.states.get(load1).state == "0.13"


async def test_uptime_is_stable_across_polls(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """The uptime timestamp must not flap when uptime ticks within tolerance.

    Regression test: the old sensor recomputed ``now - uptime`` on every read,
    so the boot timestamp drifted across minute boundaries between polls.
    """
    uptime_id = _entity_id(hass, "uptime")
    assert uptime_id is not None
    first = hass.states.get(uptime_id).state
    assert first not in (None, "unknown", "unavailable")

    coordinator: GLinetUpdateCoordinator = init_integration.runtime_data

    # Next poll: uptime ticks forward a few seconds (well within tolerance).
    status = load_json("router_get_status")
    status["system"]["uptime"] += 7
    mock_glinet.router_get_status.return_value = status
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(uptime_id).state == first


async def test_uptime_reanchors_on_reboot(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A reboot (uptime resets low) moves the boot timestamp."""
    uptime_id = _entity_id(hass, "uptime")
    first = hass.states.get(uptime_id).state

    coordinator: GLinetUpdateCoordinator = init_integration.runtime_data
    status = load_json("router_get_status")
    status["system"]["uptime"] = 60.0  # just rebooted
    mock_glinet.router_get_status.return_value = status
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(uptime_id).state != first


async def test_sensor_filtered_when_value_missing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A sensor whose value is unavailable on this model is not created."""
    status = load_json("router_get_status")
    status["system"].pop("cpu", None)
    mock_glinet.router_get_status.return_value = status

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _entity_id(hass, "cpu_temp") is None
    # A sensor with data is still created.
    assert _entity_id(hass, "memory_use") is not None
