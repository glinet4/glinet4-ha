"""Behavioural tests for the firmware update entity."""

from __future__ import annotations

from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import DOMAIN, SLOW_SCAN_INTERVAL
from custom_components.glinet4.coordinator import FIRMWARE_CHECK_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


def _entity_id(hass: HomeAssistant, mac: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "update", DOMAIN, f"glinet4_update/{mac}/firmware"
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_update_entity_reports_up_to_date(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """With no new_version the entity exists (when supported) and reports off."""
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, profile.factory_mac)
    check = profile.load("firmware_check_online")
    if check is None:
        assert entity_id is None
        return
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == "off"
    assert state.attributes["installed_version"] == check["current_version"]
    assert state.attributes["latest_version"] == check["current_version"]


async def test_update_entity_reports_new_firmware(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A new_version from the router turns the entity on after the next check."""
    check = profile.load("firmware_check_online")
    if check is None:
        return
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, profile.factory_mac)

    mock_glinet.firmware_check_online.return_value = {
        **check,
        "new_version": "4.9.1",
    }
    freezer.tick(FIRMWARE_CHECK_INTERVAL)  # past the firmware-check throttle
    # The firmware check is part of the slow (configuration) poll.
    coordinator = mock_config_entry.runtime_data.slow
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["latest_version"] == "4.9.1"


async def test_firmware_check_is_throttled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The online check hits GL.iNet's servers; it must not run every poll."""
    if profile.load("firmware_check_online") is None:
        return
    await _setup(hass, mock_config_entry)
    calls_after_setup = mock_glinet.firmware_check_online.call_count
    assert calls_after_setup == 1

    # The check rides the slow coordinator but is throttled far harder than
    # that coordinator's own interval, so several slow polls inside one
    # FIRMWARE_CHECK_INTERVAL must not produce a second online check.
    coordinator = mock_config_entry.runtime_data.slow
    assert coordinator.update_interval == SLOW_SCAN_INTERVAL
    polls = 3
    assert polls * SLOW_SCAN_INTERVAL < FIRMWARE_CHECK_INTERVAL
    for _ in range(polls):
        freezer.tick(SLOW_SCAN_INTERVAL)
        await coordinator.async_refresh()
    assert mock_glinet.firmware_check_online.call_count == calls_after_setup

    # Past the throttle window, the next slow poll checks again.
    freezer.tick(FIRMWARE_CHECK_INTERVAL)
    await coordinator.async_refresh()
    assert mock_glinet.firmware_check_online.call_count == calls_after_setup + 1
