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

Look at your raw `expansion_valve_open_degree` sensor with the AC off:
- If shows ~5: leave defaults (steps mode).
- If shows ~42: set `Calibration: EEV max` = 4095, `EEV idle cool` = 42, `EEV idle heat` = 683 (encoded mode).

### Recommended after 1-2 weeks of operation

| Number entity | Meaning | Default |
|---|---|---|
| `Calibration: EEV max` | Max value of the EEV sensor (steps or encoded) | 500 |
| `Calibration: EEV idle (cool/dry)` | EEV bleed-through in cool mode | 5 |
| `Calibration: EEV idle (heat)` | EEV bleed-through in heat mode | 80 |
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
Steady-state requires compressor uptime > 5 min AND no defrost. If your compressor cycles faster than 5 minutes, you'll never see steady state. This is by design — short cycles produce unreliable COP measurements.

## Service manual references

- Section 7.1.1.4 — f_max(T_outdoor) tables (heating: 118 Hz <16°C, 112 Hz 16-20°C, 102 Hz ≥20°C; cooling: 37/45/56/63/90 Hz at 16/23/29/32/≥32°C)
- Section 7.1.4 — outdoor fan RPM tables (3×3 + extra row)
- Section 7.1.5 — EEV control (idle cool: 5 steps; idle heat: 80 steps)
- Section 11.1-11.4 — performance curves (P_max, Q_max at 8 cooling × 7 heating reference points)

## License

MIT — see LICENSE.

## Credits

- Service Manual V1 (2021-05-31) by Haier
- ESPHome integration: [paveldn/haier-esphome](https://github.com/paveldn/haier-esphome)
- Physics references: ASHRAE Fundamentals 2021, Cuevas & Lebrun (2009), Yu et al. (2023), Tang et al. (2021)
