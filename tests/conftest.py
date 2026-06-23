"""Common fixtures for the GL-iNet integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from gli4py.enums import TailscaleConnection
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

FIXTURES = Path(__file__).parent / "fixtures"

# The sanitised factory MAC captured from the live router (see scripts/
# capture_fixtures.py). Drives unique_id / device identity in the tests.
FACTORY_MAC = "00:11:22:00:00:01"


def load_json(name: str) -> Any:
    """Load a sanitised API fixture captured from the live router."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,  # noqa: ARG001  (pthcc fixture)
) -> None:
    """Enable loading the glinet custom integration in every test."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry for the integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="GL-iNet MT6000",
        unique_id=FACTORY_MAC,
        data={
            CONF_HOST: "http://192.168.8.1",
            CONF_USERNAME: "root",
            CONF_PASSWORD: "test-password",
            CONF_API_TOKEN: "test-token",
        },
        options={CONF_CONSIDER_HOME: 180},
    )


def build_mock_api() -> AsyncMock:
    """Build an AsyncMock GLinet client backed by the captured fixtures."""
    api = AsyncMock()
    api.router_info.return_value = load_json("router_info")
    api.router_get_status.return_value = load_json("router_get_status")
    api.connected_clients.return_value = load_json("connected_clients")
    api.wifi_ifaces_get.return_value = load_json("wifi_ifaces_get")
    api.tailscale_configured.return_value = True
    api._tailscale_get_config.return_value = load_json("tailscale_get_config")
    api.tailscale_connection_state.return_value = TailscaleConnection.CONNECTED
    api.wireguard_client_list.return_value = load_json("wireguard_client_list")
    api.wireguard_client_state.return_value = load_json("wireguard_client_state")
    # Action endpoints (no useful return value).
    api.router_reboot.return_value = None
    api.wifi_iface_set_enabled.return_value = None
    api.tailscale_start.return_value = None
    api.tailscale_stop.return_value = None
    api.wireguard_client_start.return_value = None
    api.wireguard_client_stop.return_value = None
    api.logged_in = True
    return api


@pytest.fixture
def mock_api() -> AsyncMock:
    """Return a fresh mock GLinet API client."""
    return build_mock_api()


@pytest.fixture
def mock_glinet(mock_api: AsyncMock) -> AsyncMock:
    """Patch the GLinet client used by the coordinator to the mock API."""
    with patch(
        "custom_components.glinet.coordinator.GLinet", return_value=mock_api
    ):
        yield mock_api


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> MockConfigEntry:
    """Set up the glinet integration with mocked API and return the entry."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
