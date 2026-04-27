"""Sensor platform for the Afrihost integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

try:
    from homeassistant.const import UnitOfInformation
except ImportError:
    UnitOfInformation = type("UnitOfInformation", (), {"GIGABYTES": "GB"})()

from . import _selected_products
from .const import DOMAIN
from .coordinator import AfrihostCoordinator


# ---------------------------------------------------------------------------
# Sensor descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AfrihostSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], Any] | None = None


def _pct(field: str) -> Callable[[dict], Any]:
    def fn(p: dict) -> float | None:
        v = p.get(field)
        return round(float(v), 2) if v is not None else None
    return fn


def _str_field(field: str) -> Callable[[dict], Any]:
    return lambda p: p.get(field)


def _bytes_to_gb(field: str) -> Callable[[dict], Any]:
    def fn(p: dict) -> float | None:
        v = p.get(field)
        try:
            return round(int(v) / (1024 ** 3), 2)
        except (TypeError, ValueError):
            return None
    return fn


_BANDWIDTH_SENSORS: tuple[AfrihostSensorDescription, ...] = (
    AfrihostSensorDescription(
        key="percentage_used",
        name="Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pct("percentage_used"),
    ),
    AfrihostSensorDescription(
        key="percentage_left",
        name="Remaining",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pct("percentage_left"),
    ),
    AfrihostSensorDescription(
        key="bandwidth_limit",
        name="Bandwidth Limit",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_bytes_to_gb("bandwidth_limit"),
    ),
    AfrihostSensorDescription(
        key="status",
        name="Status",
        value_fn=_str_field("status"),
    ),
)

def _wallet_data_gb(p: dict) -> float | None:
    """Data remaining for AirMobile SIMs (bytes stored in _wallet)."""
    v = (p.get("_wallet") or {}).get("_data_remaining_bytes")
    try:
        return round(int(v) / (1024 ** 3), 2)
    except (TypeError, ValueError):
        return None


def _composite_bytes_to_gb(field: str) -> Callable[[dict], Any]:
    """Read a bytes field from _composite and return GB (voice SIMs only)."""
    def fn(p: dict) -> float | None:
        v = (p.get("_composite") or {}).get(field)
        try:
            return round(int(v) / (1024 ** 3), 2)
        except (TypeError, ValueError):
            return None
    return fn


def _data_remaining_gb(p: dict) -> float | None:
    """Data remaining: composite for voice SIMs, _wallet for AirMobile."""
    if p.get("_wallet_source") == "airmobile":
        return _wallet_data_gb(p)
    return _composite_bytes_to_gb("bandwidth_available")(p)


def _composite_pct(p: dict) -> float | None:
    v = (p.get("_composite") or {}).get("percentage_used")
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _wallet_value(wallet_key: str) -> Callable[[dict], Any]:
    """Return a value_fn that reads a wallet balance, handling both wallet shapes.

    Voice wallet (solution_type_id 800/810/811):
      _wallet = {"summary_airtime": {"balance": 7683, "airtime_wallet_type": {"display_amount": 0.01, ...}}}

    AirMobile wallet (solution_type_id 840):
      Response shape confirmed at runtime — falls back gracefully if key absent.
    """
    def fn(p: dict) -> float | None:
        wallet = p.get("_wallet") or {}
        entry = wallet.get(wallet_key) or {}
        balance = entry.get("balance")
        if balance is None:
            return None
        display_amount = (entry.get("airtime_wallet_type") or {}).get("display_amount", 1)
        try:
            return round(float(balance) * float(display_amount), 2)
        except (TypeError, ValueError):
            return None
    return fn


_SIM_SENSORS: tuple[AfrihostSensorDescription, ...] = (
    AfrihostSensorDescription(
        key="status",
        name="Status",
        value_fn=_str_field("status"),
    ),
    AfrihostSensorDescription(
        key="airtime_balance",
        name="Airtime Balance",
        native_unit_of_measurement="ZAR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_wallet_value("summary_airtime"),
    ),
    AfrihostSensorDescription(
        key="sms_balance",
        name="SMS Balance",
        native_unit_of_measurement="SMS",
        state_class=SensorStateClass.TOTAL,
        value_fn=_wallet_value("summary_sms"),
    ),
    AfrihostSensorDescription(
        key="data_remaining",
        name="Data Remaining",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data_remaining_gb,
    ),
    AfrihostSensorDescription(
        key="data_used",
        name="Data Used",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_composite_bytes_to_gb("bandwidth_used"),
    ),
    AfrihostSensorDescription(
        key="data_limit",
        name="Data Limit",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_composite_bytes_to_gb("bandwidth_limit"),
    ),
    AfrihostSensorDescription(
        key="data_used_pct",
        name="Data Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_composite_pct,
    ),
)

_STATUS_SENSORS: tuple[AfrihostSensorDescription, ...] = (
    AfrihostSensorDescription(
        key="status",
        name="Status",
        value_fn=_str_field("status"),
    ),
)


def _voip_airtime_balance(p: dict) -> float | None:
    """Sum all airtime balance entries for a VoIP product (already in rands)."""
    balances = p.get("_airtime") or []
    if not balances:
        return None
    try:
        return round(sum(float(b.get("balance", 0)) for b in balances), 2)
    except (TypeError, ValueError):
        return None


_VOIP_SENSORS: tuple[AfrihostSensorDescription, ...] = (
    AfrihostSensorDescription(
        key="status",
        name="Status",
        value_fn=_str_field("status"),
    ),
    AfrihostSensorDescription(
        key="airtime_balance",
        name="Airtime Balance",
        native_unit_of_measurement="ZAR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_voip_airtime_balance,
    ),
)

_DEVICE_SENSORS: tuple[AfrihostSensorDescription, ...] = (
    AfrihostSensorDescription(
        key="status",
        name="Status",
        value_fn=_str_field("friendly_status"),
    ),
)

_HOSTING_SENSORS: tuple[AfrihostSensorDescription, ...] = (
    AfrihostSensorDescription(
        key="disk_used",
        name="Disk Used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: _safe_float((p.get("_usage_stats") or {}).get("used_percent")),
    ),
    AfrihostSensorDescription(
        key="disk_available",
        name="Disk Available",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: _safe_float((p.get("_usage_stats") or {}).get("percent_available")),
    ),
)

_SENSORS_BY_TYPE: dict[str, tuple[AfrihostSensorDescription, ...]] = {
    "wireless":   _BANDWIDTH_SENSORS,
    "mobile_apn": _BANDWIDTH_SENSORS,
    "mobile_sim": _SIM_SENSORS,
    "voip":       _VOIP_SENSORS,
    "device":     _DEVICE_SENSORS,
    "hosting":    _HOSTING_SENSORS,
}


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AfrihostCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[AfrihostSensor] = []
    for product_key in _selected_products(entry):
        ptype = product_key.split(":")[0]
        for desc in _SENSORS_BY_TYPE.get(ptype, ()):
            entities.append(AfrihostSensor(coordinator, product_key, desc, entry.entry_id))
    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Sensor entity
# ---------------------------------------------------------------------------

class AfrihostSensor(CoordinatorEntity[AfrihostCoordinator], SensorEntity):
    """One measurement for one Afrihost product device."""

    _attr_has_entity_name = True
    entity_description: AfrihostSensorDescription

    def __init__(
        self,
        coordinator: AfrihostCoordinator,
        product_key: str,
        description: AfrihostSensorDescription,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._product_key = product_key
        self._attr_unique_id = f"{entry_id}_{product_key}_{description.key}"

        p = (coordinator.data or {}).get(product_key, {})
        self._attr_device_info = _build_device_info(product_key, p)

    @property
    def native_value(self) -> Any:
        p = (self.coordinator.data or {}).get(self._product_key)
        if p is None or self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(p)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> float | None:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _build_device_info(product_key: str, p: dict) -> DeviceInfo:
    ptype = product_key.split(":")[0]

    if ptype == "wireless":
        name = p.get("display_name") or p.get("name") or "LTE"
        model = "LTE/Wireless"
    elif ptype == "mobile_apn":
        name = p.get("display_name") or p.get("name") or "Mobile Data"
        model = "Mobile Data Package"
    elif ptype == "mobile_sim":
        name = p.get("friendlyname") or "SIM"
        sol = p.get("solution") or {}
        model = sol.get("display_name") or sol.get("name") or "Mobile SIM"
    elif ptype == "voip":
        name = p.get("friendlyname") or p.get("uid") or "VoIP"
        sol = p.get("solution") or {}
        model = sol.get("display_name") or sol.get("name") or "VoIP"
    elif ptype == "device":
        sub = p.get("sub_product_item") or {}
        name = p.get("description") or sub.get("name") or "Device"
        model = sub.get("name") or "Hardware Device"
    elif ptype == "hosting":
        name = p.get("name") or p.get("display_name") or "Hosting"
        model = "Web Hosting"
    else:
        name = product_key
        model = ptype

    return DeviceInfo(
        identifiers={(DOMAIN, product_key)},
        name=name,
        manufacturer="Afrihost",
        model=model,
    )
