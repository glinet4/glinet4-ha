"""Tests for the GL.iNet repair issues."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from glinet4.enums import TailscaleConnection
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.const import DOMAIN, ISSUE_STATISTICS_NOT_COLLECTING
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir


def _issue_id(entry: MockConfigEntry) -> str:
    return f"statistics_not_collecting_{entry.entry_id}"


def _force(mock_glinet: AsyncMock, *, stats_on: bool, accel_on: bool) -> None:
    """Pin the stats/acceleration state regardless of the active profile."""
    mock_glinet.flow_stats_rule.side_effect = None
    mock_glinet.flow_stats_rule.return_value = {
        "enable": stats_on,
        "type": "app",
        "time": "day",
    }
    mock_glinet.network_acceleration.side_effect = None
    mock_glinet.network_acceleration.return_value = {
        "enable": accel_on,
        "dpi_enabled": True,
        "qos_enabled": not accel_on,
        "actype": 1,
    }


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_issue_raised_when_stats_on_but_not_accelerated(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """Stats enabled while acceleration is off raises an informational issue."""
    _force(mock_glinet, stats_on=True, accel_on=False)
    await _setup(hass, mock_config_entry)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(mock_config_entry))
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "statistics_not_collecting"
    assert "device" in (issue.translation_placeholders or {})


async def test_no_issue_when_stats_off(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """No issue when statistics are disabled."""
    _force(mock_glinet, stats_on=False, accel_on=False)
    await _setup(hass, mock_config_entry)
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(mock_config_entry)) is None
    )


async def test_no_issue_when_accelerated(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """No issue when acceleration is on (stats will collect)."""
    _force(mock_glinet, stats_on=True, accel_on=True)
    await _setup(hass, mock_config_entry)
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(mock_config_entry)) is None
    )


async def test_issue_cleared_when_condition_resolves(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """Enabling acceleration clears a previously-raised issue."""
    _force(mock_glinet, stats_on=True, accel_on=False)
    await _setup(hass, mock_config_entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(mock_config_entry))

    _force(mock_glinet, stats_on=True, accel_on=True)
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(mock_config_entry)) is None
    )


async def test_issue_removed_on_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """Unloading the entry removes its repair issue."""
    _force(mock_glinet, stats_on=True, accel_on=False)
    await _setup(hass, mock_config_entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(mock_config_entry))

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(mock_config_entry)) is None
    )


def test_issue_translations_present_and_consistent() -> None:
    """The repair issue's translation key exists and both files agree.

    Mirrors what hassfest enforces in CI: every translation_key used with
    async_create_issue must exist under 'issues' in strings.json, and
    translations/en.json must match.
    """
    base = Path("custom_components/glinet4")
    strings = json.loads((base / "strings.json").read_text())
    en = json.loads((base / "translations" / "en.json").read_text())

    assert strings["issues"] == en["issues"]
    assert strings.get("exceptions") == en.get("exceptions")
    for key in (
        ISSUE_STATISTICS_NOT_COLLECTING,
        "tailscale_reauth_required",
        "router_mode",
    ):
        issue = strings["issues"][key]
        # Non-fixable issues render a title + description; no fix_flow.
        assert issue["title"]
        assert issue["description"]
        assert "fix_flow" not in issue


def _tailscale_issue_id(entry: MockConfigEntry) -> str:
    return f"tailscale_reauth_required_{entry.entry_id}"


def _router_mode_issue_id(entry: MockConfigEntry) -> str:
    return f"router_mode_{entry.entry_id}"


def _force_tailscale(mock_glinet: AsyncMock, state: str, url: str | None) -> None:
    """Pin the tailscale connection state and auth url."""
    mock_glinet.tailscale_configured.return_value = True
    mock_glinet.tailscale_connection_state.return_value = TailscaleConnection[
        state.upper()
    ]
    mock_glinet.tailscale_auth_url.return_value = url


async def test_tailscale_reauth_issue_raised_when_login_required(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A login-required tailscale state raises the re-auth issue."""
    _force_tailscale(mock_glinet, "login_required", "https://login.tailscale.com/a/x")
    await _setup(hass, mock_config_entry)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, _tailscale_issue_id(mock_config_entry)
    )
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "tailscale_reauth_required"
    assert issue.learn_more_url


async def test_tailscale_reauth_issue_absent_when_connected(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """No re-auth issue while tailscale is connected."""
    _force_tailscale(mock_glinet, "connected", None)
    await _setup(hass, mock_config_entry)
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, _tailscale_issue_id(mock_config_entry)
        )
        is None
    )


async def test_tailscale_reauth_issue_cleared_on_reconnect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """Reconnecting clears a previously-raised re-auth issue."""
    _force_tailscale(mock_glinet, "login_required", "https://login.tailscale.com/a/x")
    await _setup(hass, mock_config_entry)
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, _tailscale_issue_id(mock_config_entry)
    )
    _force_tailscale(mock_glinet, "connected", None)
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, _tailscale_issue_id(mock_config_entry)
        )
        is None
    )


async def test_router_mode_issue_raised_in_ap_mode(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """A non-router operating mode raises the router-mode issue."""
    mock_glinet.network_mode.side_effect = None
    mock_glinet.network_mode.return_value = "ap"
    await _setup(hass, mock_config_entry)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, _router_mode_issue_id(mock_config_entry)
    )
    assert issue is not None
    assert issue.translation_key == "router_mode"
    assert issue.translation_placeholders.get("mode") == "ap"


async def test_router_mode_issue_absent_in_router_mode(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """No issue when the router is in router mode."""
    mock_glinet.network_mode.side_effect = None
    mock_glinet.network_mode.return_value = "router"
    await _setup(hass, mock_config_entry)
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, _router_mode_issue_id(mock_config_entry)
        )
        is None
    )


async def test_all_issues_removed_on_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_glinet: AsyncMock
) -> None:
    """Unloading clears every repair issue this entry raised."""
    _force(mock_glinet, stats_on=True, accel_on=False)
    _force_tailscale(mock_glinet, "login_required", "https://login.tailscale.com/a/x")
    mock_glinet.network_mode.side_effect = None
    mock_glinet.network_mode.return_value = "ap"
    await _setup(hass, mock_config_entry)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, _issue_id(mock_config_entry))
    assert registry.async_get_issue(DOMAIN, _tailscale_issue_id(mock_config_entry))
    assert registry.async_get_issue(DOMAIN, _router_mode_issue_id(mock_config_entry))

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, _issue_id(mock_config_entry)) is None
    assert (
        registry.async_get_issue(DOMAIN, _tailscale_issue_id(mock_config_entry)) is None
    )
    assert (
        registry.async_get_issue(DOMAIN, _router_mode_issue_id(mock_config_entry))
        is None
    )
