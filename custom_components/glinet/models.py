"""Data models shared across the GL-iNet integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from homeassistant.util import dt as dt_util


class DeviceInterfaceType(StrEnum):
    """Enum for the possible interface types reported by glipy."""

    WIFI_24 = "2.4GHz"
    WIFI_5 = "5GHz"
    LAN = "LAN"
    WIFI_24_GUEST = "2.4GHz Guest"
    WIFI_5_GUEST = "5GHz Guest"
    UNKNOWN = "Unknown"
    DONGLE = "Dongle"
    BYPASS_ROUTE = "Bypass Route"
    UNKNOWN2 = "Unknown"
    MLO = "MLO"
    MLO_GUEST = "MLO Guest"
    WIFI_6 = "6GHz"
    WIFI_6_GUEST = "6GHz Guest"


@dataclass
class WireGuardClient:
    """Class for keeping track of WireGuard Client Configs."""

    name: str
    connected: bool = field(compare=False)
    group_id: int
    peer_id: int
    tunnel_id: int | None


@dataclass
class WifiInterface:
    """Class for keeping track of Wifi Interfaces."""

    name: str
    enabled: bool
    ssid: str
    guest: bool
    hidden: bool
    encryption: str


class ClientDevInfo:
    """Representation of a device connected to the router."""

    def __init__(self, mac: str, name: str | None = None) -> None:
        """Initialize a connected device."""
        self._mac: str = mac
        self._name: str | None = name
        self._ip_address: str | None = None
        self._last_activity: datetime = dt_util.utcnow() - timedelta(days=1)
        self._connected: bool = False
        self._if_type: DeviceInterfaceType = DeviceInterfaceType.UNKNOWN

    def update(self, dev_info: dict | None = None, consider_home: int = 0) -> None:
        """Update connected device info."""
        now: datetime = dt_util.utcnow()
        if dev_info:
            # Prefer the user-defined alias as a name
            alias = dev_info.get("alias")
            if alias and alias.strip():
                self._name = alias
            else:
                # If no alias, fallback to auto-assigned name field
                name = dev_info.get("name", "")
                if name == "*" or not name.strip():
                    self._name = self._mac.replace(":", "_")
                else:
                    self._name = name
            self._ip_address = dev_info.get("ip")
            self._last_activity = now
            self._connected = dev_info.get("online", False)
            self._if_type = list(DeviceInterfaceType)[
                dev_info.get("type", 5)
            ]  # TODO be more index safe
        # a device might not actually be online but we want to consider it home
        elif self._connected:
            self._connected = (
                now - self._last_activity
            ).total_seconds() < consider_home
            self._ip_address = None

    @property
    def is_connected(self) -> bool:
        """Return connected status."""
        return self._connected

    @property
    def interface_type(self) -> DeviceInterfaceType:
        """Return device interface type."""
        return self._if_type

    @property
    def mac(self) -> str:
        """Return device mac address."""
        return self._mac

    @property
    def name(self) -> str | None:
        """Return device name."""
        return self._name

    @property
    def ip_address(self) -> str | None:
        """Return device ip address."""
        return self._ip_address

    @property
    def last_activity(self) -> datetime:
        """Return device last activity."""
        return self._last_activity
