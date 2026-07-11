"""Tests for the GL-iNet repair issues."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet.const import DOMAIN, ISSUE_STATISTICS_NOT_COLLECTING
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
    base = Path("custom_components/glinet")
    strings = json.loads((base / "strings.json").read_text())
    en = json.loads((base / "translations" / "en.json").read_text())

    assert strings["issues"] == en["issues"]
    issue = strings["issues"][ISSUE_STATISTICS_NOT_COLLECTING]
    # Non-fixable issues render a title + description; no fix_flow.
    assert issue["title"]
    assert issue["description"]
    assert "fix_flow" not in issue
