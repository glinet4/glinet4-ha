"""Behavioural tests for the Tailscale exit-node select."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


def _entity_id(hass: HomeAssistant, mac: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "select", DOMAIN, f"glinet_select/{mac}/tailscale_exit_node"
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_select_created_only_with_tailscale(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """The exit-node select exists exactly when tailscale is configured."""
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, profile.factory_mac)
    if not profile.manifest["capabilities"]["has_tailscale"]:
        assert entity_id is None
        return
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == "none"
    expected_options = ["none"] + [
        f"{node['location']} ({node['ip']})"
        for node in profile.load("tailscale_exit_node_list") or []
    ]
    assert state.attributes["options"] == expected_options


async def test_selecting_a_node_sets_the_exit_node(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """Choosing a node calls the API with its IP; 'none' clears it."""
    nodes = profile.load("tailscale_exit_node_list")
    if not nodes:
        return
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, profile.factory_mac)

    label = f"{nodes[0]['location']} ({nodes[0]['ip']})"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": label},
        blocking=True,
    )
    mock_glinet.tailscale_set_exit_node.assert_awaited_with(nodes[0]["ip"])

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": "none"},
        blocking=True,
    )
    mock_glinet.tailscale_set_exit_node.assert_awaited_with(None)


async def test_current_option_follows_config(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
) -> None:
    """The selected option mirrors exit_node_ip from the router config."""
    nodes = profile.load("tailscale_exit_node_list")
    if not nodes:
        return
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass, profile.factory_mac)

    config = dict(mock_glinet._tailscale_get_config.return_value)
    config["exit_node_ip"] = nodes[0]["ip"]
    mock_glinet._tailscale_get_config.return_value = config
    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == f"{nodes[0]['location']} ({nodes[0]['ip']})"
