"""Number entities for calibration parameters.

Each calibration constant becomes a UI slider/box that persists in entry.options.
On change, the coordinator picks up the new value via self._opt(...).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_BYPASS_FACTOR,
    DEFAULT_DAY_TARIFF,
    DEFAULT_EEV_IDLE_COOL,
    DEFAULT_EEV_IDLE_HEAT,
    DEFAULT_EEV_MAX,
    DEFAULT_ETA_CARNOT_COOL,
    DEFAULT_ETA_CARNOT_HEAT,
    DEFAULT_IDLE_BASE,
    DEFAULT_IDLE_CRANKCASE,
    DEFAULT_IDLE_INDOOR_FAN,
    DEFAULT_IDLE_OUTDOOR_FAN,
    DEFAULT_INDOOR_AIRFLOW_NOMINAL,
    DEFAULT_NIGHT_TARIFF,
    DEFAULT_OUTDOOR_AIR_DT_OFFSET,
    DEFAULT_PIPE_LENGTH,
    DOMAIN,
    OPT_BYPASS_FACTOR,
    OPT_DAY_TARIFF,
    OPT_EEV_IDLE_COOL,
    OPT_EEV_IDLE_HEAT,
    OPT_EEV_MAX,
    OPT_ETA_CARNOT_COOL,
    OPT_ETA_CARNOT_HEAT,
    OPT_IDLE_BASE,
    OPT_IDLE_CRANKCASE,
    OPT_IDLE_INDOOR_FAN,
    OPT_IDLE_OUTDOOR_FAN,
    OPT_INDOOR_AIRFLOW_NOMINAL,
    OPT_NIGHT_TARIFF,
    OPT_OUTDOOR_AIR_DT_OFFSET,
    OPT_PIPE_LENGTH,
)
from .coordinator import HaierMonitorCoordinator
from .entity import HaierMonitorEntity


@dataclass(frozen=True)
class HaierNumberDef:
    """Definition of a calibration number."""

    option_key: str
    translation_key: str
    default: float
    minimum: float
    maximum: float
    step: float = 1.0
    unit: Optional[str] = None
    icon: Optional[str] = None
    mode: NumberMode = NumberMode.AUTO


NUMBER_DEFS: list[HaierNumberDef] = [
    # EEV calibration — units depend on what your ESPHome publishes.
    # paveldn/haier-esphome publishes a fraction 0.0..1.0 (defaults match this).
    # Steps-mode firmware can use 0..500 with corresponding integer idle values.
    HaierNumberDef(OPT_EEV_MAX, "eev_max", DEFAULT_EEV_MAX, 0.001, 5000.0, step=0.001, icon="mdi:valve", mode=NumberMode.BOX),
    HaierNumberDef(OPT_EEV_IDLE_COOL, "eev_idle_cool", DEFAULT_EEV_IDLE_COOL, 0.0, 2000.0, step=0.001, icon="mdi:valve-closed", mode=NumberMode.BOX),
    HaierNumberDef(OPT_EEV_IDLE_HEAT, "eev_idle_heat", DEFAULT_EEV_IDLE_HEAT, 0.0, 2000.0, step=0.001, icon="mdi:valve-closed", mode=NumberMode.BOX),

    # Pipe length
    HaierNumberDef(OPT_PIPE_LENGTH, "pipe_length", DEFAULT_PIPE_LENGTH, 0.0, 30.0, step=0.5, unit="m", icon="mdi:pipe"),

    # Carnot
    HaierNumberDef(OPT_ETA_CARNOT_COOL, "eta_carnot_cool", DEFAULT_ETA_CARNOT_COOL, 0.20, 0.70, step=0.01, icon="mdi:gauge"),
    HaierNumberDef(OPT_ETA_CARNOT_HEAT, "eta_carnot_heat", DEFAULT_ETA_CARNOT_HEAT, 0.20, 0.70, step=0.01, icon="mdi:gauge"),

    # Idle
    HaierNumberDef(OPT_IDLE_BASE, "idle_base", DEFAULT_IDLE_BASE, 0.0, 50.0, step=0.5, unit=UnitOfPower.WATT, icon="mdi:flash-outline"),
    HaierNumberDef(OPT_IDLE_INDOOR_FAN, "idle_indoor_fan", DEFAULT_IDLE_INDOOR_FAN, 0.0, 50.0, step=0.5, unit=UnitOfPower.WATT, icon="mdi:fan"),
    HaierNumberDef(OPT_IDLE_OUTDOOR_FAN, "idle_outdoor_fan", DEFAULT_IDLE_OUTDOOR_FAN, 0.0, 200.0, step=1.0, unit=UnitOfPower.WATT, icon="mdi:fan"),
    HaierNumberDef(OPT_IDLE_CRANKCASE, "idle_crankcase", DEFAULT_IDLE_CRANKCASE, 0.0, 200.0, step=1.0, unit=UnitOfPower.WATT, icon="mdi:radiator"),

    # Sensor offset
    HaierNumberDef(OPT_OUTDOOR_AIR_DT_OFFSET, "outdoor_air_dt_offset", DEFAULT_OUTDOOR_AIR_DT_OFFSET, -3.0, 3.0, step=0.05, unit=UnitOfTemperature.CELSIUS, icon="mdi:thermometer-alert"),

    # Bypass factor
    HaierNumberDef(OPT_BYPASS_FACTOR, "bypass_factor", DEFAULT_BYPASS_FACTOR, 0.05, 0.30, step=0.01, icon="mdi:air-conditioner"),

    # Indoor airflow (AS25 Lo/Mid/Hi: 700/900/1100; AS35: 800/1000/1200; cassettes can exceed 1500)
    HaierNumberDef(OPT_INDOOR_AIRFLOW_NOMINAL, "indoor_airflow_nominal", DEFAULT_INDOOR_AIRFLOW_NOMINAL, 200.0, 2500.0, step=10.0, unit="m³/h", icon="mdi:weather-windy"),

    # Tariffs
    HaierNumberDef(OPT_DAY_TARIFF, "day_tariff", DEFAULT_DAY_TARIFF, 0.0, 100.0, step=0.01, icon="mdi:cash"),
    HaierNumberDef(OPT_NIGHT_TARIFF, "night_tariff", DEFAULT_NIGHT_TARIFF, 0.0, 100.0, step=0.01, icon="mdi:cash"),
]


class HaierMonitorNumber(HaierMonitorEntity, NumberEntity):
    """A calibration number entity backed by entry.options."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: HaierMonitorCoordinator,
        number_def: HaierNumberDef,
    ) -> None:
        super().__init__(
            coordinator, f"calibration_{number_def.option_key}", number_def.translation_key
        )
        self._def = number_def
        self._attr_native_min_value = number_def.minimum
        self._attr_native_max_value = number_def.maximum
        self._attr_native_step = number_def.step
        self._attr_native_unit_of_measurement = number_def.unit
        self._attr_icon = number_def.icon
        self._attr_mode = number_def.mode

    @property
    def native_value(self) -> float:
        return self.coordinator.entry.options.get(
            self._def.option_key, self._def.default
        )

    async def async_set_native_value(self, value: float) -> None:
        new_options = {**self.coordinator.entry.options, self._def.option_key: value}
        self.hass.config_entries.async_update_entry(
            self.coordinator.entry, options=new_options
        )
        self.coordinator.config = {**self.coordinator.entry.data, **new_options}
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up calibration number entities."""
    coordinator: HaierMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [HaierMonitorNumber(coordinator, nd) for nd in NUMBER_DEFS]
    async_add_entities(entities)
