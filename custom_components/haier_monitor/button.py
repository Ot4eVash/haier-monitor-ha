"""Button entities for maintenance reset.

Pressing a button records the current timestamp via coordinator API,
which feeds `sensor.haier_filter_days_*` and triggers reminders.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HaierMonitorCoordinator
from .entity import HaierMonitorEntity


class HaierFilterCleanedButton(HaierMonitorEntity, ButtonEntity):
    """Button to mark filter as cleaned now."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:air-filter"

    def __init__(
        self, coordinator: HaierMonitorCoordinator, room_name: str
    ) -> None:
        super().__init__(
            coordinator,
            f"button_filter_cleaned_{room_name}",
            "filter_cleaned_room",
        )
        self._room_name = room_name
        self._attr_translation_placeholders = {"room": room_name}

    async def async_press(self) -> None:
        await self.coordinator.async_set_filter_cleaned(self._room_name)


class HaierOutdoorCleanedButton(HaierMonitorEntity, ButtonEntity):
    """Button to mark outdoor unit as cleaned now."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:water"

    def __init__(self, coordinator: HaierMonitorCoordinator) -> None:
        super().__init__(coordinator, "button_outdoor_cleaned", "outdoor_cleaned")

    async def async_press(self) -> None:
        await self.coordinator.async_set_outdoor_cleaned()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up maintenance buttons."""
    coordinator: HaierMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [HaierOutdoorCleanedButton(coordinator)]
    for iu in entry.data.get("indoor_units", []):
        entities.append(HaierFilterCleanedButton(coordinator, iu["name"]))
    async_add_entities(entities)
