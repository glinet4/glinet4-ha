"""Behavioural tests for GL.iNet switches.

Switch states and registry entries are covered by ``tests/test_snapshots.py``;
this module keeps the side effects snapshots can't express - that toggling a
switch calls the right API and refreshes the coordinator. Feature-specific
switches are gated on the active profile's capabilities.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from glinet4.error_handling import NonZeroResponse
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


def _switch_id(hass: HomeAssistant, mac: str, unique_suffix: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"glinet4_switch/{mac}/{unique_suffix}"
    )


async def test_wifi_switch_turn_on_off_calls_api(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Toggling a WiFi switch calls the API and refreshes the coordinator."""
    entity_id = _switch_id(hass, profile.factory_mac, "iface_wifi2g")
    assert entity_id is not None
    calls_before = mock_glinet.wifi_ifaces.await_count

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wifi_iface_set_enabled.assert_awaited_with("wifi2g", enabled=False)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wifi_iface_set_enabled.assert_awaited_with("wifi2g", enabled=True)

    # async_request_refresh after each toggle re-polls the interfaces (the
    # refresh is debounced, so let it run before asserting).
    await hass.async_block_till_done()
    assert mock_glinet.wifi_ifaces.await_count > calls_before


async def test_tailscale_switch_turn_off_calls_api(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Turning off the Tailscale switch stops Tailscale."""
    if not profile.manifest["capabilities"]["has_tailscale"]:
        pytest.skip("profile has no Tailscale")
    entity_id = _switch_id(hass, profile.factory_mac, "tailscale")
    assert entity_id is not None

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.tailscale_stop.assert_awaited()


async def test_wireguard_switch_turn_off_calls_api(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Turning off the WireGuard switch stops the client."""
    if not profile.manifest["capabilities"]["has_wireguard"]:
        pytest.skip("profile has no WireGuard")
    client_name = profile.load("wireguard_client_list")[0]["name"]
    entity_id = _switch_id(hass, profile.factory_mac, f"{client_name}/wireguard_client")
    assert entity_id is not None

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.wireguard_client_stop.assert_awaited()


async def test_led_switch_reflects_and_controls_led_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """The LED switch mirrors led_config and drives led_set_enabled."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"glinet4_switch/{profile.factory_mac}/led"
    )
    led_config = profile.load("led_config")
    if led_config is None:
        assert entity_id is None
        return
    assert entity_id is not None
    expected = "on" if led_config["led_enable"] else "off"
    assert hass.states.get(entity_id).state == expected

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.led_set_enabled.assert_awaited_with(enabled=True)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.led_set_enabled.assert_awaited_with(enabled=False)


async def test_client_internet_switch_blocks_and_unblocks(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    entity_registry_enabled_by_default: None,
) -> None:
    """Per-client internet switch: on = allowed, turn_off blocks by MAC."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    clients = profile.load("connected_clients") or {}
    named = {
        mac: c
        for mac, c in clients.items()
        if (c.get("alias") or "").strip() or (c.get("name") or "").strip()
    }
    if not named:
        return
    mac = next(iter(named))
    entity_id = registry.async_get_entity_id(
        "switch", DOMAIN, f"glinet4_switch/{mac}/internet"
    )
    assert entity_id is not None
    # A non-blocked client shows internet access on.
    assert hass.states.get(entity_id).state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.client_set_blocked.assert_awaited_with(mac, blocked=True)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.client_set_blocked.assert_awaited_with(mac, blocked=False)


async def test_flow_statistics_switch_toggles_and_explains(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Stats switch toggles the rule and surfaces why data may not collect."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"glinet4_switch/{profile.factory_mac}/flow_statistics"
    )
    rule = profile.load("flow_stats_rule")
    if rule is None:
        assert entity_id is None
        return
    assert entity_id is not None
    coordinator = mock_config_entry.runtime_data
    accel = profile.load("network_acceleration") or {}

    # Baseline: stats off => not collecting; reason says so.
    state = hass.states.get(entity_id)
    assert state.state == "off"
    assert state.attributes["network_acceleration"] == accel.get("enable", False)
    assert state.attributes["collecting_app_data"] is False
    assert "disabled" in state.attributes["reason"].lower()

    # Stats on but acceleration off => enabled yet not collecting app data,
    # and the reason names the acceleration prerequisite.
    mock_glinet.flow_stats_rule.return_value = {**rule, "enable": True}
    mock_glinet.network_acceleration.return_value = {**accel, "enable": False}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["collecting_app_data"] is False
    assert "acceleration" in state.attributes["reason"].lower()

    # Toggling only touches the statistics rule (never SQM/acceleration).
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    mock_glinet.flow_stats_set_enabled.assert_awaited_with(enabled=False)
    assert mock_glinet.network_acceleration_set.await_count == 0
    mock_glinet.flow_stats_set_enabled.assert_awaited_with(enabled=False)


async def test_led_switch_raises_home_assistant_error_on_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """A failed action surfaces as HomeAssistantError, not a raw exception."""
    if profile.load("led_config") is None:
        return
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"glinet4_switch/{profile.factory_mac}/led"
    )
    mock_glinet.led_set_enabled.side_effect = NonZeroResponse("router said no")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
