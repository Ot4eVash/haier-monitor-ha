"""Coordinator for Haier Multi-Split Monitor.

Centralized calculation engine — runs every UPDATE_INTERVAL_SECONDS and
populates a dict consumed by all sensor/binary_sensor entities.

Architecture:
    1. Read raw entity states (with safe_float fallbacks)
    2. Compute lookup table values
    3. Compute physics layer (P_elec, Q_outdoor, Q_indoor)
    4. Compute KPIs (COP/EER, expected, efficiency ratio)
    5. Update Riemann sum integrals (kWh)
    6. Compute approach temperatures
    7. Compute persistence-windowed FDD flags
    8. Generate recommendation list
    9. Publish data to listeners
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import math
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import lookup_tables as lt
from . import physics as ph
from .const import (
    ACTIVE_COOL_MODES,
    CONF_CLIMATE_ENTITY,
    CONF_COMPRESSOR_FREQUENCY,
    CONF_COMPRESSOR_STATUS,
    CONF_EEV_OPENING,
    CONF_INDOOR_COIL_TEMP,
    CONF_INDOOR_FAN_STATUS,
    CONF_INDOOR_UNITS,
    CONF_NAME,
    CONF_NATIVE_COMPRESSOR_CURRENT,
    CONF_NATIVE_DEFROST,
    CONF_NATIVE_OUTDOOR_FAN,
    CONF_NATIVE_POWER,
    CONF_OUTDOOR_COIL_TEMP,
    CONF_OUTDOOR_DEFROST_TEMP,
    CONF_OUTDOOR_IN_AIR_TEMP,
    CONF_OUTDOOR_OUT_AIR_TEMP,
    CONF_OUTDOOR_TEMP,
    CONF_OUTDOOR_TEMP_SOURCES,
    CONF_ROOM_CAPACITY,
    CONF_ROOM_HUMIDITY_SENSOR,
    CONF_ROOM_TEMP_SENSOR,
    DAY_TARIFF_HOUR_END,
    DAY_TARIFF_HOUR_START,
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
    EFFICIENCY_AVERAGE,
    EFFICIENCY_EXCELLENT,
    EFFICIENCY_GOOD,
    FDD_CYCLING_STARTS_PER_HOUR,
    FDD_DEFROST_EXCESS_PER_24H,
    FDD_DEFROST_LONG_MINUTES,
    FDD_FILTER_APPROACH_FAULT,
    FDD_FILTER_APPROACH_WARN,
    FDD_FILTER_FROST_THRESHOLD,
    FDD_OUTDOOR_COIL_APPROACH_COOL_FAULT,
    FDD_OUTDOOR_COIL_APPROACH_COOL_WARN,
    FDD_OUTDOOR_COIL_APPROACH_HEAT_FAULT,
    FDD_OUTDOOR_COIL_APPROACH_HEAT_WARN,
    FDD_REFRIGERANT_APPROACH_HEAT,
    FDD_REFRIGERANT_EEV_THRESHOLD,
    FDD_REFRIGERANT_EFFICIENCY_THRESHOLD,
    FILTER_CLEAN_REMINDER_DAYS,
    HEALTH_AVERAGE,
    HEALTH_DEFROSTING,
    HEALTH_EXCELLENT,
    HEALTH_GOOD,
    HEALTH_IDLE,
    HEALTH_PROBLEM,
    HEALTH_STARTING,
    HEALTH_UNKNOWN,
    issue_message,
    MODE_DRY,
    MODE_FAN,
    MODE_HEAT,
    MODE_HEAT_COOL,
    MODE_OFF,
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
    OUTDOOR_CLEAN_REMINDER_DAYS,
    SANITY_EXCELLENT_HIGH,
    SANITY_EXCELLENT_LOW,
    SANITY_GOOD_HIGH,
    SANITY_GOOD_LOW,
    SANITY_OK_HIGH,
    SANITY_OK_LOW,
    SCOP_CLASS_BOUNDARIES,
    SCOP_RATED,
    SEER_CLASS_BOUNDARIES,
    SEER_RATED,
    SEVERITY_FAULT,
    SEVERITY_INFO,
    SEVERITY_OK,
    SEVERITY_WARN,
    STEADY_STATE_MIN_UPTIME_SECONDS,
    STORAGE_KEY_ENERGY,
    STORAGE_KEY_MAINTENANCE,
    STORAGE_VERSION,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


def safe_float(state, default: Optional[float] = None) -> Optional[float]:
    """Safely convert a HA state object to float, returning default on failure."""
    if state is None:
        return default
    if state.state in (None, "unknown", "unavailable", ""):
        return default
    try:
        return float(state.state)
    except (ValueError, TypeError):
        return default


def safe_bool(state, default: bool = False) -> bool:
    """Convert HA state to bool. Treats 'on' as True, 'off' as False."""
    if state is None:
        return default
    if state.state == "on":
        return True
    if state.state == "off":
        return False
    return default


# ---------------------------------------------------------------------------
# Smoothing buffers — sliding window mean/median
# ---------------------------------------------------------------------------
@dataclass
class SmoothBuffer:
    """Time-windowed smoothing buffer (mean over last N samples)."""

    window_seconds: int = 300  # 5 min default
    samples: deque = field(default_factory=deque)

    def push(self, value: Optional[float], now: datetime) -> None:
        """Add a sample and prune old samples beyond window."""
        if value is None:
            return
        self.samples.append((now, value))
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    @property
    def mean(self) -> Optional[float]:
        """Mean of current window."""
        if not self.samples:
            return None
        return sum(v for _, v in self.samples) / len(self.samples)


# ---------------------------------------------------------------------------
# Persistence-window flag (delay_on / delay_off equivalent)
# ---------------------------------------------------------------------------
@dataclass
class PersistenceFlag:
    """Hysteresis flag: must hold condition for delay_on to set, delay_off to clear."""

    delay_on_seconds: int
    delay_off_seconds: int
    state: bool = False
    condition_since: Optional[datetime] = None
    last_condition: Optional[bool] = None

    def update(self, condition: bool, now: datetime) -> bool:
        """Update flag state based on current condition."""
        if condition != self.last_condition:
            self.condition_since = now
            self.last_condition = condition

        if self.condition_since is None:
            return self.state

        elapsed = (now - self.condition_since).total_seconds()

        if not self.state and condition and elapsed >= self.delay_on_seconds:
            self.state = True
        elif self.state and not condition and elapsed >= self.delay_off_seconds:
            self.state = False

        return self.state


# ---------------------------------------------------------------------------
# Defrost event log (for 24h frequency / duration history)
# ---------------------------------------------------------------------------
@dataclass
class DefrostHistory:
    """Track defrost cycles for 24h statistics."""

    in_defrost: bool = False
    defrost_started: Optional[datetime] = None
    events: list[tuple[datetime, datetime]] = field(default_factory=list)  # (start, end)

    def update(self, defrost_now: bool, now: datetime) -> None:
        """Update on defrost state transition."""
        if defrost_now and not self.in_defrost:
            self.in_defrost = True
            self.defrost_started = now
        elif not defrost_now and self.in_defrost:
            self.in_defrost = False
            if self.defrost_started:
                self.events.append((self.defrost_started, now))
                self.defrost_started = None
        # Prune events older than 24h
        cutoff = now - timedelta(hours=24)
        self.events = [(s, e) for s, e in self.events if e >= cutoff]

    def count_24h(self) -> int:
        return len(self.events)

    def avg_duration_min(self) -> float:
        if not self.events:
            return 0.0
        durations = [(e - s).total_seconds() / 60 for s, e in self.events]
        return sum(durations) / len(durations)


# ---------------------------------------------------------------------------
# Compressor cycling tracker (starts per hour)
# ---------------------------------------------------------------------------
@dataclass
class CyclingTracker:
    """Track compressor on/off transitions for cycling detection."""

    compressor_was_on: bool = False
    starts: deque = field(default_factory=deque)

    def update(self, compressor_running: bool, now: datetime) -> None:
        if compressor_running and not self.compressor_was_on:
            self.starts.append(now)
        self.compressor_was_on = compressor_running
        cutoff = now - timedelta(hours=1)
        while self.starts and self.starts[0] < cutoff:
            self.starts.popleft()

    def starts_per_hour(self) -> int:
        return len(self.starts)


# ---------------------------------------------------------------------------
# Riemann-sum energy integrator with daily/monthly/yearly buckets
# ---------------------------------------------------------------------------
@dataclass
class EnergyIntegrator:
    """Cumulative kWh integrator with utility-meter-like daily/monthly resets."""

    total_kwh: float = 0.0
    cool_total_kwh: float = 0.0
    heat_total_kwh: float = 0.0
    q_cool_total_kwh: float = 0.0
    q_heat_total_kwh: float = 0.0
    q_room1_total_kwh: float = 0.0
    q_room2_total_kwh: float = 0.0
    q_sensible_total_kwh: float = 0.0
    q_latent_total_kwh: float = 0.0
    last_update: Optional[datetime] = None

    # Daily / monthly / yearly snapshots
    daily_snapshots: dict[str, float] = field(default_factory=dict)
    monthly_snapshots: dict[str, float] = field(default_factory=dict)
    yearly_snapshots: dict[str, float] = field(default_factory=dict)
    last_daily_reset: Optional[str] = None  # ISO date string
    last_monthly_reset: Optional[str] = None  # YYYY-MM
    last_yearly_reset: Optional[str] = None  # YYYY

    # Per-tariff cumulative (day/night for cost calc)
    day_kwh: float = 0.0
    night_kwh: float = 0.0
    day_kwh_daily_snapshot: float = 0.0
    night_kwh_daily_snapshot: float = 0.0
    day_kwh_monthly_snapshot: float = 0.0
    night_kwh_monthly_snapshot: float = 0.0
    day_kwh_yearly_snapshot: float = 0.0
    night_kwh_yearly_snapshot: float = 0.0

    def integrate(
        self,
        p_elec_w: float,
        p_cool_w: float,
        p_heat_w: float,
        q_cool_w: float,
        q_heat_w: float,
        q_room1_w: float,
        q_room2_w: float,
        q_sensible_w: float,
        q_latent_w: float,
        now: datetime,
    ) -> None:
        """Riemann-left integration step."""
        if self.last_update is None:
            self.last_update = now
            return
        dt_h = (now - self.last_update).total_seconds() / 3600.0
        if dt_h <= 0 or dt_h > 1.0:
            # Skip if clock jumped or first call
            self.last_update = now
            return
        self.total_kwh += (p_elec_w / 1000) * dt_h
        self.cool_total_kwh += (p_cool_w / 1000) * dt_h
        self.heat_total_kwh += (p_heat_w / 1000) * dt_h
        self.q_cool_total_kwh += (q_cool_w / 1000) * dt_h
        self.q_heat_total_kwh += (q_heat_w / 1000) * dt_h
        self.q_room1_total_kwh += (q_room1_w / 1000) * dt_h
        self.q_room2_total_kwh += (q_room2_w / 1000) * dt_h
        self.q_sensible_total_kwh += (q_sensible_w / 1000) * dt_h
        self.q_latent_total_kwh += (q_latent_w / 1000) * dt_h

        # Tariff allocation
        hour = now.hour
        if DAY_TARIFF_HOUR_START <= hour < DAY_TARIFF_HOUR_END:
            self.day_kwh += (p_elec_w / 1000) * dt_h
        else:
            self.night_kwh += (p_elec_w / 1000) * dt_h

        self.last_update = now

    def get_period_value(
        self, snapshots: dict[str, float], current: float, key: str
    ) -> float:
        """Get current period total = current cumulative − snapshot at period start."""
        snap = snapshots.get(key, 0.0)
        return max(0.0, current - snap)

    def to_dict(self) -> dict:
        """Serialize for storage."""
        return {
            "total_kwh": self.total_kwh,
            "cool_total_kwh": self.cool_total_kwh,
            "heat_total_kwh": self.heat_total_kwh,
            "q_cool_total_kwh": self.q_cool_total_kwh,
            "q_heat_total_kwh": self.q_heat_total_kwh,
            "q_room1_total_kwh": self.q_room1_total_kwh,
            "q_room2_total_kwh": self.q_room2_total_kwh,
            "q_sensible_total_kwh": self.q_sensible_total_kwh,
            "q_latent_total_kwh": self.q_latent_total_kwh,
            "daily_snapshots": self.daily_snapshots,
            "monthly_snapshots": self.monthly_snapshots,
            "yearly_snapshots": self.yearly_snapshots,
            "last_daily_reset": self.last_daily_reset,
            "last_monthly_reset": self.last_monthly_reset,
            "last_yearly_reset": self.last_yearly_reset,
            "day_kwh": self.day_kwh,
            "night_kwh": self.night_kwh,
            "day_kwh_daily_snapshot": self.day_kwh_daily_snapshot,
            "night_kwh_daily_snapshot": self.night_kwh_daily_snapshot,
            "day_kwh_monthly_snapshot": self.day_kwh_monthly_snapshot,
            "night_kwh_monthly_snapshot": self.night_kwh_monthly_snapshot,
            "day_kwh_yearly_snapshot": self.day_kwh_yearly_snapshot,
            "night_kwh_yearly_snapshot": self.night_kwh_yearly_snapshot,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EnergyIntegrator":
        e = cls()
        # Legacy field rename (1.0 → 1.1): q_kitchen/q_bedroom → q_room1/q_room2
        if "q_kitchen_total_kwh" in data and "q_room1_total_kwh" not in data:
            data["q_room1_total_kwh"] = data.pop("q_kitchen_total_kwh")
        if "q_bedroom_total_kwh" in data and "q_room2_total_kwh" not in data:
            data["q_room2_total_kwh"] = data.pop("q_bedroom_total_kwh")
        for k, v in data.items():
            if hasattr(e, k):
                setattr(e, k, v)
        # Same rename inside snapshot dicts
        for snap_attr in ("daily_snapshots", "monthly_snapshots", "yearly_snapshots"):
            snap = getattr(e, snap_attr, None)
            if isinstance(snap, dict):
                if "q_kitchen" in snap and "q_room1" not in snap:
                    snap["q_room1"] = snap.pop("q_kitchen")
                if "q_bedroom" in snap and "q_room2" not in snap:
                    snap["q_room2"] = snap.pop("q_bedroom")
        return e


# ---------------------------------------------------------------------------
# Main coordinator
# ---------------------------------------------------------------------------
class HaierMonitorCoordinator(DataUpdateCoordinator):
    """Coordinator that computes all sensor values from raw HA states."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.config = {**entry.data, **entry.options}

        # State for stateful calculations
        self._compressor_started: Optional[datetime] = None
        self._compressor_was_on: bool = False
        self._defrost_history = DefrostHistory()
        self._cycling_tracker = CyclingTracker()
        self._energy = EnergyIntegrator()

        # Smoothing buffers (5 min mean for KPIs)
        self._smooth_eer = SmoothBuffer(window_seconds=300)
        self._smooth_cop = SmoothBuffer(window_seconds=300)
        self._smooth_eer_efficiency = SmoothBuffer(window_seconds=300)
        self._smooth_cop_efficiency = SmoothBuffer(window_seconds=300)
        self._smooth_q_sanity = SmoothBuffer(window_seconds=3600)
        self._smooth_approach_outdoor = SmoothBuffer(window_seconds=3600)
        self._smooth_approach_evap: dict[str, SmoothBuffer] = {}

        # FDD persistence flags
        self._fdd_outdoor_coil = PersistenceFlag(3600, 1800)
        self._fdd_filter: dict[str, PersistenceFlag] = {}
        self._fdd_refrigerant = PersistenceFlag(1800, 900)
        self._fdd_cycling = PersistenceFlag(3600, 1800)
        self._fdd_excessive_defrost = PersistenceFlag(1800, 21600)

        # Storage
        self._store_energy = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.{STORAGE_KEY_ENERGY}"
        )
        self._store_maintenance = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.{STORAGE_KEY_MAINTENANCE}",
        )
        self.maintenance_data: dict = {}

        # Init smoothing for each indoor unit
        for iu in self.config.get(CONF_INDOOR_UNITS, []):
            key = iu[CONF_NAME]
            self._smooth_approach_evap[key] = SmoothBuffer(window_seconds=3600)
            self._fdd_filter[key] = PersistenceFlag(14400, 3600)

    async def async_load_persistent(self) -> None:
        """Load energy and maintenance state from disk."""
        energy_data = await self._store_energy.async_load()
        if energy_data:
            self._energy = EnergyIntegrator.from_dict(energy_data)
        maintenance_data = await self._store_maintenance.async_load()
        if maintenance_data:
            self.maintenance_data = maintenance_data

    async def async_save_persistent(self) -> None:
        """Save energy and maintenance state to disk."""
        await self._store_energy.async_save(self._energy.to_dict())
        await self._store_maintenance.async_save(self.maintenance_data)

    @callback
    def async_register_midnight_listener(self):
        """Snapshot energy buckets exactly at local-time 00:00 each day.

        Without this, the daily/monthly rollover only happens on the first
        coordinator tick after midnight — which after an HA restart at 03:00
        would silently absorb several hours of consumption into the new
        daily snapshot. Returns the unsubscribe function.
        """
        async def _at_midnight(_now: datetime) -> None:
            self._maybe_reset_periods(dt_util.utcnow())
            await self.async_save_persistent()
            await self.async_request_refresh()

        return async_track_time_change(
            self.hass, _at_midnight, hour=0, minute=0, second=2
        )

    async def async_set_filter_cleaned(self, room_name: str) -> None:
        """Mark filter as cleaned now for given room."""
        key = f"filter_last_clean_{room_name}"
        self.maintenance_data[key] = dt_util.utcnow().isoformat()
        await self.async_save_persistent()
        await self.async_request_refresh()

    async def async_set_outdoor_cleaned(self) -> None:
        """Mark outdoor coil as cleaned now."""
        self.maintenance_data["outdoor_last_clean"] = dt_util.utcnow().isoformat()
        await self.async_save_persistent()
        await self.async_request_refresh()

    def _opt(self, key: str, default: Any) -> Any:
        """Read a calibration option (entry.options) with fallback to default."""
        return self.entry.options.get(key, default)

    def _agg_outdoor_temp(self, sources: list[str], default: Optional[float] = None) -> Optional[float]:
        """Average available outdoor temperatures across all sources."""
        vals = []
        for src in sources:
            v = safe_float(self.hass.states.get(src))
            if v is not None:
                vals.append(v)
        if not vals:
            return default
        return sum(vals) / len(vals)

    def _max_present(self, sources: list[str], default: Optional[float] = None) -> Optional[float]:
        """Max of available values (used for compressor frequency)."""
        vals = []
        for src in sources:
            v = safe_float(self.hass.states.get(src))
            if v is not None:
                vals.append(v)
        if not vals:
            return default
        return max(vals)

    def _any_on(self, sources: list[str]) -> bool:
        for src in sources:
            if safe_bool(self.hass.states.get(src)):
                return True
        return False

    def _native_power(self, sources: list[str]) -> Optional[float]:
        """Take max of native ESPHome power sensors (compressor on each side)."""
        vals = []
        for src in sources:
            v = safe_float(self.hass.states.get(src))
            if v is not None and v > 0:
                vals.append(v)
        if not vals:
            return None
        return max(vals)

    def _native_defrost(self, sources: list[str]) -> Optional[bool]:
        """True if any native defrost sensor is on; None if none configured."""
        any_configured = False
        for src in sources:
            if not src:
                continue
            any_configured = True
            if safe_bool(self.hass.states.get(src)):
                return True
        if not any_configured:
            return None
        return False

    async def _async_update_data(self) -> dict[str, Any]:
        """Main calculation pipeline."""
        try:
            return self._compute_all()
        except Exception as exc:
            _LOGGER.exception("Error computing Haier monitor data: %s", exc)
            return self.data or {}

    def _compute_all(self) -> dict[str, Any]:
        """Compute all derived values. Pure function of HA states + own state."""
        now = dt_util.utcnow()
        data: dict[str, Any] = {"timestamp": now}

        cfg = self.config
        indoor_units = cfg.get(CONF_INDOOR_UNITS, [])

        # ------ Layer 0: raw aggregates ------
        outdoor_temp_sources = cfg.get(CONF_OUTDOOR_TEMP_SOURCES, {})
        t_outdoor = self._agg_outdoor_temp(
            outdoor_temp_sources.get(CONF_OUTDOOR_TEMP, [])
        )
        t_outdoor_coil = self._agg_outdoor_temp(
            outdoor_temp_sources.get(CONF_OUTDOOR_COIL_TEMP, [])
        )
        t_outdoor_defrost = self._agg_outdoor_temp(
            outdoor_temp_sources.get(CONF_OUTDOOR_DEFROST_TEMP, [])
        )
        t_outdoor_in_air = self._agg_outdoor_temp(
            outdoor_temp_sources.get(CONF_OUTDOOR_IN_AIR_TEMP, [])
        )
        t_outdoor_out_air = self._agg_outdoor_temp(
            outdoor_temp_sources.get(CONF_OUTDOOR_OUT_AIR_TEMP, [])
        )
        f_comp = self._max_present(
            outdoor_temp_sources.get(CONF_COMPRESSOR_FREQUENCY, [])
        )
        compressor_running = self._any_on(
            outdoor_temp_sources.get(CONF_COMPRESSOR_STATUS, [])
        )

        outdoor_air_dt = None
        if t_outdoor_in_air is not None and t_outdoor_out_air is not None:
            offset = self._opt(OPT_OUTDOOR_AIR_DT_OFFSET, DEFAULT_OUTDOOR_AIR_DT_OFFSET)
            outdoor_air_dt = (t_outdoor_out_air - t_outdoor_in_air) - offset

        data["outdoor_temperature"] = t_outdoor
        data["outdoor_coil_temperature"] = t_outdoor_coil
        data["outdoor_defrost_temperature"] = t_outdoor_defrost
        data["outdoor_in_air_temperature"] = t_outdoor_in_air
        data["outdoor_out_air_temperature"] = t_outdoor_out_air
        data["outdoor_air_dt"] = outdoor_air_dt
        data["compressor_frequency"] = f_comp
        data["compressor_running"] = compressor_running

        # Native sensors
        native_power = self._native_power(
            outdoor_temp_sources.get(CONF_NATIVE_POWER, [])
        )
        native_compressor_current = self._max_present(
            outdoor_temp_sources.get(CONF_NATIVE_COMPRESSOR_CURRENT, [])
        )
        native_outdoor_fan = self._native_defrost(
            outdoor_temp_sources.get(CONF_NATIVE_OUTDOOR_FAN, [])
        )
        native_defrost = self._native_defrost(
            outdoor_temp_sources.get(CONF_NATIVE_DEFROST, [])
        )
        data["native_power"] = native_power
        data["compressor_current"] = native_compressor_current

        # Per-room reads
        rooms_data: dict[str, dict] = {}
        avg_indoor_temp_vals = []
        for iu in indoor_units:
            name = iu[CONF_NAME]
            r = {}
            r["name"] = name
            r["climate_state"] = self.hass.states.get(iu.get(CONF_CLIMATE_ENTITY, "")).state if iu.get(CONF_CLIMATE_ENTITY) and self.hass.states.get(iu.get(CONF_CLIMATE_ENTITY)) else None
            r["fan_running"] = safe_bool(self.hass.states.get(iu.get(CONF_INDOOR_FAN_STATUS, "")))
            r["t_room"] = safe_float(self.hass.states.get(iu.get(CONF_ROOM_TEMP_SENSOR, "")))
            r["rh_room"] = safe_float(self.hass.states.get(iu.get(CONF_ROOM_HUMIDITY_SENSOR, "")))
            r["t_indoor_coil"] = safe_float(self.hass.states.get(iu.get(CONF_INDOOR_COIL_TEMP, "")))
            r["eev_raw"] = safe_float(self.hass.states.get(iu.get(CONF_EEV_OPENING, ""))) or 0.0
            r["capacity"] = float(iu.get(CONF_ROOM_CAPACITY, 2500))
            if r["t_room"] is not None:
                avg_indoor_temp_vals.append(r["t_room"])
            rooms_data[name] = r

        avg_indoor_temp = (
            sum(avg_indoor_temp_vals) / len(avg_indoor_temp_vals)
            if avg_indoor_temp_vals
            else 22.0
        )
        data["indoor_temperature_avg"] = avg_indoor_temp

        # ------ Layer 1: mode and state ------
        # Compute system mode from indoor units' climate states
        mode = MODE_OFF
        modes = [r["climate_state"] for r in rooms_data.values() if r["climate_state"]]
        if "cool" in modes:
            mode = "cool"
        elif "heat" in modes:
            mode = "heat"
        elif "dry" in modes:
            mode = "dry"
        elif "fan_only" in modes:
            mode = "fan_only"
        elif "heat_cool" in modes:
            mode = "heat_cool"
        data["mode"] = mode

        # Compressor uptime & cycling
        if compressor_running and not self._compressor_was_on:
            self._compressor_started = now
        if not compressor_running:
            self._compressor_started = None
        self._compressor_was_on = compressor_running
        compressor_uptime_min = (
            (now - self._compressor_started).total_seconds() / 60.0
            if self._compressor_started
            else 0.0
        )
        data["compressor_uptime_min"] = compressor_uptime_min

        self._cycling_tracker.update(compressor_running, now)
        data["compressor_starts_per_hour"] = self._cycling_tracker.starts_per_hour()

        # Defrost detection (must run before outdoor_fan fallback —
        # during defrost the outdoor fan is OFF even though compressor is ON,
        # so the proxy must subtract this case to avoid double-counting fan idle power).
        in_defrost = ph.is_defrost(
            mode=mode,
            compressor_running=compressor_running,
            t_outdoor=t_outdoor,
            t_outdoor_coil=t_outdoor_coil,
            t_defrost=t_outdoor_defrost,
            delta_t_air=outdoor_air_dt,
            native_defrost_status=native_defrost,
        )
        data["in_defrost"] = in_defrost
        self._defrost_history.update(in_defrost, now)
        data["defrost_count_24h"] = self._defrost_history.count_24h()
        data["defrost_avg_minutes"] = self._defrost_history.avg_duration_min()

        # Outdoor fan running (native or fallback to compressor minus defrost)
        if native_outdoor_fan is not None:
            outdoor_fan_running = native_outdoor_fan
        else:
            outdoor_fan_running = compressor_running and not in_defrost
        data["outdoor_fan_running"] = outdoor_fan_running

        # Steady state
        steady_state = (
            compressor_running
            and not in_defrost
            and compressor_uptime_min * 60 > STEADY_STATE_MIN_UPTIME_SECONDS
        )
        data["steady_state"] = steady_state

        # ------ Layer 2: lookup tables ------
        # Use `is None` checks rather than `or` to avoid truthiness bug where
        # T_outdoor = 0.0°C (common in winter / ESPHome stale-state edge cases)
        # would silently fall back to 20.0°C and skew lookup tables by 3-5×.
        t_for_tables = t_outdoor if t_outdoor is not None else 20.0
        f_for_rpm = f_comp if f_comp is not None else 0.0
        comp_f_max = lt.f_max(t_for_tables, mode)
        comp_f_min = lt.f_min(mode)
        outdoor_fan_rpm = (
            lt.outdoor_fan_rpm(t_for_tables, f_for_rpm, mode)
            if outdoor_fan_running
            else 0.0
        )
        airflow = lt.outdoor_airflow(outdoor_fan_rpm)
        p_max = lt.p_max_table(t_for_tables, avg_indoor_temp, mode)
        q_max = lt.q_max_table(t_for_tables, avg_indoor_temp, mode)

        data["comp_f_max"] = comp_f_max
        data["comp_f_min"] = comp_f_min
        data["outdoor_fan_rpm"] = outdoor_fan_rpm
        data["outdoor_airflow"] = airflow
        data["p_elec_max"] = p_max
        data["q_max"] = q_max
        data["eer_table"] = (q_max / p_max) if p_max > 50 else 0.0

        # ------ Layer 3: physics ------
        indoor_fans_running = sum(1 for r in rooms_data.values() if r["fan_running"])
        p_idle = ph.idle_power(
            t_outdoor=t_outdoor,
            mode=mode,
            compressor_running=compressor_running,
            indoor_fans_running_count=indoor_fans_running,
            outdoor_fan_running=outdoor_fan_running,
            idle_base=self._opt(OPT_IDLE_BASE, DEFAULT_IDLE_BASE),
            idle_indoor_fan=self._opt(OPT_IDLE_INDOOR_FAN, DEFAULT_IDLE_INDOOR_FAN),
            idle_outdoor_fan=self._opt(OPT_IDLE_OUTDOOR_FAN, DEFAULT_IDLE_OUTDOOR_FAN),
            idle_crankcase=self._opt(OPT_IDLE_CRANKCASE, DEFAULT_IDLE_CRANKCASE),
        )
        p_modeled = ph.p_elec_modeled(
            p_idle=p_idle,
            f_comp=f_comp,
            f_max=comp_f_max,
            p_max=p_max,
            compressor_running=compressor_running,
        )
        p_elec, p_source = ph.p_elec_best(native_power, p_modeled)

        data["p_idle"] = p_idle
        data["p_elec_modeled"] = p_modeled
        data["p_elec"] = p_elec
        data["p_elec_source"] = p_source

        q_outdoor = (
            ph.q_outdoor_air(airflow, outdoor_air_dt, 0.0)
            if outdoor_air_dt is not None
            else 0.0
        )
        q_indoor = ph.q_indoor_total(
            q_outdoor=q_outdoor,
            p_elec=p_elec,
            p_idle=p_idle,
            mode=mode,
            pipe_length=self._opt(OPT_PIPE_LENGTH, DEFAULT_PIPE_LENGTH),
            in_defrost=in_defrost,
            steady_state=steady_state,
        )
        data["q_outdoor_air"] = q_outdoor
        data["q_indoor_total"] = q_indoor

        # ------ Per-room: dewpoint, condensation, sensible, share ------
        bypass = self._opt(OPT_BYPASS_FACTOR, DEFAULT_BYPASS_FACTOR)
        indoor_airflow = self._opt(
            OPT_INDOOR_AIRFLOW_NOMINAL, DEFAULT_INDOOR_AIRFLOW_NOMINAL
        )
        eev_idle = (
            self._opt(OPT_EEV_IDLE_COOL, DEFAULT_EEV_IDLE_COOL)
            if mode in ACTIVE_COOL_MODES
            else (
                self._opt(OPT_EEV_IDLE_HEAT, DEFAULT_EEV_IDLE_HEAT)
                if mode == MODE_HEAT
                else 0.0
            )
        )
        max_capacity = max((r["capacity"] for r in rooms_data.values()), default=2500)

        proxies = []
        for name, r in rooms_data.items():
            if r["t_room"] is not None and r["rh_room"] is not None:
                r["dewpoint"] = ph.dewpoint(r["t_room"], r["rh_room"])
            else:
                r["dewpoint"] = None
            r["condensation"] = ph.is_condensation_active(
                r["t_indoor_coil"], r["dewpoint"], r["fan_running"], mode
            )
            r["q_sensible"] = ph.q_sensible_per_room(
                r["t_room"],
                r["t_indoor_coil"],
                r["fan_running"],
                indoor_airflow,
                bypass,
                mode,
            )
            r["approach_evap"] = ph.approach_evap_indoor(
                r["t_room"], r["t_indoor_coil"], mode
            )
            r["mass_flow_proxy"] = ph.room_share(
                r["eev_raw"], eev_idle, r["capacity"], max_capacity, r["fan_running"]
            )
            proxies.append(r["mass_flow_proxy"])

        shares = ph.normalize_shares(proxies)
        for (name, r), share in zip(rooms_data.items(), shares):
            r["share"] = share
            r["q_room"] = q_indoor * share

        data["rooms"] = rooms_data

        # Total sensible / latent (capped at q_indoor for sanity)
        q_sensible_total = min(
            sum(r["q_sensible"] for r in rooms_data.values()), q_indoor
        ) if mode != MODE_HEAT else q_indoor
        q_latent_total = max(0.0, q_indoor - q_sensible_total)
        shr = q_sensible_total / q_indoor if q_indoor > 200 else 1.0

        data["q_sensible_total"] = q_sensible_total
        data["q_latent_total"] = q_latent_total
        data["shr"] = shr

        # Approach outdoor
        approach_outdoor = ph.approach_outdoor(t_outdoor_coil, t_outdoor_in_air, mode)
        data["approach_outdoor"] = approach_outdoor
        if approach_outdoor is not None and steady_state:
            self._smooth_approach_outdoor.push(approach_outdoor, now)
        data["approach_outdoor_smoothed"] = self._smooth_approach_outdoor.mean

        for name, r in rooms_data.items():
            ap = r["approach_evap"]
            if ap is not None and steady_state and r["fan_running"]:
                self._smooth_approach_evap[name].push(ap, now)
            r["approach_evap_smoothed"] = self._smooth_approach_evap[name].mean

        # ------ Layer 5: KPIs ------
        eer = q_indoor / p_elec if (steady_state and mode in ACTIVE_COOL_MODES and p_elec > 50) else None
        cop = q_indoor / p_elec if (steady_state and mode == MODE_HEAT and p_elec > 50) else None
        data["eer_instant"] = eer
        data["cop_instant"] = cop

        if eer is not None:
            self._smooth_eer.push(eer, now)
        if cop is not None:
            self._smooth_cop.push(cop, now)
        data["eer_smoothed"] = self._smooth_eer.mean
        data["cop_smoothed"] = self._smooth_cop.mean

        # Expected (paspartный = q_max/p_max)
        eer_expected = data["eer_table"] if mode in ACTIVE_COOL_MODES and data["eer_table"] > 0 else None
        cop_expected = data["eer_table"] if mode == MODE_HEAT and data["eer_table"] > 0 else None
        data["eer_expected"] = eer_expected
        data["cop_expected"] = cop_expected

        # Carnot derived
        data["cop_carnot"] = ph.expected_cop_carnot(
            t_outdoor_coil,
            sum((r["t_indoor_coil"] for r in rooms_data.values() if r["t_indoor_coil"] is not None), 0.0)
            / max(1, sum(1 for r in rooms_data.values() if r["t_indoor_coil"] is not None)) if any(r["t_indoor_coil"] is not None for r in rooms_data.values()) else None,
            self._opt(OPT_ETA_CARNOT_COOL, DEFAULT_ETA_CARNOT_COOL) if mode in ACTIVE_COOL_MODES else self._opt(OPT_ETA_CARNOT_HEAT, DEFAULT_ETA_CARNOT_HEAT),
            mode,
        )

        # Efficiency ratios
        eer_efficiency = (eer / eer_expected) if (eer is not None and eer_expected) else None
        cop_efficiency = (cop / cop_expected) if (cop is not None and cop_expected) else None
        data["eer_efficiency"] = eer_efficiency
        data["cop_efficiency"] = cop_efficiency

        if eer_efficiency is not None:
            self._smooth_eer_efficiency.push(eer_efficiency, now)
        if cop_efficiency is not None:
            self._smooth_cop_efficiency.push(cop_efficiency, now)
        data["eer_efficiency_smoothed"] = self._smooth_eer_efficiency.mean
        data["cop_efficiency_smoothed"] = self._smooth_cop_efficiency.mean

        # Sanity ratio (Q_real / Q_expected at current f)
        sanity = None
        if steady_state and comp_f_max > 0 and q_max > 0 and f_comp:
            q_expected_at_f = q_max * f_comp / comp_f_max
            if q_expected_at_f > 200:
                sanity = q_indoor / q_expected_at_f
        data["q_sanity_ratio"] = sanity
        if sanity is not None:
            self._smooth_q_sanity.push(sanity, now)
        data["q_sanity_smoothed"] = self._smooth_q_sanity.mean

        # ------ Layer 6: energy integration ------
        # SEER/SCOP must be computed over comparable windows: q_indoor is
        # gated to 0 outside steady_state (in physics.q_indoor_total), so
        # mirror that gate on p_cool/p_heat to avoid systematic SEER bias.
        # The unconditional `p_elec` is still integrated as `total_kwh`.
        seer_window = steady_state and not in_defrost
        p_cool = p_elec if (mode in ACTIVE_COOL_MODES and seer_window) else 0.0
        p_heat = p_elec if (mode == MODE_HEAT and seer_window) else 0.0
        q_cool_w = q_indoor if mode in ACTIVE_COOL_MODES else 0.0
        q_heat_w = q_indoor if mode == MODE_HEAT else 0.0
        rooms_list = list(rooms_data.items())
        q_room1 = rooms_list[0][1].get("q_room", 0.0) if rooms_list else 0.0
        q_room2 = rooms_list[1][1].get("q_room", 0.0) if len(rooms_list) > 1 else 0.0

        self._energy.integrate(
            p_elec_w=p_elec,
            p_cool_w=p_cool,
            p_heat_w=p_heat,
            q_cool_w=q_cool_w,
            q_heat_w=q_heat_w,
            q_room1_w=q_room1,
            q_room2_w=q_room2,
            q_sensible_w=q_sensible_total,
            q_latent_w=q_latent_total,
            now=now,
        )

        # Period snapshot resets
        self._maybe_reset_periods(now)

        # Period values
        local_now = dt_util.as_local(now)
        date_key = local_now.strftime("%Y-%m-%d")
        month_key = local_now.strftime("%Y-%m")
        year_key = local_now.strftime("%Y")
        data["e_elec_total"] = self._energy.total_kwh
        data["e_elec_cool_total"] = self._energy.cool_total_kwh
        data["e_elec_heat_total"] = self._energy.heat_total_kwh
        data["q_cool_total"] = self._energy.q_cool_total_kwh
        data["q_heat_total"] = self._energy.q_heat_total_kwh
        data["q_room1_total"] = self._energy.q_room1_total_kwh
        data["q_room2_total"] = self._energy.q_room2_total_kwh
        data["q_sensible_total_kwh"] = self._energy.q_sensible_total_kwh
        data["q_latent_total_kwh"] = self._energy.q_latent_total_kwh

        data["e_elec_daily"] = self._energy.get_period_value(
            self._energy.daily_snapshots, self._energy.total_kwh, "e_elec"
        )
        data["e_elec_monthly"] = self._energy.get_period_value(
            self._energy.monthly_snapshots, self._energy.total_kwh, "e_elec"
        )
        data["e_elec_yearly"] = self._energy.get_period_value(
            self._energy.yearly_snapshots, self._energy.total_kwh, "e_elec"
        )
        data["e_elec_cool_monthly"] = self._energy.get_period_value(
            self._energy.monthly_snapshots, self._energy.cool_total_kwh, "e_elec_cool"
        )
        data["e_elec_heat_monthly"] = self._energy.get_period_value(
            self._energy.monthly_snapshots, self._energy.heat_total_kwh, "e_elec_heat"
        )
        data["q_cool_daily"] = self._energy.get_period_value(
            self._energy.daily_snapshots, self._energy.q_cool_total_kwh, "q_cool"
        )
        data["q_cool_monthly"] = self._energy.get_period_value(
            self._energy.monthly_snapshots, self._energy.q_cool_total_kwh, "q_cool"
        )
        data["q_heat_daily"] = self._energy.get_period_value(
            self._energy.daily_snapshots, self._energy.q_heat_total_kwh, "q_heat"
        )
        data["q_heat_monthly"] = self._energy.get_period_value(
            self._energy.monthly_snapshots, self._energy.q_heat_total_kwh, "q_heat"
        )
        data["q_room1_monthly"] = self._energy.get_period_value(
            self._energy.monthly_snapshots, self._energy.q_room1_total_kwh, "q_room1"
        )
        data["q_room2_monthly"] = self._energy.get_period_value(
            self._energy.monthly_snapshots, self._energy.q_room2_total_kwh, "q_room2"
        )

        # SEER / SCOP running
        data["seer_running"] = (
            self._energy.q_cool_total_kwh / self._energy.cool_total_kwh
            if self._energy.cool_total_kwh > 0.1
            else None
        )
        data["scop_running"] = (
            self._energy.q_heat_total_kwh / self._energy.heat_total_kwh
            if self._energy.heat_total_kwh > 0.1
            else None
        )
        data["seer_pct"] = (
            data["seer_running"] / SEER_RATED * 100
            if data["seer_running"] is not None
            else None
        )
        data["scop_pct"] = (
            data["scop_running"] / SCOP_RATED * 100
            if data["scop_running"] is not None
            else None
        )
        data["seer_grade"] = ph.energy_class(
            data["seer_running"], SEER_CLASS_BOUNDARIES
        )
        data["scop_grade"] = ph.energy_class(
            data["scop_running"], SCOP_CLASS_BOUNDARIES
        )

        # Cost via tariff-aware allocation: day/night kWh tracked separately
        # in EnergyIntegrator and snapshotted at period boundaries — multiply
        # each fraction by its own tariff, never the average.
        day_tariff = self._opt(OPT_DAY_TARIFF, DEFAULT_DAY_TARIFF)
        night_tariff = self._opt(OPT_NIGHT_TARIFF, DEFAULT_NIGHT_TARIFF)
        day_daily = max(0.0, self._energy.day_kwh - self._energy.day_kwh_daily_snapshot)
        night_daily = max(0.0, self._energy.night_kwh - self._energy.night_kwh_daily_snapshot)
        day_monthly = max(0.0, self._energy.day_kwh - self._energy.day_kwh_monthly_snapshot)
        night_monthly = max(0.0, self._energy.night_kwh - self._energy.night_kwh_monthly_snapshot)
        day_yearly = max(0.0, self._energy.day_kwh - self._energy.day_kwh_yearly_snapshot)
        night_yearly = max(0.0, self._energy.night_kwh - self._energy.night_kwh_yearly_snapshot)
        data["cost_daily"] = day_daily * day_tariff + night_daily * night_tariff
        data["cost_monthly"] = day_monthly * day_tariff + night_monthly * night_tariff
        data["cost_yearly"] = day_yearly * day_tariff + night_yearly * night_tariff
        data["e_elec_day_daily"] = day_daily
        data["e_elec_night_daily"] = night_daily

        # ------ Layer 7: status enums ------
        data["health"] = self._compute_health(data)
        data["efficiency_label"] = self._compute_efficiency_label(data)
        data["sanity_label"] = self._compute_sanity_label(data)
        what_state, what_attrs = self._compute_what_doing(data, rooms_data)
        data["what_doing"] = what_state
        data["what_doing_attrs"] = what_attrs

        # ------ Layer 8: FDD flags ------
        ap_smoothed = self._smooth_approach_outdoor.mean
        outdoor_coil_problem_cond = False
        if steady_state and not in_defrost and ap_smoothed is not None:
            if mode in ACTIVE_COOL_MODES:
                outdoor_coil_problem_cond = ap_smoothed > FDD_OUTDOOR_COIL_APPROACH_COOL_FAULT
            elif mode == MODE_HEAT:
                outdoor_coil_problem_cond = ap_smoothed > FDD_OUTDOOR_COIL_APPROACH_HEAT_FAULT
        data["fdd_outdoor_coil"] = self._fdd_outdoor_coil.update(
            outdoor_coil_problem_cond, now
        )

        # Outdoor coil 3-state status
        if not steady_state or ap_smoothed is None:
            data["outdoor_coil_status"] = "unknown"
        elif data["fdd_outdoor_coil"]:
            data["outdoor_coil_status"] = "needs_cleaning"
        elif (mode in ACTIVE_COOL_MODES and ap_smoothed > FDD_OUTDOOR_COIL_APPROACH_COOL_WARN) or (
            mode == MODE_HEAT and ap_smoothed > FDD_OUTDOOR_COIL_APPROACH_HEAT_WARN
        ):
            data["outdoor_coil_status"] = "possibly_dirty"
        else:
            data["outdoor_coil_status"] = "clean"

        # Per-room filters
        for name, r in rooms_data.items():
            ap_evap = r["approach_evap_smoothed"]
            t_coil = r["t_indoor_coil"]
            cond_filter = False
            if steady_state and mode in ACTIVE_COOL_MODES and r["fan_running"] and ap_evap is not None:
                high_dt = ap_evap > FDD_FILTER_APPROACH_FAULT
                frost = t_coil is not None and t_coil < FDD_FILTER_FROST_THRESHOLD
                cond_filter = high_dt or frost
            r["fdd_filter"] = self._fdd_filter[name].update(cond_filter, now)
            if not steady_state or ap_evap is None or mode not in ACTIVE_COOL_MODES:
                r["filter_status"] = "unknown"
            elif r["fdd_filter"]:
                r["filter_status"] = "needs_cleaning"
            elif ap_evap > FDD_FILTER_APPROACH_WARN:
                r["filter_status"] = "possibly_dirty"
            else:
                r["filter_status"] = "clean"

        # Refrigerant
        eff_smoothed = (
            data["eer_efficiency_smoothed"]
            if mode in ACTIVE_COOL_MODES
            else data["cop_efficiency_smoothed"]
        )
        eev_max_calib = self._opt(OPT_EEV_MAX, DEFAULT_EEV_MAX)
        max_eev_frac = max(
            (r["eev_raw"] / eev_max_calib for r in rooms_data.values() if eev_max_calib > 0),
            default=0.0,
        )

        refrig_cond = False
        if steady_state:
            if mode in ACTIVE_COOL_MODES:
                ap_evaps = [
                    r["approach_evap_smoothed"]
                    for r in rooms_data.values()
                    if r["approach_evap_smoothed"] is not None
                ]
                if ap_evaps:
                    ind1 = max(ap_evaps) > 18
                    ind2 = eff_smoothed is not None and eff_smoothed < FDD_REFRIGERANT_EFFICIENCY_THRESHOLD
                    ind3 = max_eev_frac > FDD_REFRIGERANT_EEV_THRESHOLD
                    refrig_cond = sum([ind1, ind2, ind3]) >= 2
            elif mode == MODE_HEAT:
                ind1 = ap_smoothed is not None and ap_smoothed > FDD_REFRIGERANT_APPROACH_HEAT
                ind2 = eff_smoothed is not None and eff_smoothed < FDD_REFRIGERANT_EFFICIENCY_THRESHOLD
                ind3 = max_eev_frac > FDD_REFRIGERANT_EEV_THRESHOLD
                refrig_cond = sum([ind1, ind2, ind3]) >= 2
        data["fdd_refrigerant"] = self._fdd_refrigerant.update(refrig_cond, now)
        data["refrigerant_status"] = (
            "leak_suspected" if data["fdd_refrigerant"]
            else "normal" if steady_state
            else "unknown"
        )

        # Cycling
        cycling_cond = self._cycling_tracker.starts_per_hour() > FDD_CYCLING_STARTS_PER_HOUR
        data["fdd_cycling"] = self._fdd_cycling.update(cycling_cond, now)

        # Excessive defrost
        excessive_defrost_cond = self._defrost_history.count_24h() > FDD_DEFROST_EXCESS_PER_24H
        data["fdd_excessive_defrost"] = self._fdd_excessive_defrost.update(
            excessive_defrost_cond, now
        )

        # Defrost status (3-state user-friendly)
        if mode != MODE_HEAT or t_outdoor is None or t_outdoor > 5:
            data["defrost_status_label"] = "unknown"
        elif data["fdd_excessive_defrost"]:
            data["defrost_status_label"] = "frequent"
        elif (
            self._defrost_history.count_24h() > 0
            and self._defrost_history.avg_duration_min() > FDD_DEFROST_LONG_MINUTES
        ):
            data["defrost_status_label"] = "long"
        else:
            data["defrost_status_label"] = "normal"

        # Maintenance days-since
        data["filter_days"] = {
            name: self._days_since(self.maintenance_data.get(f"filter_last_clean_{name}"))
            for name in rooms_data
        }
        data["outdoor_days"] = self._days_since(self.maintenance_data.get("outdoor_last_clean"))

        # ------ Layer 9: recommendations ------
        issues = self._build_issues(data)
        data["issues"] = issues
        data["severity"] = self._compute_severity(issues)
        data["top_message"] = self._top_message(issues)

        return data

    def _maybe_reset_periods(self, now: datetime) -> None:
        """Take energy snapshot at start of new day/month/year.

        Triggered by both the periodic coordinator update and an explicit
        midnight time-change listener (see __init__.py); idempotent.
        """
        local_now = dt_util.as_local(now)
        date_key = local_now.strftime("%Y-%m-%d")
        month_key = local_now.strftime("%Y-%m")
        year_key = local_now.strftime("%Y")

        if self._energy.last_daily_reset != date_key:
            self._energy.daily_snapshots = {
                "e_elec": self._energy.total_kwh,
                "e_elec_cool": self._energy.cool_total_kwh,
                "e_elec_heat": self._energy.heat_total_kwh,
                "q_cool": self._energy.q_cool_total_kwh,
                "q_heat": self._energy.q_heat_total_kwh,
                "q_room1": self._energy.q_room1_total_kwh,
                "q_room2": self._energy.q_room2_total_kwh,
            }
            self._energy.day_kwh_daily_snapshot = self._energy.day_kwh
            self._energy.night_kwh_daily_snapshot = self._energy.night_kwh
            self._energy.last_daily_reset = date_key

        if self._energy.last_monthly_reset != month_key:
            self._energy.monthly_snapshots = {
                "e_elec": self._energy.total_kwh,
                "e_elec_cool": self._energy.cool_total_kwh,
                "e_elec_heat": self._energy.heat_total_kwh,
                "q_cool": self._energy.q_cool_total_kwh,
                "q_heat": self._energy.q_heat_total_kwh,
                "q_room1": self._energy.q_room1_total_kwh,
                "q_room2": self._energy.q_room2_total_kwh,
            }
            self._energy.day_kwh_monthly_snapshot = self._energy.day_kwh
            self._energy.night_kwh_monthly_snapshot = self._energy.night_kwh
            self._energy.last_monthly_reset = month_key

        if self._energy.last_yearly_reset != year_key:
            self._energy.yearly_snapshots = {
                "e_elec": self._energy.total_kwh,
            }
            self._energy.day_kwh_yearly_snapshot = self._energy.day_kwh
            self._energy.night_kwh_yearly_snapshot = self._energy.night_kwh
            self._energy.last_yearly_reset = year_key

    def _days_since(self, iso_str: Optional[str]) -> int:
        """Return days since given ISO timestamp, or -1 if never set."""
        if not iso_str:
            return -1
        try:
            dt = dt_util.parse_datetime(iso_str)
            if dt is None:
                return -1
            return int((dt_util.utcnow() - dt).total_seconds() / 86400)
        except (ValueError, TypeError):
            return -1

    def _compute_health(self, data: dict) -> str:
        if not data["compressor_running"]:
            return HEALTH_IDLE
        if data["in_defrost"]:
            return HEALTH_DEFROSTING
        if not data["steady_state"]:
            return HEALTH_STARTING

        sanity = data["q_sanity_smoothed"]
        eff = (
            data["eer_efficiency_smoothed"]
            if data["mode"] in ACTIVE_COOL_MODES
            else data["cop_efficiency_smoothed"]
        )

        if sanity is None and eff is None:
            return HEALTH_UNKNOWN

        s_score = 4
        if sanity is not None:
            if SANITY_EXCELLENT_LOW <= sanity <= SANITY_EXCELLENT_HIGH:
                s_score = 4
            elif SANITY_GOOD_LOW <= sanity <= SANITY_GOOD_HIGH:
                s_score = 3
            elif SANITY_OK_LOW <= sanity <= SANITY_OK_HIGH:
                s_score = 2
            else:
                s_score = 1

        e_score = 4
        if eff is not None:
            if eff >= EFFICIENCY_EXCELLENT:
                e_score = 4
            elif eff >= EFFICIENCY_GOOD:
                e_score = 3
            elif eff >= EFFICIENCY_AVERAGE:
                e_score = 2
            else:
                e_score = 1

        worst = min(s_score, e_score)
        if worst >= 4:
            return HEALTH_EXCELLENT
        if worst == 3:
            return HEALTH_GOOD
        if worst == 2:
            return HEALTH_AVERAGE
        return HEALTH_PROBLEM

    def _compute_efficiency_label(self, data: dict) -> str:
        if not data["compressor_running"]:
            return "idle"
        if data["in_defrost"]:
            return "defrosting"
        if not data["steady_state"]:
            return "starting"

        eff = (
            data["eer_efficiency_smoothed"]
            if data["mode"] in ACTIVE_COOL_MODES
            else data["cop_efficiency_smoothed"]
        )
        if eff is None or eff == 0:
            return "unknown"
        if eff >= EFFICIENCY_EXCELLENT:
            return "excellent"
        if eff >= EFFICIENCY_GOOD:
            return "good"
        if eff >= EFFICIENCY_AVERAGE:
            return "average"
        return "low"

    def _compute_sanity_label(self, data: dict) -> str:
        r = data["q_sanity_smoothed"]
        if r is None or r == 0:
            return "unknown"
        if SANITY_EXCELLENT_LOW <= r <= SANITY_EXCELLENT_HIGH:
            return "normal"
        if SANITY_GOOD_LOW <= r < SANITY_EXCELLENT_LOW:
            return "slightly_low"
        if r < SANITY_GOOD_LOW:
            return "significantly_low"
        if SANITY_EXCELLENT_HIGH < r <= SANITY_GOOD_HIGH:
            return "slightly_high"
        return "significantly_high"

    def _compute_what_doing(self, data: dict, rooms: dict) -> tuple[str, dict]:
        """Return (state, attributes-with-active-rooms-list)."""
        attrs: dict = {}
        if data["mode"] == MODE_OFF:
            return "off", attrs
        if data["in_defrost"]:
            return "defrosting", attrs
        if data["compressor_running"] and not data["steady_state"]:
            return "starting", attrs

        any_fan = any(r["fan_running"] for r in rooms.values())
        if not data["compressor_running"] and not any_fan:
            return "off", attrs

        active_rooms = [name for name, r in rooms.items() if r["fan_running"]]
        attrs["active_rooms"] = active_rooms

        if data["mode"] in ACTIVE_COOL_MODES:
            verb = "drying" if data["mode"] == MODE_DRY else "cooling"
        elif data["mode"] == MODE_HEAT:
            verb = "heating"
        elif data["mode"] == MODE_FAN:
            return "fan_only", attrs
        elif data["mode"] == MODE_HEAT_COOL:
            return "auto", attrs
        else:
            return "idle", attrs

        # Use single base verb; rooms go into attributes
        if len(active_rooms) > 1:
            return f"{verb}_all", attrs
        return verb, attrs

    def _build_issues(self, data: dict) -> list[dict]:
        issues = []
        if data["fdd_refrigerant"]:
            issues.append({"code": "refrigerant_low", "severity": SEVERITY_FAULT})
        if data["fdd_outdoor_coil"]:
            issues.append({"code": "outdoor_coil_dirty", "severity": SEVERITY_WARN})
        for name, r in data["rooms"].items():
            if r.get("fdd_filter"):
                issues.append(
                    {"code": f"filter_{name}_dirty", "severity": SEVERITY_WARN}
                )
        if data["fdd_excessive_defrost"]:
            issues.append({"code": "excessive_defrost", "severity": SEVERITY_WARN})
        if data["fdd_cycling"]:
            issues.append({"code": "short_cycling", "severity": SEVERITY_INFO})
        # Filter / outdoor reminders
        for name, days in data["filter_days"].items():
            if days >= FILTER_CLEAN_REMINDER_DAYS:
                issues.append(
                    {
                        "code": f"filter_{name}_due",
                        "severity": SEVERITY_INFO,
                        "days": days,
                    }
                )
        if data["outdoor_days"] >= OUTDOOR_CLEAN_REMINDER_DAYS:
            issues.append(
                {
                    "code": "outdoor_clean_due",
                    "severity": SEVERITY_INFO,
                    "days": data["outdoor_days"],
                }
            )
        return issues

    def _compute_severity(self, issues: list[dict]) -> str:
        if not issues:
            return SEVERITY_OK
        if any(i["severity"] == SEVERITY_FAULT for i in issues):
            return SEVERITY_FAULT
        if any(i["severity"] == SEVERITY_WARN for i in issues):
            return SEVERITY_WARN
        return SEVERITY_INFO

    def _top_message(self, issues: list[dict]) -> str:
        """Return human-readable top message, or 'OK' if no issues."""
        if not issues:
            return "OK"
        # Sort by severity rank (fault > warn > info), preserve order
        rank = {SEVERITY_FAULT: 3, SEVERITY_WARN: 2, SEVERITY_INFO: 1}
        sorted_issues = sorted(issues, key=lambda i: -rank.get(i["severity"], 0))
        top = sorted_issues[0]
        return issue_message(top["code"], top.get("days"))
