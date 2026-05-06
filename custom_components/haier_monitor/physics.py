"""Pure-Python physics calculations for Haier Multi-Split Monitor.

Functions are framework-agnostic — no Home Assistant dependencies.
This makes them testable in isolation.

References:
    - ASHRAE Fundamentals 2021 (psychrometrics)
    - Cuevas & Lebrun (2009) Applied Thermal Engineering — variable-speed scroll
    - Yu et al. (2023) Buildings (MDPI) — Outdoor Air Enthalpy Method
    - Service Manual 2U50S2SM1FA-3 V1 (lookup tables)
"""
from __future__ import annotations

import math
from typing import Optional

from .const import (
    AIR_VOLUMETRIC_FACTOR,
    ACTIVE_COOL_MODES,
    MODE_HEAT,
)


# ---------------------------------------------------------------------------
# Idle power model (state-dependent)
# ---------------------------------------------------------------------------
def idle_power(
    t_outdoor: Optional[float],
    mode: str,
    compressor_running: bool,
    indoor_fans_running_count: int,
    outdoor_fan_running: bool,
    idle_base: float,
    idle_indoor_fan: float,
    idle_outdoor_fan: float,
    idle_crankcase: float,
) -> float:
    """Compute idle (non-compressor) power consumption.

    Returns watts. Range typically 8-150 W depending on conditions.
    """
    p = idle_base
    if indoor_fans_running_count > 0:
        p += idle_indoor_fan * indoor_fans_running_count
    if outdoor_fan_running:
        p += idle_outdoor_fan
    # Crankcase heater heuristic (only when cold AND heat mode AND compressor off)
    if (
        mode == MODE_HEAT
        and not compressor_running
        and t_outdoor is not None
        and t_outdoor < 5
    ):
        p += idle_crankcase + max(0.0, (5.0 - t_outdoor) * 3.0)
    return p


# ---------------------------------------------------------------------------
# P_elec (electric power) — improved linear+quadratic model
# ---------------------------------------------------------------------------
def p_elec_modeled(
    p_idle: float,
    f_comp: Optional[float],
    f_max: float,
    p_max: float,
    compressor_running: bool,
) -> float:
    """Compute modeled electric power consumption (W).

    Formula:
        P = P_idle + P_max × (f / f_max) × [1 + γ × (f_norm − 0.6)²]
        γ = 0.15 (Cuevas-style quadratic correction)

    The quadratic term captures the increased losses at extreme frequencies
    (friction at low f, inverter switching losses at high f).
    """
    if not compressor_running or f_comp is None or f_max <= 0 or p_max <= 0:
        return p_idle
    f_norm = f_comp / f_max
    quadratic = 1 + 0.15 * (f_norm - 0.6) ** 2
    return p_idle + p_max * f_norm * quadratic


def p_elec_best(
    p_native: Optional[float], p_modeled: float
) -> tuple[float, str]:
    """Choose between native ESPHome power and modeled. Returns (value, source)."""
    if p_native is not None and p_native > 0:
        return p_native, "native"
    return p_modeled, "model"


# ---------------------------------------------------------------------------
# Q_outdoor — heat flow through outdoor coil via air-side balance
# ---------------------------------------------------------------------------
def q_outdoor_air(
    airflow_m3h: float,
    delta_t_c: float,
    offset: float = 0.0,
) -> float:
    """Heat flow through outdoor coil via air enthalpy difference (W).

    Q [W] = ρ × V × cp × ΔT = 0.3424 × V[m³/h] × ΔT[K]

    Sign: cool → Q > 0 (coil rejects heat); heat → Q < 0 (coil absorbs).
    """
    return AIR_VOLUMETRIC_FACTOR * airflow_m3h * (delta_t_c - offset)


# ---------------------------------------------------------------------------
# Q_indoor — energy balance + pipe loss correction
# ---------------------------------------------------------------------------
def q_indoor_total(
    q_outdoor: float,
    p_elec: float,
    p_idle: float,
    mode: str,
    pipe_length: float,
    in_defrost: bool,
    steady_state: bool,
) -> float:
    """Heat delivered to / removed from rooms (W).

    Cool: Q_indoor = (Q_outdoor − W_comp) × (1 − k_pipe_cool)
    Heat: Q_indoor = (|Q_outdoor| + W_comp) × (1 − k_pipe_heat)
    where W_comp = P_elec − P_idle and k_pipe = 0.005×L (cool) / 0.01×L (heat).

    Returns 0 during defrost or non-steady-state (forced gating).
    """
    if in_defrost or not steady_state:
        return 0.0
    w_comp = max(0.0, p_elec - p_idle)
    if mode in ACTIVE_COOL_MODES:
        k_pipe = 0.005 * pipe_length
        return max(0.0, (q_outdoor - w_comp) * (1.0 - k_pipe))
    if mode == MODE_HEAT:
        k_pipe = 0.01 * pipe_length
        return max(0.0, (abs(q_outdoor) + w_comp) * (1.0 - k_pipe))
    return 0.0


# ---------------------------------------------------------------------------
# Dewpoint via Magnus formula (±0.4K accuracy, -40..+50°C range)
# ---------------------------------------------------------------------------
def dewpoint(t_c: float, rh_pct: float) -> float:
    """Compute dewpoint (°C) using Magnus formula.

    γ = ln(RH/100) + (17.625·T) / (243.04 + T)
    T_dp = 243.04·γ / (17.625 − γ)
    """
    rh = max(1.0, min(100.0, rh_pct))
    gamma = math.log(rh / 100.0) + (17.625 * t_c) / (243.04 + t_c)
    return 243.04 * gamma / (17.625 - gamma)


def is_condensation_active(
    t_indoor_coil: Optional[float],
    t_dewpoint: Optional[float],
    fan_running: bool,
    mode: str,
) -> bool:
    """True if coil is below dewpoint → condensation (latent removal) occurs."""
    if mode not in ACTIVE_COOL_MODES:
        return False
    if not fan_running:
        return False
    if t_indoor_coil is None or t_dewpoint is None:
        return False
    return t_indoor_coil < (t_dewpoint - 0.5)


# ---------------------------------------------------------------------------
# Sensible / Latent split via bypass factor model
# ---------------------------------------------------------------------------
def q_sensible_per_room(
    t_room: Optional[float],
    t_indoor_coil: Optional[float],
    fan_running: bool,
    indoor_airflow_m3h: float,
    bypass_factor: float,
    mode: str,
) -> float:
    """Sensible heat removed/delivered to one room (W).

    Bypass factor model: T_supply ≈ T_coil + BF × (T_room − T_coil).
    Q_sens = 0.34 × V × (T_room − T_supply) = 0.34 × V × (T_room − T_coil) × (1−BF)

    Heating: assumed all sensible (no condensation on hot coil).
    """
    if not fan_running or t_room is None or t_indoor_coil is None:
        return 0.0
    if mode == MODE_HEAT:
        # In heating, coil hot, ΔT inverted; sensible heat going INTO room
        delta_t = max(0.0, t_indoor_coil - t_room)
        return AIR_VOLUMETRIC_FACTOR * indoor_airflow_m3h * delta_t * (1 - bypass_factor)
    if mode in ACTIVE_COOL_MODES:
        delta_t = max(0.0, t_room - t_indoor_coil)
        return AIR_VOLUMETRIC_FACTOR * indoor_airflow_m3h * delta_t * (1 - bypass_factor)
    return 0.0


# ---------------------------------------------------------------------------
# Per-room distribution via capacity-weighted EEV opening
# ---------------------------------------------------------------------------
def room_share(
    eev_raw: float,
    eev_idle: float,
    rated_capacity: float,
    rated_capacity_max: float,
    fan_running: bool,
) -> float:
    """Mass flow proxy for one room (relative units).

    proxy = (EEV_raw − EEV_idle) × √(rated_capacity / max_capacity)
    Returns 0 if fan off (fan-off blocks force ratio to other rooms).
    """
    if not fan_running:
        return 0.0
    eev_eff = max(0.0, eev_raw - eev_idle)
    if rated_capacity_max <= 0:
        return 0.0
    return eev_eff * math.sqrt(rated_capacity / rated_capacity_max)


def normalize_shares(proxies: list[float]) -> list[float]:
    """Convert raw mass-flow proxies into shares summing to 1.0."""
    total = sum(proxies)
    if total <= 0:
        return [0.0] * len(proxies)
    return [p / total for p in proxies]


# ---------------------------------------------------------------------------
# Approach temperatures (for FDD)
# ---------------------------------------------------------------------------
def approach_outdoor(
    t_coil: Optional[float], t_air: Optional[float], mode: str
) -> Optional[float]:
    """Outdoor coil approach temperature.

    Cool (condenser): T_outdoor_coil − T_outdoor_air — 8-15K healthy, >18K fouled.
    Heat (evaporator): T_outdoor_air − T_outdoor_coil — 4-8K healthy, >12K fouled.
    """
    if t_coil is None or t_air is None:
        return None
    if mode in ACTIVE_COOL_MODES:
        return t_coil - t_air
    if mode == MODE_HEAT:
        return t_air - t_coil
    return None


def approach_evap_indoor(
    t_room: Optional[float], t_indoor_coil: Optional[float], mode: str
) -> Optional[float]:
    """Indoor coil approach.

    Cool (evaporator): T_room − T_indoor_coil — 8-14K healthy, >16K reduced airflow.
    Heat (condenser): T_indoor_coil − T_room.
    """
    if t_room is None or t_indoor_coil is None:
        return None
    if mode in ACTIVE_COOL_MODES:
        return t_room - t_indoor_coil
    if mode == MODE_HEAT:
        return t_indoor_coil - t_room
    return None


# ---------------------------------------------------------------------------
# Carnot-derived expected COP/EER
# ---------------------------------------------------------------------------
def expected_cop_carnot(
    t_outdoor_coil: Optional[float],
    t_indoor_coil: Optional[float],
    eta_carnot: float,
    mode: str,
) -> Optional[float]:
    """Expected COP from Carnot cycle × machine efficiency.

    Cool: COP = η × T_evap_K / (T_cond − T_evap)
    Heat: COP = η × T_cond_K / (T_cond − T_evap)
    """
    if t_outdoor_coil is None or t_indoor_coil is None:
        return None
    if mode in ACTIVE_COOL_MODES:
        # Outdoor coil = condenser, indoor coil = evaporator
        delta_t = (t_outdoor_coil + 273.15) - (t_indoor_coil + 273.15)
        if delta_t < 1:
            return None
        return eta_carnot * (t_indoor_coil + 273.15) / delta_t
    if mode == MODE_HEAT:
        # Indoor coil = condenser, outdoor coil = evaporator
        delta_t = (t_indoor_coil + 273.15) - (t_outdoor_coil + 273.15)
        if delta_t < 1:
            return None
        return eta_carnot * (t_indoor_coil + 273.15) / delta_t
    return None


# ---------------------------------------------------------------------------
# Defrost detection (multi-indicator voting)
# ---------------------------------------------------------------------------
def is_defrost(
    mode: str,
    compressor_running: bool,
    t_outdoor: Optional[float],
    t_outdoor_coil: Optional[float],
    t_defrost: Optional[float],
    delta_t_air: Optional[float],
    native_defrost_status: Optional[bool],
) -> bool:
    """Multi-indicator defrost detection.

    Native ESPHome defrost_status takes precedence (returns True immediately).
    Otherwise: 2-of-3 voting between coil-hot, defrost-sensor-warm, reverse-flow.
    """
    if not compressor_running or mode != MODE_HEAT:
        return False
    if native_defrost_status is True:
        return True
    if t_outdoor is None or t_outdoor_coil is None:
        return False

    indicators = 0
    # Indicator 1: outdoor coil hotter than outdoor air by 5°C+ in cold weather
    if t_outdoor < 8 and t_outdoor_coil > (t_outdoor + 5):
        indicators += 1
    # Indicator 2: defrost sensor warm (heater pulled coil up)
    if t_defrost is not None and t_defrost > 7:
        indicators += 1
    # Indicator 3: reverse heat flow (heat normally has Q_outdoor<0; positive ΔT → reversal)
    if delta_t_air is not None and delta_t_air > 0.5:
        indicators += 1

    return indicators >= 2


# ---------------------------------------------------------------------------
# Energy class boundaries (EU label) lookup
# ---------------------------------------------------------------------------
def energy_class(value: Optional[float], boundaries: list[tuple[float, str]]) -> str:
    """Map SEER/SCOP to A+++..C class string."""
    if value is None:
        return "unknown"
    for threshold, label in boundaries:
        if value >= threshold:
            return label
    return "unknown"
