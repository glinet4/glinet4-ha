"""DataUpdateCoordinator for the GL.iNet integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, TypeVar, cast

from glinet4 import GLinet
from glinet4.enums import TailscaleConnection
from glinet4.error_handling import AuthenticationError, NonZeroResponse, TokenError
from homeassistant.components.device_tracker import (
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
    DOMAIN as TRACKER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, format_mac
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    API_PATH,
    DOMAIN,
    FAST_SCAN_INTERVAL,
    ISSUE_ROUTER_MODE,
    ISSUE_STATISTICS_NOT_COLLECTING,
    ISSUE_TAILSCALE_REAUTH,
    SCAN_INTERVAL,
    SLOW_SCAN_INTERVAL,
    TRACKER_SCAN_INTERVAL,
)
from .models import ClientDevInfo, WifiInterface, WireGuardClient
from .utils import adjust_mac

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_registry import RegistryEntry

_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")

# The online firmware check talks to GL.iNet's update servers, so it runs far
# less often than the router poll.
FIRMWARE_CHECK_INTERVAL = timedelta(hours=6)

# A WireGuard peer is treated as connected when its last handshake is within
# this window; WireGuard renegotiates roughly every 2 minutes, so 3 covers a
# live peer without flagging one that has just dropped.
WG_HANDSHAKE_TIMEOUT_S = 180


@dataclass
class GLinetData:
    """Snapshot of router state exposed to entities each refresh.

    Holds references to the coordinator's working collections (not copies);
    entities read it fresh after every coordinator update.
    """

    system_status: dict = field(default_factory=dict)
    devices: dict[str, ClientDevInfo] = field(default_factory=dict)
    connected_devices: int = 0
    wifi_ifaces: dict[str, WifiInterface] = field(default_factory=dict)
    wireguard_clients: dict[int, WireGuardClient] = field(default_factory=dict)
    wireguard_connections: list[WireGuardClient] = field(default_factory=list)
    tailscale_config: dict = field(default_factory=dict)
    tailscale_connection: bool | None = None
    tailscale_state: str | None = None
    tailscale_auth_url: str | None = None
    tailscale_exit_nodes: list[dict] = field(default_factory=list)
    wan_status: dict = field(default_factory=dict)
    wan_speed: dict = field(default_factory=dict)
    firmware_check: dict = field(default_factory=dict)
    led_config: dict = field(default_factory=dict)
    network_interfaces: list[dict] = field(default_factory=list)
    flow_stats_rule: dict = field(default_factory=dict)
    network_acceleration: dict = field(default_factory=dict)
    network_mode: str = ""
    firewall_wan_access: dict = field(default_factory=dict)
    firewall_dmz: dict = field(default_factory=dict)
    # None until the router answers the read, so an empty list (0 rules) is
    # distinguishable from an unsupported endpoint.
    firewall_port_forwards: list[dict] | None = None
    firewall_rules: list[dict] | None = None
    # None until the router answers the read, distinguishing an unconfigured/
    # empty server from an endpoint the firmware doesn't expose.
    wireguard_server: dict | None = None
    openvpn_server_users: list | None = None


class GLinetUpdateCoordinator(DataUpdateCoordinator[GLinetData]):
    """Coordinate polling of a GL.iNet router and own its API client.

    Replaces the old ``GLinetRouter``: it holds the device identity and the
    glinet4 client, and produces a ``GLinetData`` snapshot every ``SCAN_INTERVAL``
    which all entities consume via ``CoordinatorEntity``.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        # always_update stays True (default): trackers mutate state in place, so
        # always_update=False would compare snapshots equal and drop their updates.
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self._options: dict = dict(entry.options)

        self._api: GLinet
        self._host: str = entry.data[CONF_HOST]

        self._factory_mac: str = "UNKNOWN"
        self._model: str = "UNKNOWN"
        self._sw_v: str = "UNKNOWN"

        self._devices: dict[str, ClientDevInfo] = {}
        self._connected_devices: int = 0
        self._wifi_ifaces: dict[str, WifiInterface] = {}
        self._system_status: dict = {}
        self._wireguard_clients: dict[int, WireGuardClient] = {}
        self._wireguard_connections: list[WireGuardClient] = []
        self._tailscale_config: dict = {}
        self._tailscale_connection: bool | None = None
        self._tailscale_state: str | None = None
        self._tailscale_auth_url: str | None = None
        self._tailscale_exit_nodes: list[dict] = []
        self._wan_status: dict = {}
        self._wan_speed: dict = {}
        self._firmware_check: dict = {}
        self._firmware_check_at: datetime | None = None
        self._led_config: dict = {}
        self._network_interfaces: list[dict] = []
        self._flow_stats_rule: dict = {}
        self._network_acceleration: dict = {}
        self._network_mode: str = ""
        self._firewall_wan_access: dict = {}
        self._firewall_dmz: dict = {}
        self._firewall_port_forwards: list[dict] | None = None
        self._firewall_rules: list[dict] | None = None
        self._wireguard_server: dict | None = None
        self._openvpn_server_users: list | None = None
        # Optional-endpoint probe results: confirmed on first success,
        # unsupported on a NonZeroResponse before any success.
        self._confirmed_endpoints: set[str] = set()
        self._unsupported_endpoints: set[str] = set()

        self._late_init_complete: bool = False
        self._connect_error: bool = False
        self._token_error: bool = False
        # Set by _update_platform when any call hits a transport error this
        # cycle, so _async_update_data can fail the whole refresh
        self._cycle_failed: bool = False
        # Set by _call_optional when an *optional* endpoint fails for transport
        # or auth reasons rather than being unsupported. The hub ignores it (a
        # flaky optional endpoint must not take down the whole refresh, since
        # its mandatory calls still prove reachability), but a sibling whose
        # bucket is entirely optional has no such proof and uses it to fail.
        self._optional_transport_failed: bool = False
        # Serialises refreshes across all four coordinators. They share this
        # object's working state, so without it an overlapping refresh can
        # clear a failure flag another one just set, or interleave writes and
        # yield a snapshot mixing two polls.
        self._refresh_lock = asyncio.Lock()

    async def async_setup(self) -> None:
        """Authenticate, load identity and restore known trackers.

        Called once from ``async_setup_entry`` before the first refresh.
        """
        if not self._late_init_complete:
            await self.async_init()

        # Restore device-tracker entities saved from a previous run so we keep
        # reporting them (and apply consider_home) even before they reappear.
        entity_registry = er.async_get(self.hass)
        track_entries: list[RegistryEntry] = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        for entry in track_entries:
            if entry.domain == TRACKER_DOMAIN:
                self._devices[entry.unique_id] = ClientDevInfo(
                    entry.unique_id, entry.original_name
                )

        await self.renew_token()

    async def async_init(self) -> None:
        """Connect to the router and read its stable identity."""
        try:
            self._api = await self.get_api()
            await self._api.login(
                self.config_entry.data[CONF_USERNAME],
                self.config_entry.data[CONF_PASSWORD],
            )
        except OSError as exc:
            _LOGGER.exception("Error connecting to GL.iNet router %s", self._host)
            raise ConfigEntryNotReady from exc
        try:
            router_info = await self._update_platform(self._api.router_info)
            assert router_info is not None
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Error getting basic device info from GL.iNet router %s", self._host
            )
            raise ConfigEntryNotReady from exc

        _LOGGER.debug("Router info retrieved: %s", router_info)
        self._model = router_info["model"]
        self._sw_v = router_info["firmware_version"]
        self._factory_mac = router_info["mac"]
        self._late_init_complete = True

    async def get_api(self) -> GLinet:
        """Optimistically return a GLinet client, no test included."""
        conf = self.config_entry.data
        shared_session = async_get_clientsession(self.hass)

        if CONF_PASSWORD in conf:
            router = GLinet(base_url=conf[CONF_HOST] + API_PATH, session=shared_session)
            await router.login(conf[CONF_USERNAME], conf[CONF_PASSWORD])
            return router
        _LOGGER.error(
            "Error setting up GL.iNet router, no auth details found in configuration"
        )
        raise ConfigEntryAuthFailed

    async def renew_token(self) -> None:
        """Attempt to get a new token."""
        try:
            await self._api.login(
                self.config_entry.data[CONF_USERNAME],
                self.config_entry.data[CONF_PASSWORD],
            )
            _LOGGER.info("GL.iNet router %s token was renewed", self._host)
        except (AuthenticationError, TokenError) as exc:
            _LOGGER.exception(
                "GL.iNet %s failed to renew the token, have you changed your router password?",
                self._host,
            )
            raise ConfigEntryAuthFailed from exc
        except Exception as exc:
            _LOGGER.warning(
                "Could not connect to GL.iNet router to renew token: %s", exc
            )
            raise  # Let generic network/timeout exceptions bubble up normally

    async def _async_update_data(self) -> GLinetData:
        """Fetch the medium-rate slice of router state.

        Device trackers, WAN throughput and the near-static configuration
        endpoints are polled by the sibling coordinators built in
        ``async_setup_entry``; see ``const.SCAN_INTERVAL`` for the bucketing
        rationale. This coordinator keeps ``router_status`` because a failure
        there is the signal that the router is unreachable.
        """
        async with self._refresh_lock:
            self.reset_cycle()
            status = await self._update_platform(self._api.router_status)
            if status is None:
                # The core health call failed (router unreachable / token not
                # yet recovered). Surface it so entities go unavailable; the
                # token error flag triggers a renewal attempt next cycle.
                raise UpdateFailed(f"Unable to reach GL.iNet router {self._host}")
            self._system_status = status.get("system", {})

            await self.update_wifi_ifaces_state()
            await self.update_wireguard_client_state()
            await self.update_wan_state()

            self.raise_if_cycle_failed()
            self.async_manage_repair_issues()
            return self.snapshot()

    @property
    def refresh_lock(self) -> asyncio.Lock:
        """Return the lock serialising refreshes across all coordinators."""
        return self._refresh_lock

    def reset_cycle(self) -> None:
        """Clear the per-cycle failure flags before a refresh."""
        self._cycle_failed = False
        self._optional_transport_failed = False

    @property
    def optional_transport_failed(self) -> bool:
        """Whether an optional endpoint failed for transport/auth reasons."""
        return self._optional_transport_failed

    def raise_if_cycle_failed(self) -> None:
        """Fail the refresh if any call hit a transport error this cycle."""
        if self._cycle_failed:
            raise UpdateFailed(
                f"One or more calls to GL.iNet router {self._host} failed"
            )

    def snapshot(self) -> GLinetData:
        """Build a snapshot from the shared working state.

        Every coordinator returns this same shape, so entities read
        ``coordinator.data.<field>`` regardless of which one drives them; only
        the callback cadence differs.
        """
        return GLinetData(
            system_status=self._system_status,
            devices=self._devices,
            connected_devices=self._connected_devices,
            wifi_ifaces=self._wifi_ifaces,
            wireguard_clients=self._wireguard_clients,
            wireguard_connections=self._wireguard_connections,
            tailscale_config=self._tailscale_config,
            tailscale_connection=self._tailscale_connection,
            tailscale_state=self._tailscale_state,
            tailscale_auth_url=self._tailscale_auth_url,
            tailscale_exit_nodes=self._tailscale_exit_nodes,
            wan_status=self._wan_status,
            wan_speed=self._wan_speed,
            firmware_check=self._firmware_check,
            led_config=self._led_config,
            network_interfaces=self._network_interfaces,
            flow_stats_rule=self._flow_stats_rule,
            network_acceleration=self._network_acceleration,
            network_mode=self._network_mode,
            firewall_wan_access=self._firewall_wan_access,
            firewall_dmz=self._firewall_dmz,
            firewall_port_forwards=self._firewall_port_forwards,
            firewall_rules=self._firewall_rules,
            wireguard_server=self._wireguard_server,
            openvpn_server_users=self._openvpn_server_users,
        )

    def async_build_siblings(self) -> GLinetRuntimeData:
        """Create the sibling coordinators that share this one's API client.

        They reuse the hub's client, auth recovery and working state; only the
        set of endpoints polled and the interval differ.
        """
        return GLinetRuntimeData(
            main=self,
            fast=GLinetSubCoordinator(
                self,
                name=f"{DOMAIN} wan speed",
                update_interval=FAST_SCAN_INTERVAL,
                update=lambda hub: hub.update_wan_speed(),
            ),
            trackers=GLinetSubCoordinator(
                self,
                name=f"{DOMAIN} device trackers",
                update_interval=TRACKER_SCAN_INTERVAL,
                update=lambda hub: hub.update_device_trackers(),
            ),
            slow=GLinetSubCoordinator(
                self,
                name=f"{DOMAIN} configuration",
                update_interval=SLOW_SCAN_INTERVAL,
                update=GLinetUpdateCoordinator._update_slow_state,
            ),
        )

    async def _update_slow_state(self) -> None:
        """Poll the endpoints that change on the order of days, not seconds."""
        await self.update_tailscale_state()
        await self.update_led_state()
        await self.update_flow_statistics_state()
        await self.update_firewall_state()
        await self.update_vpn_server_state()
        await self.update_firmware_check()

    async def _update_platform(
        self, api_callable: Callable[[], Coroutine[Any, Any, T]]
    ) -> T | None:
        """Boilerplate to make update requests to api and handle errors."""
        # TODO: replace the hand-rolled _token_error/_connect_error recovery
        # with ConfigEntryAuthFailed (auth) + UpdateFailed (transport), letting
        # the coordinator handle retry/availability (the modern HA pattern).
        try:
            if self._token_error:
                _LOGGER.debug(
                    "The last requested resulted in a token error - so renewing token"
                )
                await self.renew_token()
            if self._connect_error:
                _LOGGER.debug("Got pending connect error - attempting to renew token")
                await self.renew_token()
            _LOGGER.debug(
                "Making api call %s from _update_platform()", api_callable.__name__
            )
            response = await api_callable()
        except TimeoutError:
            self._cycle_failed = True
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.exception(
                    "GL.iNet router %s did not respond in time", self._host
                )
            return None
        except TokenError as exc:
            self._cycle_failed = True
            self._token_error = True
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.warning(
                    "GL.iNet router %s token was refused %s, will try to re-autheticate before next poll",
                    self._host,
                    exc,
                )
            return None
        except NonZeroResponse:
            self._cycle_failed = True
            if not self._connect_error:
                self._connect_error = True
                _LOGGER.exception(
                    "GL.iNet router %s responded, but with an error code", self._host
                )
            return None
        except ConfigEntryAuthFailed:
            # Bubble up to Home Assistant to pause polling and trigger re-auth
            raise
        except Exception:  # pylint: disable=broad-except  # noqa: BLE001
            self._cycle_failed = True
            if not self._connect_error:
                self._connect_error = True
            _LOGGER.exception(
                "GL.iNet router %s responded with an unexpected error", self._host
            )
            return None

        if not response:
            _LOGGER.debug(
                "Invalid response from %s to request %s is of type %s, Response: %s",
                self._host,
                api_callable.__name__,
                str(type(response)),
                str(response),
            )

        if self._token_error:
            self._token_error = False
            _LOGGER.info(
                "GL.iNet %s new token has successfully made an API call, token marked as valid",
                self._host,
            )

        if self._connect_error:
            self._connect_error = False
            _LOGGER.info("Reconnected to GL.iNet router %s", self._host)
        return response

    async def update_device_trackers(self) -> None:
        """Update the device trackers."""
        wrt_devices = await self._update_platform(self._api.connected_clients)
        if not wrt_devices:
            _LOGGER.warning(
                "Router returned no valid connected devices. It returned %s of type %s",
                str(wrt_devices),
                type(wrt_devices),
            )
            if wrt_devices is None or wrt_devices == {}:
                self._connected_devices = 0
            return
        consider_home = self._options.get(
            CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds()
        )

        for device_mac, device in self._devices.items():
            dev_info = wrt_devices.get(device_mac)
            device.update(
                dev_info, consider_home, model=self._model, firmware=self._sw_v
            )

        for device_mac, dev_info in wrt_devices.items():
            if device_mac in self._devices:
                continue

            alias = str(dev_info.get("alias", "")).strip()
            name = str(dev_info.get("name", "")).strip()
            if not alias and not name:
                continue

            device = ClientDevInfo(device_mac)
            device.update(dev_info, model=self._model, firmware=self._sw_v)
            self._devices[device_mac] = device

        self._connected_devices = len(wrt_devices)

    async def update_wifi_ifaces_state(self) -> None:
        """Make a call to the API to get the WiFi ifaces config state."""
        ifaces = await self._update_platform(self._api.wifi_ifaces)
        if not ifaces:
            return
        # Rebuild the mapping each poll so an interface that disappears from the
        # router doesn't linger in the snapshot.
        self._wifi_ifaces = {
            name: WifiInterface(
                name=name,
                enabled=iface.get("enabled", False),
                ssid=iface.get("ssid", ""),
                guest=iface.get("guest", False),
                hidden=iface.get("hidden", False),
                encryption=iface.get("encryption", "UNKNOWN"),
            )
            for name, iface in ifaces.items()
        }

    async def update_tailscale_state(self) -> None:
        """Make a call to the API to get the tailscale state."""
        # tailscale_configured() is a plain API call (no _update_platform
        # wrapper), so guard it: a transient error must not abort the whole
        # refresh or escape uncaught.
        try:
            configured = await self._api.tailscale_configured()
        except (TimeoutError, NonZeroResponse, TokenError, OSError) as err:
            _LOGGER.debug("Could not determine tailscale state: %s", err)
            return
        if not configured:
            self._tailscale_config = {}
            self._tailscale_connection = None
            self._tailscale_state = None
            self._tailscale_auth_url = None
            self._tailscale_exit_nodes = []
            return
        # TODO: public API in a future glinet4 release
        ts_config = await self._update_platform(
            self._api._tailscale_get_config  # pylint: disable=protected-access  # noqa: SLF001
        )
        self._tailscale_config = dict(ts_config) if isinstance(ts_config, dict) else {}
        response: TailscaleConnection | None = await self._update_platform(
            self._api.tailscale_connection_state
        )
        self._tailscale_connection = response == TailscaleConnection.CONNECTED
        self._tailscale_state = response.name.lower() if response is not None else None
        exit_nodes = await self._call_optional(
            "tailscale_exit_node_list", self._api.tailscale_exit_node_list
        )
        if exit_nodes is not None:
            self._tailscale_exit_nodes = [dict(n) for n in exit_nodes]
        self._tailscale_auth_url = None
        if response in (
            TailscaleConnection.LOGIN_REQUIRED,
            TailscaleConnection.AUTHORIZATION_REQUIRED,
        ):
            # The firmware's own toggle path ('tailscale up --reset') can drop
            # node auth; the login URL lets the user recover from HA.
            self._tailscale_auth_url = await self._call_optional(
                "tailscale_auth_url", self._api.tailscale_auth_url
            )

    async def _call_optional(
        self, name: str, api_callable: Callable[[], Coroutine[Any, Any, T]]
    ) -> T | None:
        """Call an endpoint that may not exist on this firmware.

        A NonZeroResponse before the endpoint has ever succeeded marks it
        unsupported for the lifetime of the entry; afterwards (and for
        auth/transport errors, which the mandatory calls in the same cycle
        recover via renew_token) the failure is transient and returns None
        so callers keep their last good value.
        """
        if name in self._unsupported_endpoints:
            return None
        try:
            result = await api_callable()
        except (TimeoutError, AuthenticationError, OSError) as err:
            # AuthenticationError first: it subclasses NonZeroResponse, and an
            # auth hiccup must not mark the endpoint permanently unsupported.
            _LOGGER.debug("Optional endpoint %s failed transiently: %s", name, err)
            self._optional_transport_failed = True
            return None
        except NonZeroResponse as err:
            if name in self._confirmed_endpoints:
                _LOGGER.debug("Optional endpoint %s failed transiently: %s", name, err)
            else:
                _LOGGER.info("GL.iNet router %s does not expose %s", self._host, name)
                self._unsupported_endpoints.add(name)
            return None
        self._confirmed_endpoints.add(name)
        return result

    async def update_wan_speed(self) -> None:
        """Poll WAN throughput only - the one endpoint worth polling fast.

        Split out of ``update_wan_state`` so the fast coordinator costs exactly
        one RPC per cycle. On transient errors the previous value is kept.
        """
        speed = await self._call_optional("wan_speed", self._api.wan_speed)
        if speed is not None:
            self._wan_speed = dict(speed)

    async def update_wan_state(self) -> None:
        """Poll WAN status; degrade gracefully when unsupported.

        The endpoints only exist on newer firmware and are probed
        independently; on transient errors the previous values are kept.
        Throughput is polled separately by ``update_wan_speed``.
        """
        status, interfaces, mode = await asyncio.gather(
            self._call_optional("wan_status", self._api.wan_status),
            self._call_optional(
                "network_interfaces_status", self._api.network_interfaces_status
            ),
            self._call_optional("network_mode", self._api.network_mode),
        )
        if status is not None:
            self._wan_status = dict(status)
        if interfaces is not None:
            self._network_interfaces = [dict(i) for i in interfaces]
        if mode is not None:
            self._network_mode = mode or ""

    async def update_led_state(self) -> None:
        """Poll the LED configuration; absent on some firmware."""
        led = await self._call_optional("led_config", self._api.led_config)
        if led is not None:
            self._led_config = dict(led)

    async def update_flow_statistics_state(self) -> None:
        """Poll the flow-statistics rule and NAT-acceleration state.

        Both are optional endpoints. Acceleration state is kept so consumers
        can explain why statistics may not be collecting app data (the DPI
        accounting rides on acceleration, which conflicts with QoS/SQM).
        """
        rule, accel = await asyncio.gather(
            self._call_optional("flow_stats_rule", self._api.flow_stats_rule),
            self._call_optional("network_acceleration", self._api.network_acceleration),
        )
        if rule is not None:
            self._flow_stats_rule = dict(rule)
        if accel is not None:
            self._network_acceleration = dict(accel)

    async def update_firewall_state(self) -> None:
        """Poll the firewall reads (WAN exposure, DMZ, port forwards, rules).

        All optional per firmware; each preserves its last-good value on a
        transient failure and stays unset when the router doesn't expose it.
        """
        wan_access, dmz, port_forwards, rules = await asyncio.gather(
            self._call_optional("firewall_wan_access", self._api.firewall_wan_access),
            self._call_optional("firewall_dmz", self._api.firewall_dmz),
            self._call_optional(
                "firewall_port_forward_list", self._api.firewall_port_forward_list
            ),
            self._call_optional("firewall_rule_list", self._api.firewall_rule_list),
        )
        if wan_access is not None:
            self._firewall_wan_access = dict(wan_access)
        if dmz is not None:
            self._firewall_dmz = dict(dmz)
        if port_forwards is not None:
            self._firewall_port_forwards = [dict(rule) for rule in port_forwards]
        if rules is not None:
            self._firewall_rules = [dict(rule) for rule in rules]

    async def update_vpn_server_state(self) -> None:
        """Poll the WireGuard/OpenVPN server reads; both optional per firmware."""
        wg_status, ovpn_users = await asyncio.gather(
            self._call_optional(
                "wireguard_server_status", self._api.wireguard_server_status
            ),
            self._call_optional("openvpn_server_users", self._api.openvpn_server_users),
        )
        if wg_status is not None:
            self._wireguard_server = self._summarise_wireguard_server(wg_status)
        if ovpn_users is not None:
            self._openvpn_server_users = [dict(user) for user in ovpn_users]

    @staticmethod
    def _summarise_wireguard_server(status: dict) -> dict:
        """Reduce ``wg-server get_status`` to a connected count + safe peer stats.

        Keeps only traffic/handshake fields (never the peer key material, which
        lives in the separate ``get_peer_list`` read). A peer counts as
        connected when its last handshake is within ``WG_HANDSHAKE_TIMEOUT_S``.
        """
        now_ts = dt_util.utcnow().timestamp()
        peers = status.get("peers") or []
        summaries: list[dict] = []
        connected = 0
        for peer in peers:
            handshake = peer.get("latest_handshake") or 0
            is_connected = handshake > 0 and now_ts - handshake < WG_HANDSHAKE_TIMEOUT_S
            if is_connected:
                connected += 1
            summaries.append(
                {
                    "name": peer.get("name"),
                    "rx_bytes": peer.get("rx_bytes"),
                    "tx_bytes": peer.get("tx_bytes"),
                    "latest_handshake": handshake,
                    "connected": is_connected,
                }
            )
        return {"connected": connected, "total": len(peers), "peers": summaries}

    async def update_firmware_check(self) -> None:
        """Check online for a firmware update, at most every 6 hours."""
        now = dt_util.utcnow()
        if (
            self._firmware_check_at is not None
            and now - self._firmware_check_at < FIRMWARE_CHECK_INTERVAL
        ):
            return
        self._firmware_check_at = now
        check = await self._call_optional(
            "firmware_check_online", self._api.firmware_check_online
        )
        if check is not None:
            self._firmware_check = dict(check)

    async def update_wireguard_client_state(self) -> None:
        """Make call to the API to get the wireguard client state."""
        response = await self._update_platform(self._api.wireguard_client_list)
        if not response:
            # No clients
            self._wireguard_clients = {}
            self._wireguard_connections = []
            return
        clients = {
            config["peer_id"]: WireGuardClient(
                name=config["name"],
                connected=False,
                group_id=config["group_id"],
                peer_id=config["peer_id"],
                tunnel_id=cast("int | None", dict(config).get("tunnel_id")),
            )
            for config in response
        }
        connections: list[WireGuardClient] = []

        states = await self._update_platform(self._api.wireguard_client_state)
        for config in states or []:
            # OpenVPN configs are sometimes returned leading to errors.
            if config.get("type") != "wireguard":
                continue
            client = clients.get(config["peer_id"])
            if client is None:
                continue
            client.tunnel_id = config.get("tunnel_id", None)
            # 0 is disconnected, 1 is connected, 2 is connecting; if
            # config["enabled"] is false then status does not exist.
            client.connected = config.get("status", 0) != 0
            if client.connected:
                connections.append(client)

        self._wireguard_clients = clients
        self._wireguard_connections = connections

    def _issue_id(self, key: str) -> str:
        """Return a per-entry repair-issue id for a translation key."""
        return f"{key}_{self.config_entry.entry_id}"

    def _async_apply_issue(
        self, key: str, active: bool, placeholders: dict[str, str]
    ) -> None:
        """Raise the issue when ``active``, otherwise clear it.

        All GL.iNet repair issues are informational (``is_fixable=False``):
        each is resolved by a device-side change the user must choose, so we
        surface the requirement and let the condition clear the issue.
        """
        if active:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id(key),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders=placeholders,
                learn_more_url=self._host,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(key))

    def async_manage_repair_issues(self) -> None:
        """Raise or clear every repair issue from the current snapshot."""
        # Flow statistics enabled but not collecting (NAT acceleration off,
        # which is mutually exclusive with QoS/SQM).
        stats_on = bool(self._flow_stats_rule.get("enable"))
        accel_on = bool(self._network_acceleration.get("enable"))
        self._async_apply_issue(
            ISSUE_STATISTICS_NOT_COLLECTING,
            stats_on and not accel_on,
            {"device": self.device_name},
        )

        # Tailscale needs re-authentication (e.g. the firmware's toggle path ran
        # 'tailscale up --reset' and dropped node auth).
        self._async_apply_issue(
            ISSUE_TAILSCALE_REAUTH,
            self._tailscale_state in ("login_required", "authorization_required"),
            {"device": self.device_name},
        )

        # Router is not in router mode, so Tailscale/VPN features are
        # unavailable (the firmware rejects them outside router mode).
        self._async_apply_issue(
            ISSUE_ROUTER_MODE,
            bool(self._network_mode) and self._network_mode != "router",
            {"device": self.device_name, "mode": self._network_mode},
        )

    def async_clear_issues(self) -> None:
        """Remove this entry's repair issues (called on unload)."""
        for key in (
            ISSUE_STATISTICS_NOT_COLLECTING,
            ISSUE_TAILSCALE_REAUTH,
            ISSUE_ROUTER_MODE,
        ):
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(key))

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.unique_id or self.factory_mac)},
            connections={
                (CONNECTION_NETWORK_MAC, format_mac(self.factory_mac)),
                (CONNECTION_NETWORK_MAC, adjust_mac(self.factory_mac, 1)),
            },
            name=self.device_name,
            model=self.model or "GL.iNet Router",
            manufacturer="GL.iNet",
            configuration_url=self._host,
            sw_version=self._sw_v,
        )

    @property
    def host(self) -> str:
        """Return router host."""
        return self._host

    @property
    def api(self) -> GLinet:
        """Return router API."""
        return self._api

    @property
    def factory_mac(self) -> str:
        """Return router factory_mac."""
        return self._factory_mac

    @property
    def model(self) -> str:
        """Return router model."""
        return self._model.upper()

    @property
    def device_name(self) -> str:
        """Return the router's display name (used for the device registry)."""
        return f"GL.iNet {self._model.upper()}"


class GLinetSubCoordinator(DataUpdateCoordinator[GLinetData]):
    """A coordinator that polls one bucket of endpoints on its own interval.

    Shares the hub's API client, auth recovery and working state, so a snapshot
    it returns is the same ``GLinetData`` every other coordinator produces.
    Entities attach to whichever coordinator drives the data they read.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hub: GLinetUpdateCoordinator,
        *,
        name: str,
        update_interval: timedelta,
        update: Callable[[GLinetUpdateCoordinator], Coroutine[Any, Any, None]],
    ) -> None:
        """Initialize a sibling coordinator bound to ``hub``."""
        super().__init__(
            hub.hass,
            _LOGGER,
            name=name,
            update_interval=update_interval,
            config_entry=hub.config_entry,
        )
        self._hub = hub
        self._update = update

    async def _async_update_data(self) -> GLinetData:
        """Poll this bucket's endpoints and return the shared snapshot."""
        # Serialised against the hub and the other siblings: they all mutate the
        # hub's working state and per-cycle flags, so overlapping refreshes could
        # otherwise clear each other's failure flag or interleave writes.
        async with self._hub.refresh_lock:
            if not self._hub.last_update_success:
                # Only the hub polls a mandatory endpoint, so it is the sole
                # authority on reachability. Without this a bucket built purely
                # from optional endpoints stays "successful" against an offline
                # router, leaving its entities available with stale values.
                raise UpdateFailed(f"GL.iNet router {self._hub.host} is unreachable")
            self._hub.reset_cycle()
            await self._update(self._hub)
            self._hub.raise_if_cycle_failed()
            if self._hub.optional_transport_failed:
                # This bucket is all optional endpoints, which swallow transport
                # and auth errors to preserve last-good values. With no mandatory
                # call to prove reachability, treat that as a failed refresh
                # rather than reporting success on stale data.
                raise UpdateFailed(
                    f"GL.iNet router {self._hub.host} did not answer {self.name}"
                )
        # Three of the four repair issues are driven by slow-bucket data
        # (flow stats, acceleration, tailscale). Reconciling after every bucket
        # keeps them from lagging a full hub poll behind the state that caused
        # them; the check is pure bookkeeping over current shared state, so
        # running it more often is free and never wrong.
        self._hub.async_manage_repair_issues()
        return self._hub.snapshot()

    # Identity and the API client live on the hub. Proxying them keeps every
    # entity able to take any coordinator without caring which bucket it is in.

    @property
    def device_info(self) -> DeviceInfo:
        """Return the router device entry."""
        return self._hub.device_info

    @property
    def api(self) -> GLinet:
        """Return router API."""
        return self._hub.api

    @property
    def factory_mac(self) -> str:
        """Return router factory_mac."""
        return self._hub.factory_mac

    @property
    def model(self) -> str:
        """Return router model."""
        return self._hub.model

    @property
    def device_name(self) -> str:
        """Return the router's display name (used for the device registry)."""
        return self._hub.device_name


@dataclass
class GLinetRuntimeData:
    """The four coordinators backing a config entry, bucketed by change rate."""

    main: GLinetUpdateCoordinator
    fast: GLinetSubCoordinator
    trackers: GLinetSubCoordinator
    slow: GLinetSubCoordinator

    def all(self) -> tuple[DataUpdateCoordinator[GLinetData], ...]:
        """Return every coordinator, hub first."""
        return (self.main, self.fast, self.trackers, self.slow)


# Entities take whichever coordinator drives their data. The two classes are
# siblings rather than parent/child - GLinetSubCoordinator proxies the hub's
# identity and API client - so this alias is what entity code should name.
type GLinetCoordinator = GLinetUpdateCoordinator | GLinetSubCoordinator

type GlinetConfigEntry = ConfigEntry[GLinetRuntimeData]
