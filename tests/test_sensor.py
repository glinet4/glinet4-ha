"""Behavioural tests for GL.iNet sensors.

Entity values and registry entries are covered by ``tests/test_snapshots.py``;
this module keeps the behaviour snapshots can't express - the uptime-stability
regression and the filter that drops sensors a model doesn't report.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from glinet4.enums import TailscaleConnection
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import DOMAIN
from custom_components.glinet4.coordinator import GLinetRuntimeData
from homeassistant.const import UnitOfDataRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import Profile


def _entity_id(hass: HomeAssistant, mac: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{mac}/system_{key}"
    )


def _data_entity_id(hass: HomeAssistant, mac: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{mac}/{key}"
    )


async def _setup_at(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> GLinetRuntimeData:
    """Set up the integration with the clock frozen and return its coordinators.

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
    """WAN download/upload sensors report the router's B/s rate, displayed as Mbit/s."""
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

    # These two ride the 10s fast coordinator and would write ~8,600 recorder
    # rows a day each, so they ship disabled: registered, but never added to
    # hass until the user opts in. Enable them and reload to get live states.
    for entity_id in (download_id, upload_id):
        assert (
            registry.async_get(entity_id).disabled_by
            is er.RegistryEntryDisabler.INTEGRATION
        )
        assert hass.states.get(entity_id) is None
        registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    for entity_id, key in ((download_id, "speed_rx"), (upload_id, "speed_tx")):
        state = hass.states.get(entity_id)
        assert state is not None
        # The API reports bytes/sec; the entities suggest Mbit/s, so HA converts
        # the state itself (1 B/s == 8e-6 Mbit/s). suggested_display_precision
        # only rounds what the frontend renders.
        assert (
            state.attributes["unit_of_measurement"]
            == UnitOfDataRate.MEGABITS_PER_SECOND
        )
        # The native value is first rounded to 3 significant figures to keep the
        # recorder from storing meaningless jitter (computed here with format
        # spec 'g' rather than the integration's own helper).
        rounded = float(f"{wan_speed[key]:.3g}")
        assert float(state.state) == pytest.approx(rounded * 8 / 1_000_000)
        if rounded != wan_speed[key]:
            # ...and the rounding is really applied, not a no-op.
            assert float(state.state) != pytest.approx(wan_speed[key] * 8 / 1_000_000)
        assert (
            registry.async_get(entity_id).options["sensor"][
                "suggested_display_precision"
            ]
            == 2
        )


async def test_tailscale_status_sensor_reflects_connection_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The tailscale status sensor mirrors the connection state enum."""
    # Tailscale rides the slow (configuration) coordinator.
    coordinator = (await _setup_at(hass, mock_config_entry, freezer)).slow
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
    # router_status (and therefore uptime) rides the hub coordinator.
    coordinator = (await _setup_at(hass, mock_config_entry, freezer)).main
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
    coordinator = (await _setup_at(hass, mock_config_entry, freezer)).main
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
    # wan_status rides the hub coordinator.
    coordinator = (await _setup_at(hass, mock_config_entry, freezer)).main
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"glinet4_sensor/{profile.factory_mac}/wan_ip"
    )
    down = dict(wan_status)
    down["ipv4"] = None
    mock_glinet.wan_status.return_value = down
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unknown"

async def test_firewall_count_sensors_report_counts(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Port-forward and custom-rule count sensors reflect the firewall lists."""
    mock_glinet.firewall_port_forward_list.side_effect = None
    mock_glinet.firewall_port_forward_list.return_value = [
        {"name": "web", "proto": "tcp", "src_dport": "443"},
        {"name": "ssh", "proto": "tcp", "src_dport": "22"},
    ]
    mock_glinet.firewall_rule_list.side_effect = None
    mock_glinet.firewall_rule_list.return_value = [{"name": "block-1"}]
    await _setup_at(hass, mock_config_entry, freezer)

    mac = profile.factory_mac
    pf = hass.states.get(_data_entity_id(hass, mac, "firewall_port_forwards"))
    assert pf.state == "2"
    assert len(pf.attributes["rules"]) == 2
    assert hass.states.get(_data_entity_id(hass, mac, "firewall_rules")).state == "1"


async def test_firewall_count_sensors_report_zero_when_empty(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An answered-but-empty firewall list is a real 0, not an absent sensor."""
    mock_glinet.firewall_port_forward_list.side_effect = None
    mock_glinet.firewall_port_forward_list.return_value = []
    mock_glinet.firewall_rule_list.side_effect = None
    mock_glinet.firewall_rule_list.return_value = []
    await _setup_at(hass, mock_config_entry, freezer)

    mac = profile.factory_mac
    assert (
        hass.states.get(_data_entity_id(hass, mac, "firewall_port_forwards")).state
        == "0"
    )
    assert hass.states.get(_data_entity_id(hass, mac, "firewall_rules")).state == "0"


async def test_firewall_count_sensors_absent_when_unsupported(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,  # noqa: ARG001  (leaves firewall reads raising)
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A router that doesn't answer the firewall lists gets no count sensors."""
    await _setup_at(hass, mock_config_entry, freezer)
    mac = profile.factory_mac
    assert _data_entity_id(hass, mac, "firewall_port_forwards") is None
    assert _data_entity_id(hass, mac, "firewall_rules") is None


# A fixed clock; peer handshakes below are expressed relative to it so the
# "connected within the handshake window" derivation is deterministic. Matches
# the instant _setup_at freezes to.
_FROZEN_TS = datetime(2026, 1, 1, tzinfo=UTC).timestamp()


async def test_wireguard_server_sensor_counts_connected_peers(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """State is the count of peers whose handshake is within the live window."""
    mock_glinet.wireguard_server_status.side_effect = None
    mock_glinet.wireguard_server_status.return_value = {
        "server": {"status": 1},
        "peers": [
            {
                "name": "phone",
                "rx_bytes": 10,
                "tx_bytes": 20,
                "latest_handshake": int(_FROZEN_TS - 60),
            },  # recent -> connected
            {
                "name": "laptop",
                "rx_bytes": 0,
                "tx_bytes": 0,
                "latest_handshake": int(_FROZEN_TS - 600),
            },  # stale -> not connected
        ],
    }
    await _setup_at(hass, mock_config_entry, freezer)

    state = hass.states.get(
        _data_entity_id(hass, profile.factory_mac, "wireguard_server_peers")
    )
    assert state.state == "1"
    assert state.attributes["total_peers"] == 2
    assert {p["name"] for p in state.attributes["peers"]} == {"phone", "laptop"}


async def test_openvpn_server_users_sensor_counts_users(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """State is the number of configured OpenVPN server users."""
    mock_glinet.openvpn_server_users.side_effect = None
    mock_glinet.openvpn_server_users.return_value = [{"name": "alice"}, {"name": "bob"}]
    await _setup_at(hass, mock_config_entry, freezer)

    state = hass.states.get(
        _data_entity_id(hass, profile.factory_mac, "openvpn_server_users")
    )
    assert state.state == "2"


async def test_vpn_server_sensors_absent_when_unsupported(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_glinet: AsyncMock,  # noqa: ARG001  (leaves the reads raising)
    profile: Profile,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A router that doesn't answer the VPN-server reads gets no such sensors."""
    await _setup_at(hass, mock_config_entry, freezer)
    mac = profile.factory_mac
    assert _data_entity_id(hass, mac, "wireguard_server_peers") is None
    assert _data_entity_id(hass, mac, "openvpn_server_users") is None
