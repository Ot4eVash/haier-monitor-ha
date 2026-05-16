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
# Q_indoor — three-method estimator with sanity-based selection
# ---------------------------------------------------------------------------
def q_indoor_outdoor_air(
    q_outdoor: float,
    p_elec: float,
    p_idle: float,
    mode: str,
    pipe_length: float,
) -> float:
    """Method 2 — outdoor air enthalpy balance (Yu et al. 2023, ±8%).

    Cool: Q_indoor = (Q_outdoor − W_comp) × (1 − k_pipe_cool)
    Heat: Q_indoor = (|Q_outdoor| + W_comp) × (1 − k_pipe_heat)

    Caller must verify the outdoor air sensors actually report air (not
    refrigerant pipe temperatures, as happens on hOn multi-split units).
    """
    w_comp = max(0.0, p_elec - p_idle)
    if mode in ACTIVE_COOL_MODES:
        k_pipe = 0.005 * pipe_length
        return max(0.0, (q_outdoor - w_comp) * (1.0 - k_pipe))
    if mode == MODE_HEAT:
        k_pipe = 0.01 * pipe_length
        return max(0.0, (abs(q_outdoor) + w_comp) * (1.0 - k_pipe))
    return 0.0


def q_indoor_from_rooms(
    rooms: list[dict],
    indoor_airflow_m3h: float,
    bypass_factor: float,
    mode: str,
) -> float:
    """Method 1 — indoor coil enthalpy summation across active rooms (PRIMARY).

    For each running indoor unit with a valid coil temperature and room
    temperature, accumulates the sensible heat flow through the coil:
        Q_room = ρ·Cp·V·|T_room − T_coil|·(1 − BF)
    Returns total across rooms in watts. Robust on multi-split hOn where
    outdoor air sensors are unreliable, since indoor coil temperatures and
    room temperatures come from independent reliable sources.
    """
    if mode not in ACTIVE_COOL_MODES and mode != MODE_HEAT:
        return 0.0
    total = 0.0
    for r in rooms:
        if not r.get("fan_running"):
            continue
        t_room = r.get("t_room")
        t_coil = r.get("t_indoor_coil")
        if t_room is None or t_coil is None:
            continue
        if mode in ACTIVE_COOL_MODES:
            delta_t = max(0.0, t_room - t_coil)
        else:
            delta_t = max(0.0, t_coil - t_room)
        total += AIR_VOLUMETRIC_FACTOR * indoor_airflow_m3h * delta_t * (1 - bypass_factor)
    return total


def q_indoor_carnot(
    p_elec: float,
    p_idle: float,
    t_indoor_coil: Optional[float],
    t_outdoor_coil: Optional[float],
    eta_carnot: float,
    mode: str,
) -> float:
    """Method 3 — Carnot-cycle bound (fallback when air & room data unreliable).

    Q = η·COP_carnot·W_comp where COP_carnot uses coil temperatures:
        Cool: COP = T_evap / (T_cond − T_evap),  T_evap = indoor coil
        Heat: COP = T_cond / (T_cond − T_evap),  T_cond = indoor coil
    Returns watts.
    """
    if t_indoor_coil is None or t_outdoor_coil is None:
        return 0.0
    w_comp = max(0.0, p_elec - p_idle)
    if w_comp < 30:
        return 0.0
    t_i_k = t_indoor_coil + 273.15
    t_o_k = t_outdoor_coil + 273.15
    if mode in ACTIVE_COOL_MODES:
        # Outdoor coil hot, indoor coil cold
        delta = t_o_k - t_i_k
        if delta < 1:
            return 0.0
        cop = eta_carnot * t_i_k / delta
    elif mode == MODE_HEAT:
        # Indoor coil hot, outdoor coil cold
        delta = t_i_k - t_o_k
        if delta < 1:
            return 0.0
        cop = eta_carnot * t_i_k / delta
    else:
        return 0.0
    return max(0.0, w_comp * cop)


def outdoor_air_sensors_valid(
    t_in_air: Optional[float],
    t_out_air: Optional[float],
    t_outdoor: Optional[float],
    air_dt: Optional[float],
    valid_t_air_max: float,
    valid_t_air_min: float,
    valid_air_dt_max: float,
    valid_air_offset_max: float,
) -> bool:
    """Decide if the outdoor air-in/out pair carries real air temperatures.

    Multi-split hOn outdoor units often publish these fields with
    refrigerant-pipe temperatures instead of air — the values then differ
    from the ambient outdoor temperature by tens of K and the air-side
    energy balance overestimates Q by 5-15×. We reject the readings if any
    of these physical bounds are violated.
    """
    if t_in_air is None or t_out_air is None or air_dt is None:
        return False
    if t_out_air > valid_t_air_max or t_in_air < valid_t_air_min:
        return False
    if abs(air_dt) > valid_air_dt_max:
        return False
    if t_outdoor is not None:
        if abs(t_in_air - t_outdoor) > valid_air_offset_max:
            return False
        if abs(t_out_air - t_outdoor) > valid_air_offset_max:
            return False
    return True


def q_indoor_total(
    rooms: list[dict],
    q_outdoor: float,
    p_elec: float,
    p_idle: float,
    mode: str,
    pipe_length: float,
    in_defrost: bool,
    steady_state: bool,
    indoor_airflow_m3h: float,
    bypass_factor: float,
    t_indoor_coil_avg: Optional[float],
    t_outdoor_coil: Optional[float],
    eta_carnot: float,
    method_preference: str,
    outdoor_air_valid: bool,
) -> tuple[float, str]:
    """Compute Q_indoor with method selection.

    Returns (q_watts, method_used). Method is one of:
        'indoor'        — Method 1, indoor coil enthalpy (preferred)
        'outdoor_air'   — Method 2, outdoor air enthalpy (legacy, requires
                          sanity-validated outdoor air sensors)
        'carnot'        — Method 3, Carnot-bounded estimate
        'none'          — gated to 0 (defrost / non-steady / no data)

    Preference:
        'auto'          — try indoor → outdoor_air (if sane) → carnot
        'indoor'        — only indoor; 0 if room data missing
        'outdoor_air'   — only outdoor air; 0 if rejected by sanity check
        'carnot'        — only carnot
    """
    if in_defrost or not steady_state:
        return 0.0, "none"

    def try_indoor() -> Optional[float]:
        q = q_indoor_from_rooms(rooms, indoor_airflow_m3h, bypass_factor, mode)
        return q if q > 50 else None

    def try_outdoor_air() -> Optional[float]:
        if not outdoor_air_valid:
            return None
        q = q_indoor_outdoor_air(q_outdoor, p_elec, p_idle, mode, pipe_length)
        return q if q > 50 else None

    def try_carnot() -> Optional[float]:
        q = q_indoor_carnot(p_elec, p_idle, t_indoor_coil_avg, t_outdoor_coil, eta_carnot, mode)
        return q if q > 50 else None

    if method_preference == "indoor":
        q = try_indoor()
        return (q, "indoor") if q is not None else (0.0, "none")
    if method_preference == "outdoor_air":
        q = try_outdoor_air()
        return (q, "outdoor_air") if q is not None else (0.0, "none")
    if method_preference == "carnot":
        q = try_carnot()
        return (q, "carnot") if q is not None else (0.0, "none")
    # 'auto'
    q = try_indoor()
    if q is not None:
        return q, "indoor"
    q = try_outdoor_air()
    if q is not None:
        return q, "outdoor_air"
    q = try_carnot()
    if q is not None:
        return q, "carnot"
    return 0.0, "none"


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
# Defrost detection — 1.2: hard gating to suppress false positives
# ---------------------------------------------------------------------------
def is_defrost(
    mode: str,
    compressor_running: bool,
    t_outdoor: Optional[float],
    t_outdoor_coil: Optional[float],
    t_defrost: Optional[float],
    delta_t_air: Optional[float],
    native_defrost_status: Optional[bool],
    compressor_uptime_min: float,
    max_outdoor_t: float,
    min_uptime_sec: int,
    outdoor_air_valid: bool,
) -> bool:
    """Detect a real defrost cycle, rejecting transient artifacts.

    Hard gates (any fail → False):
      • mode must be heat
      • compressor must be running for at least `min_uptime_sec`
      • outdoor air temperature must be below `max_outdoor_t` (defrost is
        physically impossible above ~5°C)

    Decision (after gates pass):
      • Native ESPHome defrost_status, if configured, is authoritative.
      • Otherwise: outdoor coil must be ABOVE outdoor air by ≥5K (the
        reverse-cycle heating signature). The previous indicators based
        on a separate defrost-T sensor and air-ΔT direction are dropped
        because:
          – ESPHome paveldn/haier-esphome#87 makes outdoor_defrost_temperature
            mirror outdoor_coil_temperature, so it adds no independent info;
          – outdoor air ΔT is meaningless on multi-split where those fields
            carry refrigerant pipe temperatures (`outdoor_air_valid=False`).
    """
    if mode != MODE_HEAT or not compressor_running:
        return False
    if compressor_uptime_min * 60 < min_uptime_sec:
        return False
    if t_outdoor is None or t_outdoor >= max_outdoor_t:
        return False
    if native_defrost_status is True:
        return True
    if native_defrost_status is False:
        # Explicit native value False — trust it over heuristics
        return False
    if t_outdoor_coil is None:
        return False
    # Coil markedly warmer than outdoor air (reverse-cycle signature)
    if t_outdoor_coil > t_outdoor + 5:
        # Optional confirmation by air ΔT only if the air sensors are
        # validated as real air (not pipe-T on multi-split)
        if outdoor_air_valid and delta_t_air is not None and delta_t_air > 0.5:
            return True
        # Without independent confirmation require larger margin to fire
        return t_outdoor_coil > t_outdoor + 10
    return False


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
