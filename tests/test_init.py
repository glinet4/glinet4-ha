"""Tests for GL-iNet integration setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock

from gli4py.error_handling import AuthenticationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.coordinator import GLinetUpdateCoordinator
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry loads, exposes the coordinator, then unloads cleanly."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, GLinetUpdateCoordinator)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_when_unreachable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A failed first refresh (router unreachable) puts the entry in retry."""
    mock_glinet.router_get_status.return_value = None

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_reauth_started_on_auth_failure(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A token renewal that fails authentication triggers the reauth flow."""
    # login succeeds during async_init (get_api + login) then fails when the
    # coordinator renews the token in async_setup.
    mock_glinet.login.side_effect = [None, None, AuthenticationError("bad creds")]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"].get("source") == "reauth"
    ]
    assert flows
