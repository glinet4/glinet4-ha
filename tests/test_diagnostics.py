"""Tests for GL.iNet diagnostics."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glinet4.diagnostics import async_get_config_entry_diagnostics
from homeassistant.core import HomeAssistant

from .conftest import Profile


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant, init_integration: MockConfigEntry, profile: Profile
) -> None:
    """Diagnostics expose device state but redact credentials and identifiers."""
    # Diagnostics dump the hub coordinator's snapshot. ``connected_devices`` is
    # a scalar produced by the tracker coordinator, which primes *after* the
    # hub's first refresh, so it only reaches the hub's snapshot on the hub's
    # next poll. Drive that poll before dumping.
    await init_integration.runtime_data.main.async_refresh()
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)

    # Credentials and identifiers from the entry/data must not leak verbatim.
    blob = str(diagnostics)
    for secret in ("test-password", "test-token", profile.factory_mac):
        assert secret not in blob

    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["api_token"] == "**REDACTED**"

    # ...while non-secret device state is still present.
    assert diagnostics["device"]["model"] == profile.manifest["model"]
    assert (
        diagnostics["data"]["connected_devices"]
        == (profile.manifest["expected"]["connected_client_count"])
    )
