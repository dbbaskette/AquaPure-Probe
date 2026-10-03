"""Sensors exposed by the read-only AquaPure probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AquaPureProbeCoordinator


@dataclass(frozen=True, kw_only=True)
class ProbeSensorDescription(SensorEntityDescription):
    """Description for a value returned by the diagnostic command."""

    data_key: str


DESCRIPTIONS: tuple[ProbeSensorDescription, ...] = (
    ProbeSensorDescription(key="pool_output", name="Pool chlorine output", native_unit_of_measurement=PERCENTAGE, data_key="pool_output"),
    ProbeSensorDescription(key="spa_output", name="Spa chlorine output", native_unit_of_measurement=PERCENTAGE, data_key="spa_output"),
    ProbeSensorDescription(key="salt_ppm", name="Salt level", native_unit_of_measurement="ppm", data_key="salt_ppm"),
    ProbeSensorDescription(key="swc_status", name="Chlorinator status", data_key="swc_status"),
    ProbeSensorDescription(key="boost_status", name="Boost status", data_key="boost_status"),
    ProbeSensorDescription(key="boost_hours_remaining", name="Boost hours remaining", native_unit_of_measurement="h", data_key="boost_hours_remaining"),
    ProbeSensorDescription(key="low_salt", name="Low salt flag", entity_category=EntityCategory.DIAGNOSTIC, data_key="low_salt"),
    ProbeSensorDescription(key="probe_response", name="Probe response", entity_category=EntityCategory.DIAGNOSTIC, data_key="probe_response"),
    ProbeSensorDescription(key="webtouch_status", name="WebTouch probe", entity_category=EntityCategory.DIAGNOSTIC, data_key="webtouch_status"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[AquaPureProbeCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up only the values actually returned by the controller."""
    coordinator = entry.runtime_data
    async_add_entities(
        AquaPureProbeSensor(coordinator, description)
        for description in DESCRIPTIONS
        if coordinator.data.get(description.data_key) not in (None, "")
    )


class AquaPureProbeSensor(CoordinatorEntity[AquaPureProbeCoordinator], SensorEntity):
    """A non-controlling AquaPure diagnostic sensor."""

    entity_description: ProbeSensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: AquaPureProbeCoordinator, description: ProbeSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.data['serial']}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={("aquapure_probe", coordinator.data["serial"])},
            name=f"AquaPure Probe — {coordinator.data['system_name']}",
            manufacturer="Jandy / Fluidra",
            model="AquaPure cloud diagnostic probe",
        )

    @property
    def native_value(self) -> Any:
        """Return only the selected non-secret response field."""
        return self.coordinator.data.get(self.entity_description.data_key)
