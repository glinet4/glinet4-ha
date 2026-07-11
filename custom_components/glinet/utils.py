"""Utility functions for GL-iNet routers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gli4py.error_handling import APIClientError

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Awaitable


async def async_run_action[T](action: Awaitable[T], *, device: str) -> T:
    """Await a router action, converting failures to HomeAssistantError.

    A user-initiated action that fails should surface a clean, translated
    error rather than a raw library/transport exception or a swallowed log
    line, so the frontend shows why the action did not take effect.
    """
    try:
        return await action
    except (APIClientError, OSError, TimeoutError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="action_failed",
            translation_placeholders={"device": device, "error": str(err)},
        ) from err


def adjust_mac(mac: str, delta: int, sep: str = ":") -> str:
    """Increment a MAC address by 1.

    This is helpful because GL-iNet devices' LAN ports have a mac of factory_mac + 1
    but this is not found in the API
    :param mac: Original MAC address (e.g. "00:1A:2B:3C:4D:5E" or "00-1A-2B-3C-4D-5E").
    :param sep: Separator to use in the output (default is ':').
    :return: Incremented MAC address as a string.
    """
    # Remove common separators and convert to integer
    hex_str = mac.replace(sep, "").replace("-", "").lower()
    value = int(hex_str, 16)

    # Increment and wrap around at 48 bits
    value = (value + delta) & ((1 << 48) - 1)

    # Format back to hexadecimal, ensuring six bytes (12 hex digits)
    new_hex = f"{value:012x}"

    # Reinsert the separator every two hex digits
    return sep.join(new_hex[i : i + 2] for i in range(0, 12, 2)).lower()
