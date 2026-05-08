"""Config flow for Haier Multi-Split Monitor.

Fixed 2-indoor-unit flow:
    1. user step — integration name + room names (default 'Кухня', 'Спальня')
    2. room_1 step — first indoor unit sensors
    3. room_2 step — second indoor unit sensors
    4. outdoor step — link outdoor-side sensors (shared between IUs)
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
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
    DEFAULT_ROOM_CAPACITY,
    DOMAIN,
)


def _entity_selector(
    domain: list[str] | str,
    *,
    multiple: bool = False,
    device_class: str | None = None,
) -> selector.EntitySelector:
    """Convenience for entity selector with optional filter."""
    config: dict[str, Any] = {"multiple": multiple}
    if isinstance(domain, str):
        config["domain"] = domain
    else:
        config["domain"] = domain
    if device_class:
        config["device_class"] = device_class
    return selector.EntitySelector(selector.EntitySelectorConfig(**config))


def _temp_selector(multiple: bool = True) -> selector.EntitySelector:
    return _entity_selector("sensor", multiple=multiple, device_class="temperature")


def _humidity_selector() -> selector.EntitySelector:
    return _entity_selector("sensor", multiple=False, device_class="humidity")


def _binary_selector(multiple: bool = True) -> selector.EntitySelector:
    return _entity_selector("binary_sensor", multiple=multiple)


def _frequency_selector() -> selector.EntitySelector:
    return _entity_selector("sensor", multiple=True)


def _eev_selector() -> selector.EntitySelector:
    return _entity_selector("sensor", multiple=False)


def _climate_selector() -> selector.EntitySelector:
    return _entity_selector("climate", multiple=False)


# ---------------------------------------------------------------------------
# Initial flow
# ---------------------------------------------------------------------------
def _room_schema(room_default_name: str) -> vol.Schema:
    """Schema for one indoor unit step."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=room_default_name): str,
            vol.Required(CONF_CLIMATE_ENTITY): _climate_selector(),
            vol.Required(CONF_INDOOR_FAN_STATUS): _binary_selector(multiple=False),
            vol.Required(CONF_EEV_OPENING): _eev_selector(),
            vol.Optional(CONF_ROOM_TEMP_SENSOR): _temp_selector(multiple=False),
            vol.Optional(CONF_ROOM_HUMIDITY_SENSOR): _humidity_selector(),
            vol.Optional(CONF_INDOOR_COIL_TEMP): _temp_selector(multiple=False),
            vol.Required(
                CONF_ROOM_CAPACITY, default=DEFAULT_ROOM_CAPACITY
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1500,
                    max=7000,
                    step=100,
                    unit_of_measurement="W",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _build_room_dict(user_input: dict) -> dict:
    """Convert user_input into the indoor_units list element."""
    return {
        CONF_NAME: user_input[CONF_NAME],
        CONF_CLIMATE_ENTITY: user_input.get(CONF_CLIMATE_ENTITY),
        CONF_INDOOR_FAN_STATUS: user_input.get(CONF_INDOOR_FAN_STATUS),
        CONF_EEV_OPENING: user_input.get(CONF_EEV_OPENING),
        CONF_ROOM_TEMP_SENSOR: user_input.get(CONF_ROOM_TEMP_SENSOR),
        CONF_ROOM_HUMIDITY_SENSOR: user_input.get(CONF_ROOM_HUMIDITY_SENSOR),
        CONF_INDOOR_COIL_TEMP: user_input.get(CONF_INDOOR_COIL_TEMP),
        CONF_ROOM_CAPACITY: user_input.get(CONF_ROOM_CAPACITY, DEFAULT_ROOM_CAPACITY),
    }


class HaierMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure Haier Multi-Split Monitor (fixed two indoor units)."""

    VERSION = 2

    def __init__(self) -> None:
        self._name: str = "Haier Monitor"
        self._indoor_units: list[dict] = []
        self._outdoor: dict = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: integration name."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            self._name = user_input[CONF_NAME]
            return await self.async_step_room_1()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Haier Monitor"): str,
                }
            ),
        )

    async def async_step_room_1(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure first indoor unit (default 'Кухня')."""
        if user_input is not None:
            self._indoor_units = [_build_room_dict(user_input)]
            return await self.async_step_room_2()

        return self.async_show_form(
            step_id="room_1",
            data_schema=_room_schema("Кухня"),
        )

    async def async_step_room_2(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure second indoor unit (default 'Спальня')."""
        if user_input is not None:
            self._indoor_units.append(_build_room_dict(user_input))
            return await self.async_step_outdoor()

        return self.async_show_form(
            step_id="room_2",
            data_schema=_room_schema("Спальня"),
        )

    async def async_step_outdoor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure outdoor-side sensors (shared)."""
        if user_input is not None:
            self._outdoor = {
                CONF_OUTDOOR_TEMP: user_input.get(CONF_OUTDOOR_TEMP, []),
                CONF_OUTDOOR_COIL_TEMP: user_input.get(CONF_OUTDOOR_COIL_TEMP, []),
                CONF_OUTDOOR_DEFROST_TEMP: user_input.get(CONF_OUTDOOR_DEFROST_TEMP, []),
                CONF_OUTDOOR_IN_AIR_TEMP: user_input.get(CONF_OUTDOOR_IN_AIR_TEMP, []),
                CONF_OUTDOOR_OUT_AIR_TEMP: user_input.get(CONF_OUTDOOR_OUT_AIR_TEMP, []),
                CONF_COMPRESSOR_FREQUENCY: user_input.get(CONF_COMPRESSOR_FREQUENCY, []),
                CONF_COMPRESSOR_STATUS: user_input.get(CONF_COMPRESSOR_STATUS, []),
                CONF_NATIVE_POWER: user_input.get(CONF_NATIVE_POWER, []),
                CONF_NATIVE_COMPRESSOR_CURRENT: user_input.get(
                    CONF_NATIVE_COMPRESSOR_CURRENT, []
                ),
                CONF_NATIVE_DEFROST: user_input.get(CONF_NATIVE_DEFROST, []),
                CONF_NATIVE_OUTDOOR_FAN: user_input.get(CONF_NATIVE_OUTDOOR_FAN, []),
            }
            return self.async_create_entry(
                title=self._name,
                data={
                    CONF_NAME: self._name,
                    CONF_INDOOR_UNITS: self._indoor_units,
                    CONF_OUTDOOR_TEMP_SOURCES: self._outdoor,
                },
            )

        return self.async_show_form(
            step_id="outdoor",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OUTDOOR_TEMP): _temp_selector(multiple=True),
                    vol.Required(CONF_OUTDOOR_COIL_TEMP): _temp_selector(multiple=True),
                    vol.Optional(CONF_OUTDOOR_DEFROST_TEMP): _temp_selector(multiple=True),
                    vol.Required(CONF_OUTDOOR_IN_AIR_TEMP): _temp_selector(multiple=True),
                    vol.Required(CONF_OUTDOOR_OUT_AIR_TEMP): _temp_selector(multiple=True),
                    vol.Required(CONF_COMPRESSOR_FREQUENCY): _frequency_selector(),
                    vol.Required(CONF_COMPRESSOR_STATUS): _binary_selector(multiple=True),
                    vol.Optional(CONF_NATIVE_POWER): _entity_selector(
                        "sensor", multiple=True, device_class="power"
                    ),
                    vol.Optional(CONF_NATIVE_COMPRESSOR_CURRENT): _entity_selector(
                        "sensor", multiple=True, device_class="current"
                    ),
                    vol.Optional(CONF_NATIVE_DEFROST): _binary_selector(multiple=True),
                    vol.Optional(CONF_NATIVE_OUTDOOR_FAN): _binary_selector(multiple=True),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        return HaierMonitorOptionsFlow(config_entry)


# ---------------------------------------------------------------------------
# Options flow — re-edit sensor links and basic config (calibration is via numbers)
# ---------------------------------------------------------------------------
class HaierMonitorOptionsFlow(OptionsFlow):
    """Options flow — re-link sensors after install."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show menu of edit options."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["outdoor_relink", "rooms_relink"],
        )

    async def async_step_outdoor_relink(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-edit outdoor source entities."""
        if user_input is not None:
            new_data = {**self.config_entry.data}
            new_data[CONF_OUTDOOR_TEMP_SOURCES] = {
                k: user_input.get(k, []) for k in user_input
            }
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data=self.config_entry.options)

        current = self.config_entry.data.get(CONF_OUTDOOR_TEMP_SOURCES, {})
        return self.async_show_form(
            step_id="outdoor_relink",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_OUTDOOR_TEMP, default=current.get(CONF_OUTDOOR_TEMP, [])
                    ): _temp_selector(multiple=True),
                    vol.Required(
                        CONF_OUTDOOR_COIL_TEMP,
                        default=current.get(CONF_OUTDOOR_COIL_TEMP, []),
                    ): _temp_selector(multiple=True),
                    vol.Optional(
                        CONF_OUTDOOR_DEFROST_TEMP,
                        default=current.get(CONF_OUTDOOR_DEFROST_TEMP, []),
                    ): _temp_selector(multiple=True),
                    vol.Required(
                        CONF_OUTDOOR_IN_AIR_TEMP,
                        default=current.get(CONF_OUTDOOR_IN_AIR_TEMP, []),
                    ): _temp_selector(multiple=True),
                    vol.Required(
                        CONF_OUTDOOR_OUT_AIR_TEMP,
                        default=current.get(CONF_OUTDOOR_OUT_AIR_TEMP, []),
                    ): _temp_selector(multiple=True),
                    vol.Required(
                        CONF_COMPRESSOR_FREQUENCY,
                        default=current.get(CONF_COMPRESSOR_FREQUENCY, []),
                    ): _frequency_selector(),
                    vol.Required(
                        CONF_COMPRESSOR_STATUS,
                        default=current.get(CONF_COMPRESSOR_STATUS, []),
                    ): _binary_selector(multiple=True),
                    vol.Optional(
                        CONF_NATIVE_POWER, default=current.get(CONF_NATIVE_POWER, [])
                    ): _entity_selector("sensor", multiple=True, device_class="power"),
                    vol.Optional(
                        CONF_NATIVE_COMPRESSOR_CURRENT,
                        default=current.get(CONF_NATIVE_COMPRESSOR_CURRENT, []),
                    ): _entity_selector("sensor", multiple=True, device_class="current"),
                    vol.Optional(
                        CONF_NATIVE_DEFROST, default=current.get(CONF_NATIVE_DEFROST, [])
                    ): _binary_selector(multiple=True),
                    vol.Optional(
                        CONF_NATIVE_OUTDOOR_FAN,
                        default=current.get(CONF_NATIVE_OUTDOOR_FAN, []),
                    ): _binary_selector(multiple=True),
                }
            ),
        )

    async def async_step_rooms_relink(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Inform user that room editing requires re-creating entry (limitation)."""
        return self.async_abort(reason="rooms_relink_not_supported")
