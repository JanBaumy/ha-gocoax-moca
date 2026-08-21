"""Datenmodell eines MoCA-Netzes, wie es der Coordinator liefert."""

from __future__ import annotations

from dataclasses import dataclass, field

from .api.fmr import PhyRate


@dataclass(frozen=True, slots=True)
class LocalStats:
    """Ethernet-Zaehler eines Adapters.

    Nur von diesem Adapter selbst lesbar (Register 0x14) -- ist er nicht
    erreichbar, ist das Feld None und die Sensoren werden unavailable.
    """

    tx_good: int
    tx_bad: int
    tx_dropped: int
    rx_good: int
    rx_bad: int
    rx_dropped: int


@dataclass(frozen=True, slots=True)
class MocaNode:
    """Ein Knoten im MoCA-Netz, identifiziert ueber seine MAC."""

    mac: str  # normalisiert, ohne Trennzeichen
    mac_pretty: str  # 94:cc:04:00:aa:01
    node_id: int  # nicht stabil -- nur zur Anzeige
    moca_version: str
    gcd: int | None
    is_nc: bool
    local: LocalStats | None = None


@dataclass(frozen=True, slots=True)
class MocaNetwork:
    """Gesamtzustand des Netzes aus Sicht eines Polls."""

    link_up: bool
    moca_version: str
    node_mask: int
    nc_mac: str | None
    nodes: dict[str, MocaNode]  # key: normalisierte MAC
    rates: dict[tuple[str, str], PhyRate]  # (von_mac, nach_mac)
    beacon_channel: int | None = None
    first_channel: int | None = None
    num_channels: int | None = None
    lof: int | None = None
    # Hosts, die in diesem Poll nicht erreichbar waren (normalisierte MACs).
    unreachable: set[str] = field(default_factory=set)

    @property
    def node_count(self) -> int:
        return len(self.nodes)
