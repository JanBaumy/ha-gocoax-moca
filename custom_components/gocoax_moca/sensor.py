"""Sensoren des MoCA-Netzes und der einzelnen Adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfFrequency
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import GoCoaxConfigEntry, GoCoaxCoordinator
from .entity import GoCoaxNetworkEntity, GoCoaxNodeEntity
from .models import MocaNetwork, MocaNode

MBIT = UnitOfDataRate.MEGABITS_PER_SECOND


@dataclass(frozen=True, kw_only=True)
class GoCoaxNetworkSensorDescription(SensorEntityDescription):
    """Sensor am Netzwerk-Device."""

    value_fn: Callable[[MocaNetwork], StateType]


@dataclass(frozen=True, kw_only=True)
class GoCoaxNodeSensorDescription(SensorEntityDescription):
    """Sensor an einem Adapter."""

    value_fn: Callable[[MocaNode], StateType]
    # Wert stammt aus einem nur lokal lesbaren Register (0x14).
    needs_local: bool = False


NETWORK_SENSORS: tuple[GoCoaxNetworkSensorDescription, ...] = (
    GoCoaxNetworkSensorDescription(
        key="node_count",
        translation_key="node_count",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda net: net.node_count,
    ),
    GoCoaxNetworkSensorDescription(
        key="net_version",
        translation_key="net_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda net: net.moca_version,
    ),
    GoCoaxNetworkSensorDescription(
        key="nc_node",
        translation_key="nc_node",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda net: (
            net.nodes[net.nc_mac].mac_pretty if net.nc_mac in net.nodes else None
        ),
    ),
    GoCoaxNetworkSensorDescription(
        key="beacon_channel",
        translation_key="beacon_channel",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda net: net.beacon_channel,
    ),
    GoCoaxNetworkSensorDescription(
        key="first_channel",
        translation_key="first_channel",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda net: net.first_channel,
    ),
    GoCoaxNetworkSensorDescription(
        key="num_channels",
        translation_key="num_channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda net: net.num_channels,
    ),
    GoCoaxNetworkSensorDescription(
        key="lof",
        translation_key="lof",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda net: net.lof,
    ),
)


def _counter(key: str, getter: Callable[[MocaNode], int], *, enabled: bool):
    return GoCoaxNodeSensorDescription(
        key=key,
        translation_key=key,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=enabled,
        needs_local=True,
        value_fn=lambda node: getter(node) if node.local else None,
    )


NODE_SENSORS: tuple[GoCoaxNodeSensorDescription, ...] = (
    GoCoaxNodeSensorDescription(
        key="gcd",
        translation_key="gcd",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=MBIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda node: node.gcd,
    ),
    GoCoaxNodeSensorDescription(
        key="node_version",
        translation_key="node_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda node: node.moca_version,
    ),
    GoCoaxNodeSensorDescription(
        key="node_id",
        translation_key="node_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.node_id,
    ),
    # Fehlerzaehler sind die eigentlichen Alarmwerte -> standardmaessig an.
    _counter("tx_bad", lambda n: n.local.tx_bad, enabled=True),
    _counter("tx_dropped", lambda n: n.local.tx_dropped, enabled=True),
    _counter("rx_bad", lambda n: n.local.rx_bad, enabled=True),
    _counter("rx_dropped", lambda n: n.local.rx_dropped, enabled=True),
    _counter("tx_good", lambda n: n.local.tx_good, enabled=False),
    _counter("rx_good", lambda n: n.local.rx_good, enabled=False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoCoaxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Legt die Sensoren an und ergaenzt sie, wenn spaeter Knoten dazukommen."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    async_add_entities(
        GoCoaxNetworkSensor(coordinator, description)
        for description in NETWORK_SENSORS
    )

    @callback
    def _add_new_nodes() -> None:
        new = set(coordinator.data.nodes) - known
        if not new:
            return
        known.update(new)
        entities: list[SensorEntity] = []
        for mac in new:
            entities += [
                GoCoaxNodeSensor(coordinator, mac, description)
                for description in NODE_SENSORS
            ]
            entities += [
                GoCoaxPhyRateSensor(coordinator, mac, peer, vlper=vlper)
                for peer in coordinator.data.nodes
                if peer != mac
                for vlper in (False, True)
            ]
        async_add_entities(entities)

    _add_new_nodes()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_nodes))


class GoCoaxNetworkSensor(GoCoaxNetworkEntity, SensorEntity):
    """Sensor am Netzwerk-Device."""

    entity_description: GoCoaxNetworkSensorDescription

    def __init__(
        self,
        coordinator: GoCoaxCoordinator,
        description: GoCoaxNetworkSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)


class GoCoaxNodeSensor(GoCoaxNodeEntity, SensorEntity):
    """Sensor an einem Adapter."""

    entity_description: GoCoaxNodeSensorDescription

    def __init__(
        self,
        coordinator: GoCoaxCoordinator,
        mac: str,
        description: GoCoaxNodeSensorDescription,
    ) -> None:
        super().__init__(coordinator, mac, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if self.entity_description.needs_local:
            node = self.node
            return super().available and node is not None and node.local is not None
        return super().available

    @property
    def native_value(self) -> StateType:
        node = self.node
        return None if node is None else self.entity_description.value_fn(node)


class GoCoaxPhyRateSensor(GoCoaxNodeEntity, SensorEntity):
    """PHY-Rate von einem Knoten zu einem bestimmten Peer.

    Gerichtet: 0->1 und 1->0 unterscheiden sich, und eine einseitig
    einbrechende Rate zeigt ein Leitungsproblem an.
    """

    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = MBIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: GoCoaxCoordinator,
        mac: str,
        peer_mac: str,
        *,
        vlper: bool,
    ) -> None:
        kind = "phy_vlper" if vlper else "phy_nper"
        super().__init__(coordinator, mac, f"{peer_mac}_{kind}")
        self._peer_mac = peer_mac
        self._vlper = vlper
        self._attr_translation_key = kind
        self._attr_translation_placeholders = {
            "peer": coordinator.data.nodes[peer_mac].mac_pretty
        }
        if vlper:
            # Auf diesem Netz durchgehend 0 -- ein Sensor, der dauerhaft 0 zeigt,
            # sieht fuer den Nutzer nach einem Defekt aus.
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        key = (self._mac, self._peer_mac)
        return super().available and key in self.coordinator.data.rates

    @property
    def native_value(self) -> StateType:
        rate = self.coordinator.data.rates.get((self._mac, self._peer_mac))
        if rate is None:
            return None
        return rate.vlper if self._vlper else rate.nper
