"""Tests for removing stale client-tracker devices."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4 import async_remove_config_entry_device
from custom_components.glinet4.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _register_client(
    hass: HomeAssistant, entry: MockConfigEntry, mac: str
) -> dr.DeviceEntry:
    """Register a client-tracker device (mac connection, no DOMAIN identifier)."""
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_NETWORK_MAC, format_mac(mac))},
    )


async def test_router_device_cannot_be_removed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """The router hub device may not be removed on its own."""
    await _setup(hass, mock_config_entry)
    router = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, mock_config_entry.unique_id)}
    )
    assert router is not None
    assert (
        await async_remove_config_entry_device(hass, mock_config_entry, router) is False
    )


async def test_connected_client_cannot_be_removed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A currently-connected client cannot be removed (it would reappear)."""
    await _setup(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    connected = [m for m, d in coordinator.data.devices.items() if d.is_connected]
    if not connected:
        return
    device = _register_client(hass, mock_config_entry, connected[0])
    assert (
        await async_remove_config_entry_device(hass, mock_config_entry, device) is False
    )


async def test_disconnected_client_can_be_removed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A client no longer connected can be removed."""
    await _setup(hass, mock_config_entry)
    # a MAC the router has never reported is, by definition, not connected
    device = _register_client(hass, mock_config_entry, "de:ad:be:ef:00:01")
    assert (
        await async_remove_config_entry_device(hass, mock_config_entry, device) is True
    )
