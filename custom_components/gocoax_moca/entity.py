"""Basisklassen fuer Netz- und Knoten-Entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GoCoaxCoordinator
from .models import MocaNode


class GoCoaxNetworkEntity(CoordinatorEntity[GoCoaxCoordinator]):
    """Entity am Service-Device, das fuer das MoCA-Netz als Ganzes steht."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GoCoaxCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        self._attr_unique_id = f"net_{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"net_{entry_id}")},
            name="MoCA-Netzwerk",
            manufacturer="GoCoax",
            model="MoCA 2.5 Netzwerk",
        )


class GoCoaxNodeEntity(CoordinatorEntity[GoCoaxCoordinator]):
    """Entity an einem einzelnen Adapter.

    Die Identitaet haengt an der MAC, nicht an der MoCA-Node-ID: die ist nach
    einem Reboot nicht stabil, und die NC-Rolle wandert.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: GoCoaxCoordinator, mac: str, key: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{mac}_{key}"
        entry_id = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        node = coordinator.data.nodes[mac]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(CONNECTION_NETWORK_MAC, node.mac_pretty)},
            name=f"MoCA-Adapter {node.mac_pretty}",
            manufacturer="GoCoax",
            model="MXL371x",
            via_device=(DOMAIN, f"net_{entry_id}"),
        )

    @property
    def node(self) -> MocaNode | None:
        return self.coordinator.data.nodes.get(self._mac)

    @property
    def available(self) -> bool:
        """Ein Knoten, der aus dem Netz verschwindet, wird unavailable."""
        return super().available and self.node is not None


class GoCoaxLocalNodeEntity(GoCoaxNodeEntity):
    """Entity fuer Werte, die nur der Adapter selbst liefern kann (0x14).

    Faellt genau dieser Adapter aus, muessen die Zaehler unavailable werden --
    wuerden sie 0 zeigen, saehe ein Ausfall in der Historie wie ein
    Traffic-Einbruch aus.
    """

    @property
    def available(self) -> bool:
        node = self.node
        return super().available and node is not None and node.local is not None
