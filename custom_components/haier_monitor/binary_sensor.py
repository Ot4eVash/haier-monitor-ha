"""Binary sensor entities for Haier Multi-Split Monitor."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HaierMonitorCoordinator
from .entity import HaierMonitorEntity


@dataclass(frozen=True)
class HaierBinaryDef:
    """Definition of one binary sensor."""

    key: str
    translation_key: str
    icon: Optional[str] = None
    device_class: Optional[BinarySensorDeviceClass] = None
    enabled_by_default: bool = True


BINARY_SENSOR_DEFS: list[HaierBinaryDef] = [
    HaierBinaryDef("compressor_running", "compressor_running", "mdi:engine", BinarySensorDeviceClass.RUNNING),
    HaierBinaryDef("outdoor_fan_running", "outdoor_fan_running", "mdi:fan", BinarySensorDeviceClass.RUNNING, enabled_by_default=False),
    HaierBinaryDef("in_defrost", "in_defrost", "mdi:snowflake-melt", BinarySensorDeviceClass.RUNNING),
    HaierBinaryDef("steady_state", "steady_state", "mdi:check-circle-outline", None),
    HaierBinaryDef("fdd_outdoor_coil", "fdd_outdoor_coil", "mdi:water-alert", BinarySensorDeviceClass.PROBLEM, enabled_by_default=False),
    HaierBinaryDef("fdd_refrigerant", "fdd_refrigerant", "mdi:gas-cylinder", BinarySensorDeviceClass.PROBLEM, enabled_by_default=False),
    HaierBinaryDef("fdd_cycling", "fdd_cycling", "mdi:restart-alert", BinarySensorDeviceClass.PROBLEM, enabled_by_default=False),
    HaierBinaryDef("fdd_excessive_defrost", "fdd_excessive_defrost", "mdi:snowflake-melt", BinarySensorDeviceClass.PROBLEM, enabled_by_default=False),
]


class HaierMonitorBinarySensor(HaierMonitorEntity, BinarySensorEntity):
    """Generic binary sensor."""

    def __init__(
        self,
        coordinator: HaierMonitorCoordinator,
        binary_def: HaierBinaryDef,
    ) -> None:
        super().__init__(coordinator, binary_def.key, binary_def.translation_key)
        self._def = binary_def
        self._attr_device_class = binary_def.device_class
        self._attr_icon = binary_def.icon
        if not binary_def.enabled_by_default:
            self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> Optional[bool]:
        if self.coordinator.data is None:
            return None
        v = self.coordinator.data.get(self._def.key)
        return bool(v) if v is not None else None


@dataclass(frozen=True)
class HaierRoomBinaryDef:
    """Per-room binary sensor."""

    field_name: str
    translation_key: str
    icon: Optional[str] = None
    device_class: Optional[BinarySensorDeviceClass] = None
    enabled_by_default: bool = True


ROOM_BINARY_DEFS: list[HaierRoomBinaryDef] = [
    HaierRoomBinaryDef("fan_running", "fan_running_room", "mdi:fan", BinarySensorDeviceClass.RUNNING, enabled_by_default=False),
    HaierRoomBinaryDef("condensation", "condensation_room", "mdi:water", BinarySensorDeviceClass.MOISTURE, enabled_by_default=False),
    HaierRoomBinaryDef("fdd_filter", "fdd_filter_room", "mdi:air-filter", BinarySensorDeviceClass.PROBLEM, enabled_by_default=False),
]


class HaierMonitorRoomBinarySensor(HaierMonitorEntity, BinarySensorEntity):
    """Per-room binary sensor."""

    def __init__(
        self,
        coordinator: HaierMonitorCoordinator,
        room_name: str,
        binary_def: HaierRoomBinaryDef,
    ) -> None:
        super().__init__(
            coordinator,
            f"room_{room_name}_{binary_def.field_name}",
            binary_def.translation_key,
        )
        self._room_name = room_name
        self._def = binary_def
        self._attr_translation_placeholders = {"room": room_name}
        self._attr_device_class = binary_def.device_class
        self._attr_icon = binary_def.icon
        if not binary_def.enabled_by_default:
            self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> Optional[bool]:
        if self.coordinator.data is None:
            return None
        rooms = self.coordinator.data.get("rooms", {})
        room = rooms.get(self._room_name)
        if not room:
            return None
        v = room.get(self._def.field_name)
        return bool(v) if v is not None else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: HaierMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = []
    for bd in BINARY_SENSOR_DEFS:
        entities.append(HaierMonitorBinarySensor(coordinator, bd))

    for iu in entry.data.get("indoor_units", []):
        room_name = iu["name"]
        for rbd in ROOM_BINARY_DEFS:
            entities.append(HaierMonitorRoomBinarySensor(coordinator, room_name, rbd))

    async_add_entities(entities)
