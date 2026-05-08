"""Constants for Haier Multi-Split Monitor.

All values either from Service Manual 2U50S2SM1FA-3 V1 (2021-05-31)
or from peer-reviewed literature (Cuevas 2009, Tang 2021, ASHRAE Fundamentals).
"""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "haier_monitor"

# --- Configuration keys ---
CONF_OUTDOOR_TEMP_SOURCES: Final = "outdoor_temp_sources"
CONF_INDOOR_UNITS: Final = "indoor_units"
CONF_NAME: Final = "name"
CONF_CLIMATE_ENTITY: Final = "climate_entity"
CONF_OUTDOOR_TEMP: Final = "outdoor_temperature"
CONF_OUTDOOR_COIL_TEMP: Final = "outdoor_coil_temperature"
CONF_OUTDOOR_DEFROST_TEMP: Final = "outdoor_defrost_temperature"
CONF_OUTDOOR_IN_AIR_TEMP: Final = "outdoor_in_air_temperature"
CONF_OUTDOOR_OUT_AIR_TEMP: Final = "outdoor_out_air_temperature"
CONF_COMPRESSOR_FREQUENCY: Final = "compressor_frequency"
CONF_COMPRESSOR_STATUS: Final = "compressor_status"
CONF_INDOOR_FAN_STATUS: Final = "indoor_fan_status"
CONF_EEV_OPENING: Final = "eev_opening"
CONF_INDOOR_COIL_TEMP: Final = "indoor_coil_temperature"
CONF_NATIVE_POWER: Final = "native_power"
CONF_NATIVE_DEFROST: Final = "native_defrost_status"
CONF_NATIVE_OUTDOOR_FAN: Final = "native_outdoor_fan_status"
CONF_NATIVE_COMPRESSOR_CURRENT: Final = "native_compressor_current"
CONF_ROOM_TEMP_SENSOR: Final = "room_temperature"
CONF_ROOM_HUMIDITY_SENSOR: Final = "room_humidity"
CONF_ROOM_CAPACITY: Final = "room_capacity"
CONF_DAY_TARIFF: Final = "day_tariff"
CONF_NIGHT_TARIFF: Final = "night_tariff"
CONF_CURRENCY: Final = "currency"
CONF_PIPE_LENGTH: Final = "pipe_length_total"

# --- Calibration parameters (number entities, persisted in entry options) ---
OPT_EEV_MAX: Final = "eev_max"
OPT_EEV_IDLE_COOL: Final = "eev_idle_cool"
OPT_EEV_IDLE_HEAT: Final = "eev_idle_heat"
OPT_PIPE_LENGTH: Final = "pipe_length_total"
OPT_ETA_CARNOT_COOL: Final = "eta_carnot_cool"
OPT_ETA_CARNOT_HEAT: Final = "eta_carnot_heat"
OPT_IDLE_BASE: Final = "idle_base"
OPT_IDLE_INDOOR_FAN: Final = "idle_indoor_fan"
OPT_IDLE_OUTDOOR_FAN: Final = "idle_outdoor_fan"
OPT_IDLE_CRANKCASE: Final = "idle_crankcase_below_5c"
OPT_OUTDOOR_AIR_DT_OFFSET: Final = "outdoor_air_dt_offset"
OPT_BYPASS_FACTOR: Final = "bypass_factor"
OPT_INDOOR_AIRFLOW_NOMINAL: Final = "indoor_airflow_nominal"
OPT_DAY_TARIFF: Final = "day_tariff"
OPT_NIGHT_TARIFF: Final = "night_tariff"

# --- Calibration defaults ---
# EEV scale matches paveldn/haier-esphome master: hon_climate.cpp publishes
# expansion_valve_open_degree as raw/4095.0 (fraction 0.0..1.0). The unit label
# is "%" but the value is NOT scaled to 0..100 — it's a normalized fraction.
# Idle physical positions per Service Manual §7.1.5 are 5 steps cool / 80 heat
# on a 500-step PMV; expressed as fraction 0..1 they correspond to ≈ 0.001 / 0.16.
DEFAULT_EEV_MAX: Final = 1.0             # fraction of full open
DEFAULT_EEV_IDLE_COOL: Final = 0.001     # ≈ 5/4095 — service manual §7.1.5
DEFAULT_EEV_IDLE_HEAT: Final = 0.16      # ≈ 660/4095 — service manual §7.1.5
DEFAULT_PIPE_LENGTH: Final = 5.0         # m, standard pre-charge length
DEFAULT_ETA_CARNOT_COOL: Final = 0.40    # R32 ASHP typical
DEFAULT_ETA_CARNOT_HEAT: Final = 0.45    # R32 ASHP typical
DEFAULT_IDLE_BASE: Final = 8.0           # W, PCB + sensor bias
DEFAULT_IDLE_INDOOR_FAN: Final = 12.0    # W, per running IU fan
DEFAULT_IDLE_OUTDOOR_FAN: Final = 50.0   # W, OU fan minimum
DEFAULT_IDLE_CRANKCASE: Final = 30.0     # W, baseline below +5°C
DEFAULT_OUTDOOR_AIR_DT_OFFSET: Final = 0.0  # °C
DEFAULT_BYPASS_FACTOR: Final = 0.15      # ASHRAE typical residential coil BF
DEFAULT_INDOOR_AIRFLOW_NOMINAL: Final = 900.0  # m³/h, AS25 mid speed
DEFAULT_DAY_TARIFF: Final = 8.11         # RUB/kWh, default Russian rate
DEFAULT_NIGHT_TARIFF: Final = 3.49       # RUB/kWh
DEFAULT_ROOM_CAPACITY: Final = 2500      # W, AS25 rated
DEFAULT_CURRENCY: Final = "RUB"

# --- Physical constants ---
AIR_DENSITY: Final = 1.225               # kg/m³ at 15°C, 101.3 kPa
AIR_CP: Final = 1006.0                   # J/(kg·K), specific heat at const pressure
# Convenience: Q[W] = AIR_VOLUMETRIC_FACTOR × V[m³/h] × ΔT[K]
AIR_VOLUMETRIC_FACTOR: Final = AIR_DENSITY * AIR_CP / 3600.0  # ≈ 0.3424

# --- Outdoor unit specifications (Service Manual section 2) ---
OUTDOOR_FAN_RPM_MAX: Final = 950         # rpm, high speed
OUTDOOR_AIRFLOW_MAX: Final = 2900        # m³/h at high speed
COMPRESSOR_F_MIN_COOL: Final = 25        # Hz
COMPRESSOR_F_MIN_HEAT: Final = 30        # Hz

# --- Paspartные сезонные показатели (для % паспорта) ---
SEER_RATED: Final = 6.5                  # A++ for combination 2× AS25
SCOP_RATED: Final = 4.0                  # A+ for combination 2× AS25

# --- Update cadence ---
UPDATE_INTERVAL_SECONDS: Final = 30      # coordinator update interval
ENERGY_UPDATE_INTERVAL_SECONDS: Final = 60  # for Riemann sum integration

# --- Steady state thresholds ---
STEADY_STATE_MIN_UPTIME_SECONDS: Final = 300   # 5 min

# --- FDD persistence windows (seconds) ---
FDD_OUTDOOR_COIL_DELAY: Final = 3600         # 1h
FDD_OUTDOOR_COIL_OFF_DELAY: Final = 1800     # 30min
FDD_FILTER_DELAY: Final = 14400              # 4h
FDD_FILTER_OFF_DELAY: Final = 3600           # 1h
FDD_REFRIGERANT_DELAY: Final = 1800          # 30min
FDD_REFRIGERANT_OFF_DELAY: Final = 900       # 15min
FDD_CYCLING_DELAY: Final = 3600              # 1h
FDD_DEFROST_EXCESS_DELAY: Final = 1800       # 30min

# --- FDD thresholds ---
FDD_OUTDOOR_COIL_APPROACH_COOL_FAULT: Final = 18.0   # °C
FDD_OUTDOOR_COIL_APPROACH_COOL_WARN: Final = 15.0    # °C
FDD_OUTDOOR_COIL_APPROACH_HEAT_FAULT: Final = 12.0   # °C
FDD_OUTDOOR_COIL_APPROACH_HEAT_WARN: Final = 9.0     # °C
FDD_FILTER_APPROACH_FAULT: Final = 16.0              # °C ΔT через indoor coil
FDD_FILTER_APPROACH_WARN: Final = 14.0               # °C
FDD_FILTER_FROST_THRESHOLD: Final = 3.0              # °C T_indoor_coil
FDD_REFRIGERANT_EFFICIENCY_THRESHOLD: Final = 0.70   # actual/expected
FDD_REFRIGERANT_EEV_THRESHOLD: Final = 0.85          # fraction
FDD_REFRIGERANT_APPROACH_HEAT: Final = 15.0          # °C, indicator threshold for heat-mode leak suspicion
FDD_CYCLING_STARTS_PER_HOUR: Final = 5
FDD_DEFROST_EXCESS_PER_24H: Final = 10
FDD_DEFROST_LONG_MINUTES: Final = 12

# --- Health/efficiency thresholds (ratio actual/expected) ---
EFFICIENCY_EXCELLENT: Final = 0.95
EFFICIENCY_GOOD: Final = 0.80
EFFICIENCY_AVERAGE: Final = 0.65
SANITY_EXCELLENT_LOW: Final = 0.85
SANITY_EXCELLENT_HIGH: Final = 1.15
SANITY_GOOD_LOW: Final = 0.70
SANITY_GOOD_HIGH: Final = 1.30
SANITY_OK_LOW: Final = 0.50
SANITY_OK_HIGH: Final = 1.50

# --- Filter / outdoor cleaning reminder ---
FILTER_CLEAN_REMINDER_DAYS: Final = 90
OUTDOOR_CLEAN_REMINDER_DAYS: Final = 365

# --- Storage keys ---
STORAGE_VERSION: Final = 1
STORAGE_KEY_MAINTENANCE: Final = "maintenance"
STORAGE_KEY_ENERGY: Final = "energy"
STORAGE_KEY_HISTORY: Final = "history"

# --- Mode strings (matching HA climate state values) ---
MODE_COOL: Final = "cool"
MODE_HEAT: Final = "heat"
MODE_DRY: Final = "dry"
MODE_FAN: Final = "fan_only"
MODE_HEAT_COOL: Final = "heat_cool"
MODE_OFF: Final = "off"

ACTIVE_COOL_MODES: Final = (MODE_COOL, MODE_DRY)

# --- Severity levels ---
SEVERITY_OK: Final = "ok"
SEVERITY_INFO: Final = "info"
SEVERITY_WARN: Final = "warn"
SEVERITY_FAULT: Final = "fault"

# --- Localized status options (Russian for now; en in translations) ---
HEALTH_EXCELLENT: Final = "excellent"
HEALTH_GOOD: Final = "good"
HEALTH_AVERAGE: Final = "average"
HEALTH_PROBLEM: Final = "problem"
HEALTH_STARTING: Final = "starting"
HEALTH_DEFROSTING: Final = "defrosting"
HEALTH_IDLE: Final = "idle"
HEALTH_UNKNOWN: Final = "unknown"

EFFICIENCY_LABEL_EXCELLENT: Final = "excellent"
EFFICIENCY_LABEL_GOOD: Final = "good"
EFFICIENCY_LABEL_AVERAGE: Final = "average"
EFFICIENCY_LABEL_LOW: Final = "low"

SANITY_NORMAL: Final = "normal"
SANITY_LOW_MINOR: Final = "slightly_low"
SANITY_LOW_MAJOR: Final = "significantly_low"
SANITY_HIGH_MINOR: Final = "slightly_high"
SANITY_HIGH_MAJOR: Final = "significantly_high"

COMPONENT_STATUS_CLEAN: Final = "clean"
COMPONENT_STATUS_POSSIBLY_DIRTY: Final = "possibly_dirty"
COMPONENT_STATUS_NEEDS_CLEANING: Final = "needs_cleaning"
COMPONENT_STATUS_NORMAL: Final = "normal"
COMPONENT_STATUS_LEAK_SUSPECTED: Final = "leak_suspected"
COMPONENT_STATUS_FREQUENT_DEFROST: Final = "frequent"
COMPONENT_STATUS_LONG_DEFROST: Final = "long"
COMPONENT_STATUS_UNKNOWN: Final = "unknown"

# --- SEER/SCOP energy class boundaries (EU energy label) ---
# Cooling: A+++ ≥8.5, A++ ≥6.1, A+ ≥5.6, A ≥5.1, B ≥4.6, C <4.6
SEER_CLASS_BOUNDARIES: Final = [
    (8.5, "A+++"),
    (6.1, "A++"),
    (5.6, "A+"),
    (5.1, "A"),
    (4.6, "B"),
    (0.0, "C_or_lower"),
]
# Heating average climate: A+++ ≥5.1, A++ ≥4.6, A+ ≥4.0, A ≥3.4, B ≥3.1, C <3.1
SCOP_CLASS_BOUNDARIES: Final = [
    (5.1, "A+++"),
    (4.6, "A++"),
    (4.0, "A+"),
    (3.4, "A"),
    (3.1, "B"),
    (0.0, "C_or_lower"),
]

# --- Tariff time ranges (2-tariff system, default Russia) ---
# Day tariff: 07:00-23:00, night tariff: 23:00-07:00
DAY_TARIFF_HOUR_START: Final = 7
DAY_TARIFF_HOUR_END: Final = 23


# --- Issue code → user-facing message (for top_message sensor) ---
# Russian by default; switch to English in code if you prefer.
ISSUE_MESSAGES: Final = {
    "refrigerant_low": "Подозрение на утечку фреона — обратись в сервис",
    "outdoor_coil_dirty": "Промой наружный блок — теплообмен снижен",
    "outdoor_clean_due": "Наружный блок не мыли давно — пора весной/осенью",
    "excessive_defrost": "Слишком много циклов оттайки — проверь обмерзание наружника",
    "short_cycling": "Компрессор часто включается-выключается",
}


def issue_message(code: str, days: int | None = None) -> str:
    """Return human-readable message for an issue code."""
    # Per-room dynamic codes
    if code.startswith("filter_") and code.endswith("_dirty"):
        room = code[len("filter_") : -len("_dirty")]
        return f"Почисти фильтр в комнате '{room}'"
    if code.startswith("filter_") and code.endswith("_due"):
        room = code[len("filter_") : -len("_due")]
        if days is not None:
            return f"Фильтр '{room}' не чистили {days} дней — пора"
        return f"Фильтр '{room}' давно не чистили — пора"
    if code == "outdoor_clean_due" and days is not None:
        return f"Наружный блок не мыли {days} дней — пора"
    return ISSUE_MESSAGES.get(code, code)
