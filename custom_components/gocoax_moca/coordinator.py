"""Poll-Koordinator fuer ein MoCA-Netz.

Ein Coordinator bedient den gesamten Config-Entry: Die Register 0x16 und 0x1D
liefern Daten fuer alle Knoten, ein Poll gegen einen Adapter genuegt also
netzwerkweit. Nur die Ethernet-Zaehler (0x14) sind pro Adapter verschieden.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GoCoaxAuthError, GoCoaxClient, GoCoaxError
from .api.decode import (
    FRAME_RX_BAD,
    FRAME_RX_DROPPED,
    FRAME_RX_GOOD,
    FRAME_TX_BAD,
    FRAME_TX_DROPPED,
    FRAME_TX_GOOD,
    LOCAL_LINK_STATUS,
    LOCAL_NC_ID,
    LOCAL_NET_MOCA_VER,
    LOCAL_NODE_BITMASK,
    NET_MAC_HI,
    NET_MAC_LO,
    NET_MOCA_VER,
    mac_from_words,
    moca_version,
    nodes_from_bitmask,
    normalize_mac,
    u64,
)
from .api.fmr import compute_phy_rates
from .models import LocalStats, MocaNetwork, MocaNode

_LOGGER = logging.getLogger(__name__)

type GoCoaxConfigEntry = ConfigEntry[GoCoaxCoordinator]


class GoCoaxCoordinator(DataUpdateCoordinator[MocaNetwork]):
    """Pollt das MoCA-Netz und faellt bei Bedarf auf einen anderen Adapter zurueck."""

    config_entry: GoCoaxConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GoCoaxConfigEntry,
        clients: list[GoCoaxClient],
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="GoCoax MoCA",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._clients = clients
        # Host-MAC je Client; wird in _async_setup gefuellt und ordnet die
        # Ethernet-Zaehler dem richtigen Knoten-Device zu.
        self._host_macs: dict[str, str] = {}
        self._primary: GoCoaxClient = clients[0]

    async def _async_setup(self) -> None:
        """Einmalige Stammdaten.

        Laeuft nur beim ersten Refresh -- hier gehoert ausschliesslich Identitaet
        hinein. Alles, was sich erholen koennen muss, wird pro Poll geholt.
        """
        for client in self._clients:
            try:
                words = await client.async_own_mac()
            except GoCoaxAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except (GoCoaxError, ClientError, TimeoutError) as err:
                # Ein beim Setup nicht erreichbarer Peer darf die Integration
                # nicht blockieren -- seine Zaehler fehlen dann eben.
                _LOGGER.warning(
                    "MAC von %s beim Setup nicht lesbar: %s", client.host, err
                )
                continue
            self._host_macs[client.host] = normalize_mac(
                mac_from_words(words[0], words[1])
            )

    def _ordered_clients(self) -> list[GoCoaxClient]:
        """Zuletzt erfolgreicher Host zuerst."""
        return [self._primary] + [c for c in self._clients if c is not self._primary]

    async def _async_update_data(self) -> MocaNetwork:
        last_exc: Exception | None = None
        network: MocaNetwork | None = None

        for client in self._ordered_clients():
            try:
                network = await self._fetch_network(client)
            except GoCoaxAuthError as err:
                # Falsche Zugangsdaten sind kein transienter Fehler -> Reauth.
                raise ConfigEntryAuthFailed(str(err)) from err
            except (GoCoaxError, ClientError, TimeoutError, IndexError, KeyError) as err:
                last_exc = err
                _LOGGER.debug("Netzdaten von %s fehlgeschlagen: %s", client.host, err)
                continue
            self._primary = client
            break

        if network is None:
            raise UpdateFailed(f"kein Adapter erreichbar: {last_exc}")

        return await self._add_local_stats(network)

    async def _fetch_network(self, client: GoCoaxClient) -> MocaNetwork:
        """Netzwerkweite Register -- gelten unabhaengig vom befragten Adapter."""
        local = await client.async_local_info()
        node_ids = nodes_from_bitmask(local[LOCAL_NODE_BITMASK])

        net_info = {n: await client.async_net_info(n) for n in node_ids}
        nc_id = local[LOCAL_NC_ID] & 0xFF
        nc_ver = net_info[nc_id][NET_MOCA_VER] & 0xFF

        fmr_raw = {}
        for node in node_ids:
            version = 1 if min(nc_ver, net_info[node][NET_MOCA_VER] & 0xFF) < 0x20 else 2
            fmr_raw[node] = await client.async_fmr(node, version)

        rates_by_id, gcd_by_id = compute_phy_rates(local, net_info, fmr_raw)

        macs = {
            node: normalize_mac(
                mac_from_words(words[NET_MAC_HI], words[NET_MAC_LO])
            )
            for node, words in net_info.items()
        }

        nodes = {
            macs[node]: MocaNode(
                mac=macs[node],
                mac_pretty=format_mac(macs[node]),
                node_id=node,
                moca_version=moca_version(words[NET_MOCA_VER] & 0xFF),
                gcd=gcd_by_id.get(node),
                is_nc=node == nc_id,
            )
            for node, words in net_info.items()
        }

        # Raten auf MACs umschluesseln: Node-IDs sind nicht stabil.
        rates = {
            (macs[src], macs[dst]): rate
            for (src, dst), rate in rates_by_id.items()
            if src in macs and dst in macs
        }

        misc = await client.async_misc_phy()
        m25 = await client.async_m25_phy()
        lof = await client.async_lof()

        return MocaNetwork(
            link_up=bool(local[LOCAL_LINK_STATUS]),
            moca_version=moca_version(local[LOCAL_NET_MOCA_VER]),
            node_mask=local[LOCAL_NODE_BITMASK],
            nc_mac=macs.get(nc_id),
            nodes=nodes,
            rates=rates,
            beacon_channel=misc[1] if len(misc) > 1 else None,
            first_channel=m25[2] if len(m25) > 2 else None,
            num_channels=m25[3] if len(m25) > 3 else None,
            lof=lof[0] if lof else None,
        )

    async def _add_local_stats(self, network: MocaNetwork) -> MocaNetwork:
        """Ethernet-Zaehler je Adapter -- best effort.

        Ein toter Adapter macht seine eigenen Sensoren unavailable, invalidiert
        aber nicht den gesamten Poll: die netzwerkweiten Werte stehen ja.
        """
        for client in self._clients:
            mac = self._host_macs.get(client.host)
            if mac is None or mac not in network.nodes:
                continue
            try:
                words = await client.async_frame_info()
            except GoCoaxAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except (GoCoaxError, ClientError, TimeoutError, IndexError) as err:
                _LOGGER.debug("Zaehler von %s nicht lesbar: %s", client.host, err)
                network.unreachable.add(mac)
                continue

            node = network.nodes[mac]
            network.nodes[mac] = MocaNode(
                mac=node.mac,
                mac_pretty=node.mac_pretty,
                node_id=node.node_id,
                moca_version=node.moca_version,
                gcd=node.gcd,
                is_nc=node.is_nc,
                local=LocalStats(
                    tx_good=u64(words, FRAME_TX_GOOD),
                    tx_bad=u64(words, FRAME_TX_BAD),
                    tx_dropped=u64(words, FRAME_TX_DROPPED),
                    rx_good=u64(words, FRAME_RX_GOOD),
                    rx_bad=u64(words, FRAME_RX_BAD),
                    rx_dropped=u64(words, FRAME_RX_DROPPED),
                ),
            )
        return network

    @property
    def host_macs(self) -> dict[str, str]:
        """MAC je konfiguriertem Host -- nur diese liefern Ethernet-Zaehler."""
        return self._host_macs
