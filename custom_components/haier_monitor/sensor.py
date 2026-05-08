"""Sensor entities for Haier Multi-Split Monitor.

Config-driven definitions: each sensor described as a SensorDef instance,
single generic class HaierMonitorSensor reads coordinator.data[key] via .calc().
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_CURRENCY,
    DOMAIN,
)
from .coordinator import HaierMonitorCoordinator
from .entity import HaierMonitorEntity


@dataclass(frozen=True)
class HaierSensorDef:
    """Definition of one sensor."""

    key: str  # data dict key
    translation_key: str  # from translations file
    icon: Optional[str] = None
    unit: Optional[str] = None
    device_class: Optional[SensorDeviceClass] = None
    state_class: Optional[SensorStateClass] = None
    entity_category: Optional[str] = None
    options: Optional[list[str]] = None  # for enum sensors
    decimals: Optional[int] = None
    extra_attrs_fn: Optional[Callable[[dict], dict]] = None
    enabled_by_default: bool = True


def _format(value: Any, decimals: Optional[int]) -> Any:
    """Round float values to N decimals."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and decimals is not None:
        return round(value, decimals)
    return value


# ---------------------------------------------------------------------------
# Static sensor definitions (~50 sensors)
# ---------------------------------------------------------------------------
SENSOR_DEFS: list[HaierSensorDef] = [
    # Layer 0: raw inputs (technical, disabled by default to avoid clutter)
    HaierSensorDef("outdoor_temperature", "outdoor_temperature", "mdi:thermometer", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),
    HaierSensorDef("outdoor_coil_temperature", "outdoor_coil_temperature", "mdi:thermometer-lines", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),
    HaierSensorDef("outdoor_defrost_temperature", "outdoor_defrost_temperature", "mdi:snowflake-thermometer", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),
    HaierSensorDef("outdoor_in_air_temperature", "outdoor_in_air_temperature", "mdi:thermometer", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),
    HaierSensorDef("outdoor_out_air_temperature", "outdoor_out_air_temperature", "mdi:thermometer", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),
    HaierSensorDef("outdoor_air_dt", "outdoor_air_dt", "mdi:thermometer-lines", UnitOfTemperature.CELSIUS, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),
    HaierSensorDef("compressor_frequency", "compressor_frequency", "mdi:sine-wave", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, decimals=1),
    HaierSensorDef("compressor_current", "compressor_current", "mdi:current-ac", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),
    HaierSensorDef("compressor_uptime_min", "compressor_uptime", "mdi:timer-outline", UnitOfTime.MINUTES, None, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),
    HaierSensorDef("compressor_starts_per_hour", "compressor_starts_per_hour", "mdi:restart", None, None, SensorStateClass.MEASUREMENT, enabled_by_default=False),

    # Layer 2: lookup
    HaierSensorDef("comp_f_max", "comp_f_max", "mdi:speedometer", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("comp_f_min", "comp_f_min", "mdi:speedometer-slow", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("outdoor_fan_rpm", "outdoor_fan_rpm", "mdi:fan", "rpm", None, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("outdoor_airflow", "outdoor_airflow", "mdi:weather-windy", UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR, None, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("p_elec_max", "p_elec_max", "mdi:flash-outline", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("q_max", "q_max", "mdi:home-thermometer-outline", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("eer_table", "eer_table", "mdi:gauge-empty", None, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),

    # Layer 3: physics — main numeric outputs
    HaierSensorDef("p_idle", "p_idle", "mdi:flash-outline", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("p_elec_modeled", "p_elec_modeled", "mdi:flash", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef(
        "p_elec", "p_elec", "mdi:flash", UnitOfPower.WATT,
        SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0,
        extra_attrs_fn=lambda d: {"source": d.get("p_elec_source")},
    ),
    HaierSensorDef("q_outdoor_air", "q_outdoor_air", "mdi:weather-windy", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("q_indoor_total", "q_indoor_total", "mdi:home-thermometer", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0),
    HaierSensorDef("q_sensible_total", "q_sensible_total", "mdi:water-circle", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("q_latent_total", "q_latent_total", "mdi:water-percent", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("shr", "shr", "mdi:water-circle", None, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),

    # Approach temperatures (for FDD)
    HaierSensorDef("approach_outdoor", "approach_outdoor", "mdi:thermometer-chevron-up", UnitOfTemperature.CELSIUS, None, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),

    # Layer 5: KPIs
    HaierSensorDef("eer_instant", "eer_instant", "mdi:speedometer", None, None, SensorStateClass.MEASUREMENT, decimals=2),
    HaierSensorDef("cop_instant", "cop_instant", "mdi:speedometer", None, None, SensorStateClass.MEASUREMENT, decimals=2),
    HaierSensorDef("eer_smoothed", "eer_smoothed", "mdi:chart-line", None, None, SensorStateClass.MEASUREMENT, decimals=2),
    HaierSensorDef("cop_smoothed", "cop_smoothed", "mdi:chart-line", None, None, SensorStateClass.MEASUREMENT, decimals=2),
    HaierSensorDef("eer_expected", "eer_expected", "mdi:gauge-empty", None, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),
    HaierSensorDef("cop_expected", "cop_expected", "mdi:gauge-empty", None, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),
    HaierSensorDef("cop_carnot", "cop_carnot", "mdi:atom", None, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),
    HaierSensorDef("eer_efficiency", "eer_efficiency", "mdi:percent", None, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),
    HaierSensorDef("cop_efficiency", "cop_efficiency", "mdi:percent", None, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),
    HaierSensorDef("eer_efficiency_smoothed", "eer_efficiency_smoothed", "mdi:percent", None, None, SensorStateClass.MEASUREMENT, decimals=2),
    HaierSensorDef("cop_efficiency_smoothed", "cop_efficiency_smoothed", "mdi:percent", None, None, SensorStateClass.MEASUREMENT, decimals=2),
    HaierSensorDef("q_sanity_ratio", "q_sanity_ratio", "mdi:check-decagram-outline", None, None, SensorStateClass.MEASUREMENT, decimals=2, enabled_by_default=False),
    HaierSensorDef("q_sanity_smoothed", "q_sanity_smoothed", "mdi:check-decagram", None, None, SensorStateClass.MEASUREMENT, decimals=2),

    # Layer 6: energy totals
    HaierSensorDef("e_elec_total", "e_elec_total", "mdi:lightning-bolt", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3),
    HaierSensorDef("e_elec_cool_total", "e_elec_cool_total", "mdi:lightning-bolt", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("e_elec_heat_total", "e_elec_heat_total", "mdi:lightning-bolt", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("q_cool_total", "q_cool_total", "mdi:snowflake", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("q_heat_total", "q_heat_total", "mdi:fire", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),

    # Period totals
    HaierSensorDef("e_elec_daily", "e_elec_daily", "mdi:lightning-bolt", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3),
    HaierSensorDef("e_elec_monthly", "e_elec_monthly", "mdi:lightning-bolt", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3),
    HaierSensorDef("e_elec_yearly", "e_elec_yearly", "mdi:lightning-bolt", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3),
    HaierSensorDef("e_elec_cool_monthly", "e_elec_cool_monthly", "mdi:snowflake", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("e_elec_heat_monthly", "e_elec_heat_monthly", "mdi:fire", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("q_cool_daily", "q_cool_daily", "mdi:snowflake", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("q_cool_monthly", "q_cool_monthly", "mdi:snowflake", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("q_heat_daily", "q_heat_daily", "mdi:fire", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("q_heat_monthly", "q_heat_monthly", "mdi:fire", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),

    # SEER/SCOP
    HaierSensorDef("seer_running", "seer_running", "mdi:chart-line", None, None, SensorStateClass.MEASUREMENT, decimals=2),
    HaierSensorDef("scop_running", "scop_running", "mdi:chart-line", None, None, SensorStateClass.MEASUREMENT, decimals=2),
    HaierSensorDef("seer_pct", "seer_pct", "mdi:percent-outline", PERCENTAGE, None, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierSensorDef("scop_pct", "scop_pct", "mdi:percent-outline", PERCENTAGE, None, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),

    # Cost
    HaierSensorDef("cost_daily", "cost_daily", "mdi:cash", DEFAULT_CURRENCY, SensorDeviceClass.MONETARY, SensorStateClass.TOTAL, decimals=2),
    HaierSensorDef("cost_monthly", "cost_monthly", "mdi:cash", DEFAULT_CURRENCY, SensorDeviceClass.MONETARY, SensorStateClass.TOTAL, decimals=2),

    # Tariff buckets (for transparency / energy dashboard verification)
    HaierSensorDef("e_elec_day_daily", "e_elec_day_daily", "mdi:weather-sunny", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),
    HaierSensorDef("e_elec_night_daily", "e_elec_night_daily", "mdi:weather-night", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, decimals=3, enabled_by_default=False),

    # Layer 7: status enums
    HaierSensorDef(
        "what_doing", "what_doing", None, None, SensorDeviceClass.ENUM, None,
        options=[
            "off", "starting", "defrosting", "fan_only", "auto", "idle",
            "cooling", "cooling_all",
            "heating", "heating_all",
            "drying", "drying_all",
        ],
        extra_attrs_fn=lambda d: d.get("what_doing_attrs", {}),
    ),
    HaierSensorDef(
        "health", "health", None, None, SensorDeviceClass.ENUM, None,
        options=["excellent", "good", "average", "problem", "starting", "defrosting", "idle", "unknown"],
        extra_attrs_fn=lambda d: {
            "sanity_ratio": d.get("q_sanity_smoothed"),
            "efficiency_ratio": (
                d.get("eer_efficiency_smoothed")
                if d.get("mode") in ("cool", "dry")
                else d.get("cop_efficiency_smoothed")
            ),
        },
    ),
    HaierSensorDef(
        "efficiency_label", "efficiency_label", None, None, SensorDeviceClass.ENUM, None,
        options=["excellent", "good", "average", "low", "starting", "defrosting", "idle", "unknown"],
    ),
    HaierSensorDef(
        "sanity_label", "sanity_label", None, None, SensorDeviceClass.ENUM, None,
        options=["normal", "slightly_low", "significantly_low", "slightly_high", "significantly_high", "unknown"],
    ),
    HaierSensorDef(
        "seer_grade", "seer_grade", "mdi:label", None, SensorDeviceClass.ENUM, None,
        options=["A+++", "A++", "A+", "A", "B", "C_or_lower", "unknown"],
    ),
    HaierSensorDef(
        "scop_grade", "scop_grade", "mdi:label", None, SensorDeviceClass.ENUM, None,
        options=["A+++", "A++", "A+", "A", "B", "C_or_lower", "unknown"],
    ),

    # Layer 8: diagnostics — components
    HaierSensorDef(
        "outdoor_coil_status", "outdoor_coil_status", None, None, SensorDeviceClass.ENUM, None,
        options=["clean", "possibly_dirty", "needs_cleaning", "unknown"],
    ),
    HaierSensorDef(
        "refrigerant_status", "refrigerant_status", None, None, SensorDeviceClass.ENUM, None,
        options=["normal", "leak_suspected", "unknown"],
    ),
    HaierSensorDef(
        "defrost_status_label", "defrost_status_label", "mdi:snowflake-melt", None, SensorDeviceClass.ENUM, None,
        options=["normal", "frequent", "long", "unknown"],
        extra_attrs_fn=lambda d: {
            "count_24h": d.get("defrost_count_24h"),
            "avg_minutes": d.get("defrost_avg_minutes"),
        },
    ),
    HaierSensorDef("defrost_count_24h", "defrost_count_24h", "mdi:snowflake-melt", None, None, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),

    # Maintenance days
    HaierSensorDef("outdoor_days", "outdoor_days", "mdi:calendar-clock", "d", None, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),

    # Layer 9: recommendation
    HaierSensorDef(
        "severity", "recommendation_severity", None, None, SensorDeviceClass.ENUM, None,
        options=["ok", "info", "warn", "fault"],
        extra_attrs_fn=lambda d: {
            "issues": d.get("issues", []),
            "fault_count": sum(1 for i in d.get("issues", []) if i.get("severity") == "fault"),
            "warn_count": sum(1 for i in d.get("issues", []) if i.get("severity") == "warn"),
            "info_count": sum(1 for i in d.get("issues", []) if i.get("severity") == "info"),
        },
    ),
    HaierSensorDef(
        "top_message", "recommendation_top", "mdi:lightbulb-on-outline", None, None, None,
        extra_attrs_fn=lambda d: {
            "severity": d.get("severity"),
            "issues_count": len(d.get("issues", [])),
        },
    ),
]


# ---------------------------------------------------------------------------
# Per-room sensor definitions (instantiated for each indoor unit)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HaierRoomSensorDef:
    """Definition of a per-room sensor."""

    field_name: str  # field within rooms[name] dict
    translation_key: str
    icon: Optional[str] = None
    unit: Optional[str] = None
    device_class: Optional[SensorDeviceClass] = None
    state_class: Optional[SensorStateClass] = None
    options: Optional[list[str]] = None
    decimals: Optional[int] = None
    enabled_by_default: bool = True


ROOM_SENSOR_DEFS: list[HaierRoomSensorDef] = [
    HaierRoomSensorDef("q_room", "q_room", "mdi:home", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0),
    HaierRoomSensorDef("q_sensible", "q_sensible_room", "mdi:water-circle", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, decimals=0, enabled_by_default=False),
    HaierRoomSensorDef("share", "share_room", "mdi:chart-pie", None, None, SensorStateClass.MEASUREMENT, decimals=3, enabled_by_default=False),
    HaierRoomSensorDef("dewpoint", "dewpoint_room", "mdi:water-thermometer", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),
    HaierRoomSensorDef("approach_evap_smoothed", "approach_evap_room", "mdi:thermometer-chevron-down", UnitOfTemperature.CELSIUS, None, SensorStateClass.MEASUREMENT, decimals=1, enabled_by_default=False),
    HaierRoomSensorDef(
        "filter_status", "filter_status_room", None, None, SensorDeviceClass.ENUM, None,
        options=["clean", "possibly_dirty", "needs_cleaning", "unknown"],
    ),
]


# ---------------------------------------------------------------------------
# Generic sensor classes
# ---------------------------------------------------------------------------
class HaierMonitorSensor(HaierMonitorEntity, SensorEntity):
    """Generic sensor reading from coordinator.data[key]."""

    def __init__(
        self,
        coordinator: HaierMonitorCoordinator,
        sensor_def: HaierSensorDef,
    ) -> None:
        super().__init__(coordinator, sensor_def.key, sensor_def.translation_key)
        self._def = sensor_def
        self._attr_native_unit_of_measurement = sensor_def.unit
        self._attr_device_class = sensor_def.device_class
        self._attr_state_class = sensor_def.state_class
        self._attr_icon = sensor_def.icon
        if sensor_def.options:
            self._attr_options = sensor_def.options
        if not sensor_def.enabled_by_default:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return _format(self.coordinator.data.get(self._def.key), self._def.decimals)

    @property
    def extra_state_attributes(self) -> Optional[dict]:
        if self._def.extra_attrs_fn and self.coordinator.data:
            return self._def.extra_attrs_fn(self.coordinator.data)
        return None


class HaierMonitorRoomSensor(HaierMonitorEntity, SensorEntity):
    """Sensor for one indoor unit (room)."""

    def __init__(
        self,
        coordinator: HaierMonitorCoordinator,
        room_name: str,
        sensor_def: HaierRoomSensorDef,
    ) -> None:
        super().__init__(
            coordinator,
            f"room_{room_name}_{sensor_def.field_name}",
            sensor_def.translation_key,
        )
        self._room_name = room_name
        self._def = sensor_def
        self._attr_translation_placeholders = {"room": room_name}
        self._attr_native_unit_of_measurement = sensor_def.unit
        self._attr_device_class = sensor_def.device_class
        self._attr_state_class = sensor_def.state_class
        self._attr_icon = sensor_def.icon
        if sensor_def.options:
            self._attr_options = sensor_def.options
        if not sensor_def.enabled_by_default:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        rooms = self.coordinator.data.get("rooms", {})
        room = rooms.get(self._room_name)
        if not room:
            return None
        return _format(room.get(self._def.field_name), self._def.decimals)


class HaierFilterDaysSensor(HaierMonitorEntity, SensorEntity):
    """Sensor showing days since last filter clean."""

    _attr_icon = "mdi:calendar-clock"
    _attr_native_unit_of_measurement = "d"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: HaierMonitorCoordinator, room_name: str
    ) -> None:
        super().__init__(coordinator, f"filter_days_{room_name}", "filter_days_room")
        self._room_name = room_name
        self._attr_translation_placeholders = {"room": room_name}

    @property
    def native_value(self) -> Optional[int]:
        if self.coordinator.data is None:
            return None
        days = self.coordinator.data.get("filter_days", {}).get(self._room_name, -1)
        return days if days >= 0 else None


# ---------------------------------------------------------------------------
# Setup entry
# ---------------------------------------------------------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator: HaierMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    # Static sensors
    for sd in SENSOR_DEFS:
        entities.append(HaierMonitorSensor(coordinator, sd))

    # Per-room sensors
    indoor_units = entry.data.get("indoor_units", [])
    for iu in indoor_units:
        room_name = iu["name"]
        for rsd in ROOM_SENSOR_DEFS:
            entities.append(HaierMonitorRoomSensor(coordinator, room_name, rsd))
        entities.append(HaierFilterDaysSensor(coordinator, room_name))

    async_add_entities(entities)
