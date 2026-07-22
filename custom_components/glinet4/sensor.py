"""Sensors for GL.iNet component."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from math import floor, log10
from typing import TYPE_CHECKING, Any

from glinet4.enums import TailscaleConnection
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfTemperature,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import GlinetConfigEntry, GLinetCoordinator, GLinetData

_LOGGER = logging.getLogger(__name__)

# Updates flow through the DataUpdateCoordinator, so the per-entity update
# throttle is unnecessary (0 = no limit).
PARALLEL_UPDATES = 0

# Minimum movement in the derived boot time before a new timestamp is committed
# to state. Mirrors Home Assistant's UniFi integration, which uses the same
# tolerance to stop derived uptime timestamps flapping on every poll.
UPTIME_DEVIATION = timedelta(seconds=120)


class SystemStatusEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Describes a GL.iNet system status sensor entity."""

    value_fn: Callable[[dict], int | float | None]
    extra_attributes_fn: Callable[[dict], dict[str, Any]] | None = None


SYSTEM_SENSORS: list[SystemStatusEntityDescription] = [
    SystemStatusEntityDescription(
        key="cpu_temp",
        translation_key="cpu_temp",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda system_status: (
            (cpu := system_status.get("cpu")) and cpu.get("temperature")
        ),
    ),
    SystemStatusEntityDescription(
        key="load_avg1",
        translation_key="load_avg1",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: (
            la[0]
            if isinstance(la := system_status.get("load_average"), list) and len(la) > 0
            else None
        ),
    ),
    SystemStatusEntityDescription(
        key="load_avg5",
        translation_key="load_avg5",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: (
            la[1]
            if isinstance(la := system_status.get("load_average"), list) and len(la) > 1
            else None
        ),
    ),
    SystemStatusEntityDescription(
        key="load_avg15",
        translation_key="load_avg15",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda system_status: (
            la[2]
            if isinstance(la := system_status.get("load_average"), list) and len(la) > 2
            else None
        ),
    ),
    SystemStatusEntityDescription(
        key="memory_use",
        translation_key="memory_use",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        native_unit_of_measurement=PERCENTAGE,
        # Rounded natively, not just for display: the raw quotient is a full
        # float (38.1658171423608) and the recorder keys its dedup on the state
        # *string*, so unrounded it wrote a row on every single poll.
        #
        # 2dp (0.01pp, ~101 KiB of this router's 989 MiB) is finer than the
        # measurement noise - profiled over 24h the poll-to-poll deltas have a
        # lag-1 autocorrelation of -0.51, i.e. essentially pure noise, sd
        # 0.27pp - so most transitions it keeps are jitter rather than memory
        # actually moving. It is kept anyway because the absolute cost is
        # trivial (~1.4k rows/day, ~14k against the default 10-day purge) and
        # it matches the precision the sensor has always displayed. Dropping
        # the round() below to 1dp would roughly halve the rows if that ever
        # matters (keep suggested_display_precision in step with it).
        value_fn=lambda system_status: (
            (
                (memory_total := system_status.get("memory_total", 0)) > 0
                and (
                    memory_free := system_status.get("memory_free", 0)
                    + system_status.get("memory_buff_cache", 0)
                )
                >= 0
                and (mu := 100 * (1 - memory_free / memory_total))
                and isinstance(mu, float)
                and 0 <= mu <= 100
                and round(mu, 2)
            )
            or None
        ),
        extra_attributes_fn=lambda system_status: {
            "memory_total": system_status.get("memory_total"),
            "memory_free": system_status.get("memory_free"),
            "memory_buff_cache": system_status.get("memory_buff_cache"),
            "memory_available": system_status.get("memory_free", 0)
            + system_status.get("memory_buff_cache", 0),
            "memory_used": system_status.get("memory_total", 0)
            - system_status.get("memory_free", 0)
            - system_status.get("memory_buff_cache", 0),
        },
    ),
    SystemStatusEntityDescription(
        key="flash_use",
        translation_key="flash_use",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda system_status: (
            (
                (flash_total := system_status.get("flash_total", 0)) > 0
                and (flash_free := system_status.get("flash_free", 0)) >= 0
                and (fu := 100 * (1 - flash_free / flash_total))
                and isinstance(fu, float)
                and 0 <= fu <= 100
                and fu
            )
            or None
        ),
        extra_attributes_fn=lambda system_status: {
            "flash_total": system_status.get("flash_total"),
            "flash_free": system_status.get("flash_free"),
        },
    ),
]


class GLinetDataEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Describes a sensor deriving its value from the whole GLinetData snapshot."""

    value_fn: Callable[[GLinetData], str | int | float | None]
    extra_attributes_fn: Callable[[GLinetData], dict[str, Any] | None] | None = None


WAN_SENSORS: list[GLinetDataEntityDescription] = [
    GLinetDataEntityDescription(
        key="wan_ip",
        translation_key="wan_ip",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            ip.split("/")[0]
            if (ip := (data.wan_status.get("ipv4") or {}).get("ip"))
            else None
        ),
        extra_attributes_fn=lambda data: {
            "gateway": (data.wan_status.get("ipv4") or {}).get("gateway"),
            "dns": (data.wan_status.get("ipv4") or {}).get("dns"),
            "protocol": data.wan_status.get("protocol"),
        },
    ),
]


def _round_sig(value: int | None, digits: int = 3) -> int | None:
    """Round a byte rate to ``digits`` significant figures.

    Home Assistant's recorder only writes a row when the *state string* changes,
    so an unrounded rate writes a row on every single poll - measured at 636
    changes per 635 polls on a live router. Rounding the native value lets that
    dedup work during steady traffic while staying well inside the router's own
    accuracy (it reports an average over a ~3s window). Display is unaffected:
    25158 -> 25200 B/s still renders as 0.20 Mbit/s.
    """
    if not value:
        return value
    magnitude = floor(log10(abs(value)))
    quantum = 10 ** max(0, magnitude - digits + 1)
    return int(round(value / quantum) * quantum)


# Split out of WAN_SENSORS: these are the only entities whose value changes on
# every poll, so they are driven by the fast coordinator and shipped disabled.
#
# Disabled by default because they are the integration's one genuinely noisy
# entity pair, and at a 10s poll they would write ~8,600 recorder rows per day
# each. HA's Gold `entity-disabled-by-default` rule targets exactly this case,
# and core precedent is unambiguous - unifi keeps its bandwidth sensors behind
# an opt-in that defaults to off. Users who want WAN throughput enable them
# once; users who don't pay nothing for them.
WAN_THROUGHPUT_SENSORS: list[GLinetDataEntityDescription] = [
    GLinetDataEntityDescription(
        key="wan_download_speed",
        translation_key="wan_download_speed",
        has_entity_name=True,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _round_sig(data.wan_speed.get("speed_rx")),
    ),
    GLinetDataEntityDescription(
        key="wan_upload_speed",
        translation_key="wan_upload_speed",
        has_entity_name=True,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _round_sig(data.wan_speed.get("speed_tx")),
    ),
]

TAILSCALE_SENSORS: list[GLinetDataEntityDescription] = [
    GLinetDataEntityDescription(
        key="tailscale_status",
        translation_key="tailscale_status",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[state.name.lower() for state in TailscaleConnection],
        value_fn=lambda data: data.tailscale_state,
        extra_attributes_fn=lambda data: (
            {"auth_url": data.tailscale_auth_url} if data.tailscale_auth_url else None
        ),
    ),
]

# Count sensors over the firewall read surface. The backing lists are None until
# the router answers (see coordinator), so an empty list reads as a real 0 while
# an unsupported endpoint leaves the sensor uncreated.
FIREWALL_SENSORS: list[GLinetDataEntityDescription] = [
    GLinetDataEntityDescription(
        key="firewall_port_forwards",
        translation_key="firewall_port_forwards",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            None
            if data.firewall_port_forwards is None
            else len(data.firewall_port_forwards)
        ),
        extra_attributes_fn=lambda data: {"rules": data.firewall_port_forwards},
    ),
    GLinetDataEntityDescription(
        key="firewall_rules",
        translation_key="firewall_rules",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            None if data.firewall_rules is None else len(data.firewall_rules)
        ),
    ),
]


# VPN-server diagnostics. Both ride the slow bucket. WireGuard's connected
# count is derived in the coordinator (it needs the clock); OpenVPN is a plain
# count of configured server users.
VPN_SERVER_SENSORS: list[GLinetDataEntityDescription] = [
    GLinetDataEntityDescription(
        key="wireguard_server_peers",
        translation_key="wireguard_server_peers",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            None
            if data.wireguard_server is None
            else data.wireguard_server["connected"]
        ),
        extra_attributes_fn=lambda data: (
            None
            if data.wireguard_server is None
            else {
                "total_peers": data.wireguard_server["total"],
                "peers": data.wireguard_server["peers"],
            }
        ),
    ),
    GLinetDataEntityDescription(
        key="openvpn_server_users",
        translation_key="openvpn_server_users",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            None
            if data.openvpn_server_users is None
            else len(data.openvpn_server_users)
        ),
    ),
]


# Hardware/client diagnostics, all on the slow bucket.
DIAGNOSTICS_SENSORS: list[GLinetDataEntityDescription] = [
    GLinetDataEntityDescription(
        key="wired_clients",
        translation_key="wired_clients",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        # `... is None` gates on the endpoint being answered at all; a missing
        # count key on an answered payload is a real 0, not an absent sensor.
        value_fn=lambda data: (
            None
            if data.clients_status is None
            else data.clients_status.get("cable_total", 0)
        ),
    ),
    GLinetDataEntityDescription(
        key="wireless_clients",
        translation_key="wireless_clients",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            None
            if data.clients_status is None
            else data.clients_status.get("wireless_total", 0)
        ),
    ),
    GLinetDataEntityDescription(
        key="ethernet_ports",
        translation_key="ethernet_ports",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        # Count ports carrying a link (non-zero negotiated speed).
        value_fn=lambda data: (
            None
            if data.ethernet_ports is None
            else sum(1 for port in data.ethernet_ports if port.get("speed"))
        ),
        extra_attributes_fn=lambda data: (
            None if data.ethernet_ports is None else {"ports": data.ethernet_ports}
        ),
    ),
    GLinetDataEntityDescription(
        key="usb_devices",
        translation_key="usb_devices",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            None if data.usb_devices is None else len(data.usb_devices)
        ),
        extra_attributes_fn=lambda data: (
            None if data.usb_devices is None else {"devices": data.usb_devices}
        ),
    ),
    # The DPI per-app breakdown the flow-statistics switch collects: state is the
    # number of tracked apps, with the top ones (by traffic) in the attributes.
    GLinetDataEntityDescription(
        key="flow_top_apps",
        translation_key="flow_top_apps",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            None if data.flow_stats_top_apps is None else len(data.flow_stats_top_apps)
        ),
        # State counts every tracked app; the attribute is capped to the busiest
        # 10 (already sorted by the coordinator) to keep the payload bounded.
        extra_attributes_fn=lambda data: (
            None
            if data.flow_stats_top_apps is None
            else {"apps": data.flow_stats_top_apps[:10]}
        ),
    ),
    GLinetDataEntityDescription(
        key="multiwan",
        translation_key="multiwan",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            None
            if data.multiwan_status is None
            else len(data.multiwan_status.get("interfaces", []))
        ),
        extra_attributes_fn=lambda data: (
            None
            if data.multiwan_status is None
            else {"interfaces": data.multiwan_status.get("interfaces", [])}
        ),
    ),
    GLinetDataEntityDescription(
        key="repeater",
        translation_key="repeater",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        # The WiFi-as-WAN connection state (e.g. connected / not_used / failed).
        value_fn=lambda data: (
            None
            if data.repeater_status is None
            else data.repeater_status.get("state_s")
        ),
    ),
    GLinetDataEntityDescription(
        key="wifi_radios",
        translation_key="wifi_radios",
        has_entity_name=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        # Count of radios, with each radio's band/channel/state in attributes.
        value_fn=lambda data: (
            None if data.wifi_radios is None else len(data.wifi_radios)
        ),
        extra_attributes_fn=lambda data: (
            None if data.wifi_radios is None else {"radios": data.wifi_radios}
        ),
    ),
]


async def async_setup_entry(
    _: HomeAssistant, entry: GlinetConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors."""
    _LOGGER.debug("Setting up GL.iNet Sensors")

    # Sensors span three buckets. WAN throughput is the only data that changes
    # on every poll, so it gets the fast coordinator; Tailscale status changes
    # about once a day and rides the slow one.
    coordinator = entry.runtime_data.main
    sensors: list[SystemStatusSensor | SystemUptimeSensor | GLinetDataSensor] = [
        SystemStatusSensor(coordinator=coordinator, entity_description=description)
        for description in SYSTEM_SENSORS
    ]
    sensors.extend(
        GLinetDataSensor(
            coordinator=entry.runtime_data.fast, entity_description=description
        )
        for description in WAN_THROUGHPUT_SENSORS
    )
    sensors.extend(
        GLinetDataSensor(coordinator=coordinator, entity_description=description)
        for description in WAN_SENSORS
    )
    sensors.extend(
        GLinetDataSensor(
            coordinator=entry.runtime_data.slow, entity_description=description
        )
        for description in TAILSCALE_SENSORS
    )
    sensors.extend(
        GLinetDataSensor(
            coordinator=entry.runtime_data.slow, entity_description=description
        )
        for description in FIREWALL_SENSORS
    )
    sensors.extend(
        GLinetDataSensor(
            coordinator=entry.runtime_data.slow, entity_description=description
        )
        for description in VPN_SERVER_SENSORS
    )
    sensors.extend(
        GLinetDataSensor(
            coordinator=entry.runtime_data.slow, entity_description=description
        )
        for description in DIAGNOSTICS_SENSORS
    )
    # Special case for uptime as it requires additional data processing
    sensors.append(
        SystemUptimeSensor(
            coordinator=coordinator,
            entity_description=SystemStatusEntityDescription(
                key="uptime",
                translation_key="uptime",
                has_entity_name=True,
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
                value_fn=lambda a: None,
            ),
        )
    )

    # Only add sensors whose value is available on this device/model. Build a
    # new list rather than mutating `sensors` while iterating it, which would
    # skip elements and leave unavailable sensors in place.
    available = [sensor for sensor in sensors if sensor.native_value is not None]

    async_add_entities(available)


def _derive_boot_time(seconds_uptime: float) -> datetime:
    """Derive the boot timestamp from the router's uptime counter."""
    # dt_util.utcnow() is untyped (Any) under the stubs; pin it to datetime so
    # the subtraction below is typed rather than returning Any.
    now: datetime = dt_util.utcnow()
    return now - timedelta(seconds=seconds_uptime)


def _boot_time_changed(old: datetime | None, new: datetime) -> bool:
    """Return whether the boot time moved enough to warrant a state write.

    Mirrors UniFi's ``async_uptime_value_changed_fn``: sub-tolerance fluctuation
    from second-granularity uptime and poll jitter is ignored so the timestamp
    stays stable between reboots.
    """
    return old is None or abs(new - old) > UPTIME_DEVIATION


class GliSensorBase(CoordinatorEntity["GLinetCoordinator"], SensorEntity):
    """GL.iNet sensor base class."""

    entity_description: SystemStatusEntityDescription

    def __init__(
        self,
        coordinator: GLinetCoordinator,
        entity_description: SystemStatusEntityDescription,
    ) -> None:
        """Initialize the sensor class."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"glinet4_sensor/{coordinator.factory_mac}/system_{entity_description.key}"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.entity_description.extra_attributes_fn is None:
            return None
        return self.entity_description.extra_attributes_fn(
            self.coordinator.data.system_status
        )


class SystemStatusSensor(GliSensorBase):
    """GL.iNet system status sensor class."""

    @property
    def native_value(self) -> int | float | None:
        """Return the native value of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data.system_status)


class GLinetDataSensor(CoordinatorEntity["GLinetCoordinator"], SensorEntity):
    """GL.iNet sensor whose value derives from the full coordinator snapshot."""

    entity_description: GLinetDataEntityDescription

    def __init__(
        self,
        coordinator: GLinetCoordinator,
        entity_description: GLinetDataEntityDescription,
    ) -> None:
        """Initialize the sensor from its description."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"glinet4_sensor/{coordinator.factory_mac}/{entity_description.key}"
        )

    @property
    def native_value(self) -> str | int | float | None:
        """Return the native value of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.entity_description.extra_attributes_fn is None:
            return None
        return self.entity_description.extra_attributes_fn(self.coordinator.data)


class SystemUptimeSensor(GliSensorBase):
    """GL.iNet system uptime sensor class.

    The router exposes uptime as a seconds counter, so the boot timestamp is
    derived as ``now - uptime``. It is recomputed only when the coordinator
    reports a fresh uptime value, and the committed value is held stable within
    ``UPTIME_DEVIATION`` -- the same approach core uses for the UniFi integration.
    """

    _attr_native_value: datetime | None = None
    _last_uptime: float | None = None

    @property
    def native_value(self) -> datetime | None:
        """Return the cached boot timestamp, recomputing only on fresh data."""
        uptime = self.coordinator.data.system_status.get("uptime")
        if uptime is None:
            return self._attr_native_value
        if uptime != self._last_uptime:
            self._last_uptime = uptime
            candidate = _derive_boot_time(uptime)
            if _boot_time_changed(self._attr_native_value, candidate):
                self._attr_native_value = candidate
        return self._attr_native_value
