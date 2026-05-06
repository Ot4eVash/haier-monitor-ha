"""Base entity classes for Haier Multi-Split Monitor."""
from __future__ import annotations

from typing import Optional

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HaierMonitorCoordinator


class HaierMonitorEntity(CoordinatorEntity[HaierMonitorCoordinator]):
    """Base class for all Haier monitor entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HaierMonitorCoordinator,
        unique_id_suffix: str,
        translation_key: Optional[str] = None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_id_suffix}"
        if translation_key:
            self._attr_translation_key = translation_key

    @property
    def device_info(self) -> DeviceInfo:
        """Group all entities under one device."""
        entry = self.coordinator.entry
        return DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or "Haier Monitor",
            manufacturer="Haier",
            model="2U50S2SM1FA-3 Multi-Split (Calculated)",
            sw_version="1.0.0",
        )

    @property
    def available(self) -> bool:
        """Available if coordinator has data."""
        return self.coordinator.last_update_success and self.coordinator.data is not None
