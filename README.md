# Haier Multi-Split Monitor for Home Assistant

Custom integration for monitoring Haier 2U50S2SM1FA-3 multi-split inverter system (R32) via ESPHome integration `paveldn/haier-esphome`. Computes electric power, heat output, COP/EER/SEER/SCOP, per-room distribution, plus user-friendly statuses and actionable maintenance recommendations — all without an external power meter.

Target accuracy: **±5-10%** for COP/SCOP with native ESPHome power sensor, **±10-15%** without. Backed by first-party Service Manual V1 (2021) and peer-reviewed literature.

## Features

- **80+ entities**: from raw aggregates to actionable recommendations
- **Word-based statuses**: `health` (excellent/good/average/problem), `efficiency_label`, `what_doing` (cooling kitchen / heating all rooms / defrosting / etc.)
- **FDD-style diagnostics**: outdoor coil cleanness, per-room filter status, refrigerant leak detection, defrost frequency analysis — all with persistence windows to avoid false positives
- **Recommendation aggregator**: severity (ok/info/warn/fault) + ranked actionable issues, ready for Telegram notifications
- **Energy dashboard ready**: HA-compatible `total_increasing` energy sensors with daily/monthly/yearly periods
- **Per-room distribution**: capacity-weighted EEV opening + sensible/latent split via bypass factor model + dewpoint detection
- **Native sensor priority**: if ESPHome exposes native power/defrost/coil temp, the integration uses them automatically as ground truth
- **Two indoor units** (currently fixed; default room names "Кухня" / "Спальня", but you can rename in setup wizard). Multi-room dynamic support is planned.

## Installation

### Via HACS (recommended)

1. In HACS, add this repository as a Custom Repository (category: Integration):
   ```
   https://github.com/sppbfilatov/haier-monitor-ha
   ```
2. Install "Haier Multi-Split Monitor" from HACS.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → Haier Multi-Split Monitor**.

### Manual

1. Download this repository as ZIP.
2. Copy `custom_components/haier_monitor/` to your HA `config/custom_components/` directory.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → Haier Multi-Split Monitor**.

## Configuration

The setup wizard walks you through 4 steps:

1. **Integration name** — pick anything (default "Haier Monitor").
2. **First indoor unit** (default name "Кухня" — you can change):
   - Climate entity (`climate.ac_kitchen_haier_hon_climate` etc.)
   - Indoor fan status (binary)
   - EEV opening sensor
   - Optional: room temperature, room humidity (recommended for sensible/latent split), indoor coil temperature (native ESPHome)
   - Rated capacity (W) — important for asymmetric pairs (e.g. AS25 + AS35)
3. **Second indoor unit** (default "Спальня") — same fields.
4. **Outdoor sensors** — link the shared outdoor-side sensors (each indoor unit reports its own copy; integration averages with fallback):
   - Outdoor temperature, coil temperature, defrost sensor, air-in/out temperatures
   - Compressor frequency, compressor status (binary)
   - Optional: native power, compressor current, native defrost status, outdoor fan status

After setup, the integration creates all sensors in one device. Status sensors are enabled by default; technical sensors are disabled (visible in the device page if you want).

## Calibration

Calibration parameters are exposed as **Number** entities (Settings → Devices & Services → Haier Monitor → device page → "Configuration" section).

### Critical: check EEV scale immediately

Look at your raw `expansion_valve_open_degree` sensor in HA after the AC has been off for 5+ minutes (idle, cool mode):

- **~0.001-0.05** → `paveldn/haier-esphome` master fraction publication (default since v1.1). Leave defaults.
- **~5-10** → legacy "raw steps" publication (e.g., older ESPHome versions or other forks). Set `Calibration: EEV max` = 500, `EEV idle cool` = 5, `EEV idle heat` = 80.
- **~40-100** → some firmware variants publish raw 12-bit code without dividing. Set `Calibration: EEV max` = 4095, `EEV idle cool` = 42, `EEV idle heat` = 683.

If left misconfigured, per-room heat distribution (`q_room`) collapses to 0 for every room and the EEV-based refrigerant-leak indicator stops voting.

### Recommended after 1-2 weeks of operation

| Number entity | Meaning | Default (1.1) |
|---|---|---|
| `Calibration: EEV max` | Full-open value of the EEV sensor | 1.0 (fraction) |
| `Calibration: EEV idle (cool/dry)` | EEV bleed-through in cool mode | 0.001 |
| `Calibration: EEV idle (heat)` | EEV bleed-through in heat mode | 0.16 |
| `Calibration: pipe length` | Total refrigerant pipe length (m) | 5 |
| `Calibration: η Carnot (cool/heat)` | Machine efficiency vs Carnot ideal | 0.40 / 0.45 |
| `Calibration: idle base PCB` | Base power: PCB + sensor bias | 8 W |
| `Calibration: idle indoor fan` | Power per running IU fan | 12 W |
| `Calibration: idle outdoor fan` | OU fan minimum draw | 50 W |
| `Calibration: crankcase heater` | Crankcase heater base (T<+5°C) | 30 W |
| `Calibration: outdoor ΔT offset` | Sensor offset for outdoor air ΔT | 0 |
| `Calibration: bypass factor` | Indoor coil bypass for sensible/latent split | 0.15 |
| `Calibration: indoor airflow nominal` | Mid-speed airflow per IU (m³/h) | 900 |
| `Calibration: day tariff` | Day electricity rate (currency/kWh) | 8.11 (RUB) |
| `Calibration: night tariff` | Night electricity rate | 3.49 (RUB) |

## Main entities for dashboard

### The 5 you actually need

| Entity | Values | What it tells you |
|---|---|---|
| `sensor.<name>_what_doing` | "Cooling kitchen", "Heating all rooms", "Defrosting", etc. | Plain English what's happening now |
| `sensor.<name>_health` | excellent / good / average / problem | Overall traffic light |
| `sensor.<name>_efficiency_label` | excellent / good / average / low | Performance vs paspart at current weather |
| `sensor.<name>_recommendation_top` | "Clean outdoor unit", "Replace kitchen filter", "OK" | Single most important actionable message |
| `sensor.<name>_p_elec` | watts | Real-time power consumption |

### Energy dashboard

Add to **Settings → Dashboards → Energy → Individual devices**:
- `sensor.<name>_e_elec_total` (overall consumption)
- Optional: `sensor.<name>_e_elec_cool_total` and `sensor.<name>_e_elec_heat_total` for cooling/heating split

### Diagnostics

| Entity | Values |
|---|---|
| `sensor.<name>_outdoor_coil_status` | clean / possibly_dirty / needs_cleaning |
| `sensor.<name>_<room>_filter` | clean / possibly_dirty / needs_cleaning |
| `sensor.<name>_refrigerant_status` | normal / leak_suspected |
| `sensor.<name>_defrost_status_label` | normal / frequent / long |

### Maintenance buttons

`button.<name>_<room>_filter_mark_cleaned` / `button.<name>_outdoor_coil_mark_cleaned` — press after physical cleaning, the days-since counter resets and reminders disappear until next interval (90 days for filters, 365 for outdoor coil).

## Notification automation example

```yaml
automation:
  - alias: "Haier — alert on new warning/fault"
    triggers:
      - trigger: state
        entity_id: sensor.haier_monitor_recommendation_severity
        to: ["warn", "fault"]
        for: "00:10:00"
    conditions:
      - condition: template
        value_template: >
          {% set rank = {'ok': 0, 'info': 1, 'warn': 2, 'fault': 3} %}
          {{ rank.get(trigger.to_state.state, 0)
             > rank.get(trigger.from_state.state, 0) }}
    actions:
      - action: notify.telegram
        data:
          message: >
            🔧 Haier: {{ states('sensor.haier_monitor_recommendation_top') }}
```

## How accurate is this?

| Metric | Without native sensors | With native sensors |
|---|---|---|
| P_elec (instant) | ±15% | ±5% |
| Q_indoor_total | ±10% | ±10% |
| COP/EER (instant) | ±15-20% | ±10% |
| SEER/SCOP (seasonal, after weeks) | ±10-15% | ±5-10% |
| Per-room split | ±8-15% | ±8-15% |

Sources of accuracy:
- Q calculated via outdoor air enthalpy difference is the main "ground truth" channel (Yu et al. 2023 reports ±7% lab error).
- P_elec is the weakest link without native sensors — enable native power in ESPHome (one line in YAML) for huge improvement.
- Sanity ratio (`q_sanity_smoothed`) cross-checks the model continuously: stable values 0.85-1.15 confirm both channels agree.

## Enabling native ESPHome sensors

In your ESPHome device YAML, add these to your `haier:` block (one per indoor unit):

```yaml
sensor:
  - platform: haier
    haier_id: my_haier_kitchen
    power:
      name: "AC Kitchen Power"
    compressor_current:
      name: "AC Kitchen Compressor Current"
    indoor_coil_temperature:
      name: "AC Kitchen Indoor Coil Temp"
binary_sensor:
  - platform: haier
    haier_id: my_haier_kitchen
    defrost_status:
      name: "AC Kitchen Defrost Status"
    outdoor_fan_status:
      name: "AC Kitchen Outdoor Fan Status"
```

After re-flash, link them in the integration's options flow ("Re-link outdoor sensors").

## Limitations

- **Configured for fixed two-component multi-split**: 1 outdoor unit + N indoor units (tested with 2). The integration assumes one shared compressor — won't work for VRF or independent split systems.
- **Tables hardcoded for 2U50S2SM1FA-3 R32**: if you have a different Haier model, the lookup tables (P_max, Q_max, f_max, fan RPM) won't match. Pull request welcome to add other models.
- **Not for fault diagnosis of compressor electronics**: the FDD layer covers refrigerant/airflow/heat-exchange faults. Inverter faults, communication errors, etc. should be monitored via ESPHome native fault codes.
- **Multi-room re-link via options requires re-creating entry**: once configured, you can re-link outdoor sensors via UI; to add/remove rooms or change room sensor links, delete and re-add the integration.

## Troubleshooting

**Setup wizard fails on entity selectors**
Make sure your `paveldn/haier-esphome` integration is loaded and exposes the required sensors before adding Haier Monitor.

**`q_sanity_smoothed` consistently below 0.7**
Real degradation. Check (in order): (1) outdoor coil cleanness, (2) `Calibration: outdoor ΔT offset`, (3) refrigerant charge.

**Energy values reset to 0 unexpectedly**
Storage is at `.storage/haier_monitor.<entry_id>.energy`. If the file gets corrupted (unlikely), values restart from 0. To intentionally reset: stop HA, delete the file, start HA.

**`health` says "starting" forever**
Steady-state requires compressor uptime > 5 min AND no defrost. If your compressor cycles faster than 5 minutes, you'll never see steady state. Since 1.2 the threshold is calibratable via `Calibration: steady-state uptime (s)` — drop to 180 s for short-cycling automations.

## Known sensor quirks on multi-split hOn (2U50S2SM1FA-3 etc.)

The `paveldn/haier-esphome` master publishes a fixed sensor set, but some fields don't carry what their name suggests on multi-split outdoor units. From field data collected on `2U50S2SM1FA-3`:

| Sensor | Mono-split | Multi-split (this model) | Action |
|---|---|---|---|
| `expansion_valve_open_degree` | fraction 0..1 (physical max ≈ 0.122 on 500-pulse PMV) | same | works |
| `outdoor_temperature` | OAT | OAT with ~1.5K systematic offset | use real outside sensor; `Calibration: outdoor T offset` can correct |
| `outdoor_coil_temperature` | refrigerant coil T (works in cool & heat) | same | works |
| `indoor_coil_temperature` | indoor coil T (cool: 5–15°C; heat: 40–55°C) | same | works |
| `outdoor_in_air_temperature` | intake air | **refrigerant suction-line T** (range −29..+39°C) | leave empty in setup; runtime sanity check auto-rejects |
| `outdoor_out_air_temperature` | exhaust air | **refrigerant discharge-line T** (range 20..74°C) | leave empty in setup; runtime sanity check auto-rejects |
| `power` | actual watts | often **constant 0** | leave empty; model-based fallback used |
| `compressor_current` | actual amps | often **stuck 51.1 A** (protocol max) | leave empty; runtime check ignores 51.1 |
| `indoor_humidity` | actual % | constant 0 | use external humidity sensor (`sensor.<your_room>_humidity`) |
| `defrost_status` (binary) | works | works | optional, takes precedence over heuristics |

Since 1.2 the integration auto-rejects bad readings runtime, but for cleaner setup leave the empty fields above unlinked.

## Q calculation methods (1.2+)

The new `Q calculation method` sensor exposes which estimator is being used at any moment:

| Method | When used | Accuracy |
|---|---|---|
| `indoor` | room temperature + indoor coil temperature both available | ±10–15% — primary, used by default |
| `outdoor_air` | both `outdoor_in/out_air` linked AND their values pass the sanity check (real air, not pipe-T) | ±10% — secondary, rarely available on multi-split |
| `carnot` | only coil temperatures available; bounded estimate `Q = η·COP_carnot·W_comp` | ±15–25% — last-resort fallback |
| `none` | compressor not running / not in steady state / no data | — |

The selection happens automatically (`Q method = auto` is the default). For diagnostic purposes you can force a specific method via the `Q method` option — but `auto` is recommended.

## Service manual references

- Section 7.1.1.4 — f_max(T_outdoor) tables (heating: 118 Hz <16°C, 112 Hz 16-20°C, 102 Hz ≥20°C; cooling: 37/45/56/63/90 Hz at 16/23/29/32/≥32°C)
- Section 7.1.4 — outdoor fan RPM tables (3×3 + extra row)
- Section 7.1.5 — EEV control (idle cool: 5 steps; idle heat: 80 steps)
- Section 11.1-11.4 — performance curves (P_max, Q_max at 8 cooling × 7 heating reference points)

## Changelog

### 1.2.0

Centred on the Q-rewrite that brings reported EER/COP into the physical range on multi-split hOn units. Field data showed Q overestimated 6-13× because `outdoor_in/out_air_temperature` fields on these units actually publish refrigerant pipe temperatures, not air.

- **Q rewrite — 3-method system** with automatic selection:
  - **Indoor coil enthalpy** (new, primary): `Q = Σ ρ·Cp·V·|T_room − T_coil|·(1−BF)` across active indoor units. Uses sensors that work reliably on multi-split.
  - **Outdoor air enthalpy** (legacy, fallback): activated only when `outdoor_in/out_air` pass sanity checks (`|out_air − ambient| < 25K`, `|ΔT| < 20K`, `out_air ≤ 50°C`, `in_air ≥ −20°C`). On most multi-split installs these checks reject the values and the indoor method is used.
  - **Carnot estimate** (new, last fallback): `Q ≈ η·COP_carnot(T_coil_indoor, T_coil_outdoor)·W_comp` when air & room data unavailable. ±15–25%.
  - New sensor `q_method` exposes which method is active; attribute on `q_indoor_total` shows `method` + `outdoor_air_sensors_valid`.
- **False defrost suppression**: hard gate `T_outdoor < 5°C` + `compressor_uptime ≥ 3 min`. The previous defrost detector fired 391 times in a week of field data while real outdoor was 5-25°C (physically impossible). Indicators 2/3 (defrost-T sensor and air ΔT direction) were dropped because they correlate with indicator 1 due to ESPHome `#87` and because the air-ΔT is meaningless on multi-split.
- **EEV defaults refined**: 1.1's `1.0 / 0.001 / 0.16` replaced with `0.122 / 0.0012 / 0.020` matching the physical 500-pulse PMV at the protocol's 4095 full-scale. Migration v2→v3 auto-upgrades.
- **Runtime sensor sanity**:
  - `native_power` rejected when reported `< 30 W` while compressor running (handles the all-zero multi-split case).
  - `compressor_current` rejected when stuck at protocol-max 51.1 A.
  - `outdoor_in/out_air` rejected when physical bounds violated; `approach_outdoor` falls back to ambient instead of the corrupted in_air.
- **New calibration sensors**:
  - `Calibration: outdoor T offset` (±5K) for systematic hOn outdoor_temperature bias.
  - `Calibration: steady-state uptime (s)` (60–900) for short-cycling automations.
- **Config flow**: `outdoor_in_air_temperature` / `outdoor_out_air_temperature` are now Optional (were Required). Users on multi-split should leave them empty.
- **Schema migration v3** with backwards-compatible storage migration of `q_kitchen`/`q_bedroom` → `q_room1`/`q_room2` retained from 1.1.
- **README**: added "Known sensor quirks on multi-split hOn" table and "Q calculation methods" section.

### 1.1.0
- **EEV scale fix (critical):** defaults aligned with `paveldn/haier-esphome` master, which publishes `expansion_valve_open_degree` as a fraction `0.0..1.0` (raw/4095). Previous defaults assumed "raw steps" and broke per-room `q_room` distribution and the EEV indicator of refrigerant FDD on most installations. Number-entity bounds widened to allow fraction calibration. Auto-migration (config entry v1 → v2) resets EEV calibration to the new defaults if the legacy default triple `500/5/80` is detected.
- **Truthiness fix:** lookup-table inputs no longer fall back to `20.0 °C` when `T_outdoor == 0.0 °C` (`coordinator.py`).
- **Cost calculation fix:** day/night kWh allocation is now used for `cost_daily/monthly/yearly` instead of `(day+night)/2 × total_kwh`. Adds two opt-in sensors `e_elec_day_daily` and `e_elec_night_daily`.
- **SEER/SCOP bias fix:** `p_cool/p_heat` is now gated on `steady_state` to mirror `q_indoor`, eliminating the systematic downward bias caused by integrating start-up / defrost electricity without matching heat output.
- **Defrost detection:** outdoor-fan-running fallback now correctly drops to `False` during defrost, removing a 50 W bias in `p_idle`.
- **q_kitchen / q_bedroom → q_room1 / q_room2:** internal field rename so storage matches actual room positions, not hardcoded names. Existing `.storage/haier_monitor.*.energy` files are migrated transparently on first load.
- **Midnight rollover:** daily/monthly/yearly snapshots are now taken via `async_track_time_change` at local 00:00 instead of "first tick after midnight", removing a few-hour data loss when HA restarts after a date change.
- **FDD constant:** the magic `15` in heat-mode refrigerant detection replaced with `FDD_REFRIGERANT_APPROACH_HEAT`.
- **Single-instance enforcement:** config flow now aborts on duplicate setup with the documented `single_instance_allowed` reason.
- Removed dead `STEADY_STATE_MIN_POWER_W` constant; manifest `iot_class` set to standard `local_polling`.

### 1.0.0
Initial release.

## License

MIT — see LICENSE.

## Credits

- Service Manual V1 (2021-05-31) by Haier
- ESPHome integration: [paveldn/haier-esphome](https://github.com/paveldn/haier-esphome)
- Physics references: ASHRAE Fundamentals 2021, Cuevas & Lebrun (2009), Yu et al. (2023), Tang et al. (2021)
