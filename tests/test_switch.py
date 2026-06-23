"""Tests for GL-iNet switches."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import FACTORY_MAC, load_json


def _switch_id(hass: HomeAssistant, unique_suffix: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"glinet_switch/{FACTORY_MAC}/{unique_suffix}"
    )


async def test_wifi_switch_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A WiFi AP switch reflects the interface enabled flag."""
    ifaces = load_json("wifi_ifaces_get")
    name, iface = next(iter(ifaces.items()))
    entity_id = _switch_id(hass, f"iface_{name}")
    assert entity_id is not None
    expected = STATE_ON if iface["enabled"] else "off"
    assert hass.states.get(entity_id).state == expected


async def test_wifi_switch_turn_on_off_calls_api(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """Toggling a WiFi switch calls the API and refreshes the coordinator."""
    entity_id = _switch_id(hass, "iface_wifi2g")
    assert entity_id is not None
    calls_before = mock_glinet.wifi_ifaces_get.await_count

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wifi_iface_set_enabled.assert_awaited_with("wifi2g", False)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wifi_iface_set_enabled.assert_awaited_with("wifi2g", True)

    # async_request_refresh after each toggle re-polls the interfaces (the
    # refresh is debounced, so let it run before asserting).
    await hass.async_block_till_done()
    assert mock_glinet.wifi_ifaces_get.await_count > calls_before


async def test_tailscale_switch_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The Tailscale switch reflects the connection state."""
    entity_id = _switch_id(hass, "tailscale")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_ON


async def test_wireguard_switch_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The WireGuard switch is on when the client reports connected."""
    entity_id = _switch_id(hass, "wg-test/wireguard_client")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_ON


async def test_wireguard_switch_turn_off_calls_api(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """Turning off the WireGuard switch stops the client."""
    entity_id = _switch_id(hass, "wg-test/wireguard_client")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wireguard_client_stop.assert_awaited()
