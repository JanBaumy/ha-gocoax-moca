"""Link- und Knoten-Status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GoCoaxConfigEntry, GoCoaxCoordinator
from .entity import GoCoaxNetworkEntity, GoCoaxNodeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoCoaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    async_add_entities([GoCoaxLinkSensor(coordinator)])

    @callback
    def _add_new_nodes() -> None:
        new = set(coordinator.data.nodes) - known
        if not new:
            return
        known.update(new)
        async_add_entities(GoCoaxNodeOnlineSensor(coordinator, mac) for mac in new)

    _add_new_nodes()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_nodes))


class GoCoaxLinkSensor(GoCoaxNetworkEntity, BinarySensorEntity):
    """MoCA-Link des Netzes."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "link"

    def __init__(self, coordinator: GoCoaxCoordinator) -> None:
        super().__init__(coordinator, "link")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.link_up


class GoCoaxNodeOnlineSensor(GoCoaxNodeEntity, BinarySensorEntity):
    """Ist dieser Adapter im MoCA-Netz sichtbar?

    Verschwindet er, bleibt die Entity bestehen und geht auf 'off' -- ein Knoten,
    der wegen eines Kabelproblems zehn Minuten fehlt, soll seine Historie behalten.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "node_online"

    def __init__(self, coordinator: GoCoaxCoordinator, mac: str) -> None:
        super().__init__(coordinator, mac, "online")

    @property
    def available(self) -> bool:
        # Bewusst nicht die Basisklasse: gerade das Fehlen des Knotens ist hier
        # die Information, nicht ein Grund fuer unavailable.
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self._mac in self.coordinator.data.nodes
