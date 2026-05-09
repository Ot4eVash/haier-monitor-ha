"""Haier Multi-Split Monitor integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_EEV_IDLE_COOL,
    DEFAULT_EEV_IDLE_HEAT,
    DEFAULT_EEV_MAX,
    DOMAIN,
    OPT_EEV_IDLE_COOL,
    OPT_EEV_IDLE_HEAT,
    OPT_EEV_MAX,
)
from .coordinator import HaierMonitorCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry options between schema versions.

    1 → 2: EEV calibration units changed from raw steps (max=500) to fraction
    of full open (max=1.0), aligned with paveldn/haier-esphome's
    raw/4095 publication. Old options are detected by the legacy default
    triple (500.0 / 5.0 / 80.0) and reset to None so the new defaults apply.
    """
    if entry.version >= 2:
        return True

    options = dict(entry.options)
    legacy_eev = (
        options.get(OPT_EEV_MAX) == 500.0
        and options.get(OPT_EEV_IDLE_COOL) == 5.0
        and options.get(OPT_EEV_IDLE_HEAT) == 80.0
    )
    if legacy_eev:
        options[OPT_EEV_MAX] = DEFAULT_EEV_MAX
        options[OPT_EEV_IDLE_COOL] = DEFAULT_EEV_IDLE_COOL
        options[OPT_EEV_IDLE_HEAT] = DEFAULT_EEV_IDLE_HEAT
        _LOGGER.warning(
            "Haier Monitor: migrated EEV calibration from raw-steps (500/5/80) "
            "to fraction (1.0/0.001/0.16). Re-check Calibration: EEV* numbers "
            "if your ESPHome publishes raw step values instead of fractions."
        )

    hass.config_entries.async_update_entry(entry, options=options, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Haier Monitor from a config entry."""
    coordinator = HaierMonitorCoordinator(hass, entry)
    await coordinator.async_load_persistent()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Persist energy state on shutdown and listen for option changes
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(
        hass.bus.async_listen_once(
            "homeassistant_stop",
            lambda _event: hass.async_create_task(coordinator.async_save_persistent()),
        )
    )
    # Snapshot daily/monthly/yearly buckets at exactly local 00:00 — survives
    # restarts that happen mid-day without losing accumulated consumption.
    entry.async_on_unload(coordinator.async_register_midnight_listener())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: HaierMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_save_persistent()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options/data update — refresh coordinator with new config."""
    coordinator: HaierMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.config = {**entry.data, **entry.options}
    await coordinator.async_request_refresh()
