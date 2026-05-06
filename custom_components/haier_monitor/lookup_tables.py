"""Lookup tables from Haier 2U50S2SM1FA-3 Service Manual V1 (2021-05-31).

All tables verified against first-party PDF.

Sections referenced:
    7.1.1.4 — f_max(T_outdoor)
    7.1.4   — outdoor fan RPM(T_outdoor, f_comp)
    7.1.5   — EEV control
    11.1    — cooling capacity at f_max
    11.2    — heating capacity at f_max
    11.3    — cooling power consumption at f_max
    11.4    — heating power consumption at f_max
"""
from __future__ import annotations


def f_max(t_outdoor: float, mode: str) -> float:
    """Maximum allowed compressor frequency at given T_outdoor (Hz).

    Service Manual section 7.1.1.4. Tables read as STEP FUNCTION by ranges,
    not as "minimum X where T<X". For T_outdoor=18°C heating: 16<=T<20 → 112 Hz.

    Args:
        t_outdoor: outdoor air temperature in °C
        mode: 'cool', 'dry', or 'heat'

    Returns:
        max frequency in Hz, or 0 if mode does not require compressor.
    """
    if mode in ("cool", "dry"):
        if t_outdoor < 16:
            return 37.0
        if t_outdoor < 23:
            return 45.0
        if t_outdoor < 29:
            return 56.0
        if t_outdoor < 32:
            return 63.0
        # T≥32: service manual gives 90 Hz as overshoot/protection limit
        # (normal range is 25-80 Hz per section 7.1.1.1)
        return 90.0
    if mode == "heat":
        if t_outdoor < 16:
            return 118.0
        if t_outdoor < 20:
            return 112.0
        return 102.0
    return 0.0


def f_min(mode: str) -> float:
    """Minimum compressor frequency (Hz)."""
    if mode in ("cool", "dry"):
        return 25.0
    if mode == "heat":
        return 30.0
    return 0.0


def outdoor_fan_rpm(t_outdoor: float, f_comp: float, mode: str) -> float:
    """Outdoor fan RPM after 3-minute startup (Service Manual section 7.1.4).

    Cooling matrix (T_outdoor rows × f_comp cols):
                f<40    40-60    >=60
        T<23    500     600      700
        T 23-29 600     700      850
        T 29-40 850     900      900
        T>=40   900     900      900

    Heating matrix:
                f<60    60-90    >=90
        T<10    800     900      900
        T 10-16 700     800      850
        T>=16   700     700      700  (700 for all f)
    """
    if mode in ("cool", "dry"):
        if t_outdoor < 23:
            if f_comp < 40:
                return 500
            if f_comp < 60:
                return 600
            return 700
        if t_outdoor < 29:
            if f_comp < 40:
                return 600
            if f_comp < 60:
                return 700
            return 850
        if t_outdoor < 40:
            if f_comp < 40:
                return 850
            return 900
        return 900
    if mode == "heat":
        if t_outdoor < 10:
            if f_comp < 60:
                return 800
            return 900
        if t_outdoor < 16:
            if f_comp < 60:
                return 700
            if f_comp < 90:
                return 800
            return 850
        return 700
    return 0


def outdoor_airflow(rpm: float) -> float:
    """Outdoor airflow (m³/h) from fan RPM via affinity law.

    Service manual section 2: 2900 m³/h at 950 RPM (high speed).
    Linear scaling correct for clean coil; degradation accounted for elsewhere.
    """
    return 2900.0 * rpm / 950.0


def p_max_table(t_outdoor: float, t_indoor: float, mode: str) -> float:
    """Maximum compressor power consumption at f_max(T_outdoor) (W).

    Service Manual section 11.3 (cooling) at Tin=27/19, 11.4 (heating) at Tin=20.
    Nearest-neighbor selection by midpoint between table points.
    Linear T_indoor correction: × (1 + 0.02 × (Tin − reference)).
    """
    if mode in ("cool", "dry"):
        # Cooling table at Tin=27/19; points 18,20,25,32,35,40,43,46
        if t_outdoor < 19:
            p = 536.0
        elif t_outdoor < 23:
            p = 527.0
        elif t_outdoor < 29:
            p = 968.0
        elif t_outdoor < 34:
            p = 1044.0
        elif t_outdoor < 38:
            p = 1643.0
        elif t_outdoor < 42:
            p = 1726.0
        elif t_outdoor < 45:
            p = 1826.0
        else:
            p = 701.0
        return p * (1 + 0.02 * (t_indoor - 27))

    if mode == "heat":
        # Heating table at Tin=20; points -15,-5,5,7,15,20,25
        if t_outdoor < -10:
            p = 1495.0
        elif t_outdoor < 0:
            p = 1644.0
        elif t_outdoor < 6:
            p = 2135.0
        elif t_outdoor < 11:
            p = 1668.0
        elif t_outdoor < 18:
            p = 771.0
        elif t_outdoor < 23:
            p = 483.0
        else:
            p = 488.0
        return p * (1 + 0.02 * (t_indoor - 20))

    return 0.0


def q_max_table(t_outdoor: float, t_indoor: float, mode: str) -> float:
    """Maximum cooling/heating capacity at f_max(T_outdoor) (W).

    Service Manual section 11.1 (cooling) / 11.2 (heating).
    Same structure as p_max_table.
    """
    if mode in ("cool", "dry"):
        if t_outdoor < 19:
            q = 3647.0
        elif t_outdoor < 23:
            q = 3516.0
        elif t_outdoor < 29:
            q = 4616.0
        elif t_outdoor < 34:
            q = 4401.0
        elif t_outdoor < 38:
            q = 5250.0
        elif t_outdoor < 42:
            q = 4982.0
        elif t_outdoor < 45:
            q = 4768.0
        else:
            q = 3379.0
        return q * (1 + 0.015 * (t_indoor - 27))

    if mode == "heat":
        if t_outdoor < -10:
            q = 2736.0
        elif t_outdoor < 0:
            q = 5187.0
        elif t_outdoor < 6:
            q = 6570.0
        elif t_outdoor < 11:
            q = 6120.0
        elif t_outdoor < 18:
            q = 4860.0
        elif t_outdoor < 23:
            q = 4522.0
        else:
            q = 4678.0
        return q * (1 + 0.015 * (t_indoor - 20))

    return 0.0
