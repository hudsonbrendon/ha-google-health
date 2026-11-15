"""Entidade base: um dispositivo por grupo de dados."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEV_ACCOUNT, DEVICE_NAMES, DOMAIN
from .coordinator import GoogleHealthCoordinator


class GoogleHealthEntity(CoordinatorEntity[GoogleHealthCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GoogleHealthCoordinator, device: str, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        # unique_id igual ao do core ({entry_id}_{key}) → entidades antigas adotadas.
        self._attr_unique_id = f"{entry_id}_{key}"
        ident = entry_id if device == DEV_ACCOUNT else f"{entry_id}_{device}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ident)},
            manufacturer="Google",
            model=DEVICE_NAMES[device].removeprefix("Google Health "),
            name=DEVICE_NAMES[device],
            entry_type=DeviceEntryType.SERVICE,
        )
