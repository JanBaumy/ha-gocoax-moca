"""PHY-Raten aus FMR-Rohdaten.

Port der Berechnung aus phyRates.html des Adapter-Web-UI. Bewusst rein
rechnend: Eingabe sind bereits geholte Register, damit der kniffligste Teil
ohne Netzwerk und ohne HA testbar ist.

Deckt den MoCA-2.x-Pfad ab. Der Mix-Mode-GCD-Zweig (phyRates.html:259-263)
greift nur, wenn ein MoCA-1.x-Knoten im Netz ist, und ist nicht portiert --
fuer solche Knoten liefert `gcd` None statt einer erfundenen Zahl.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .decode import NET_MOCA_VER

_LOGGER = logging.getLogger(__name__)

MAX_NODES = 16

# Konstanten aus phyRates.html
LDPC_LEN_100MHZ = 3900
LDPC_LEN_50MHZ = 1200
FFT_LEN_100MHZ = 512
FFT_LEN_50MHZ = 256


@dataclass(frozen=True, slots=True)
class PhyRate:
    """Rate eines gerichteten Knotenpaars in Mbit/s."""

    nper: int
    vlper: int


def _rate_nper(gap: int, ofdmb: int, gap_vlper: int, payload_ver: int) -> int:
    if gap == 0:
        return 0
    if gap_vlper == 0 and payload_ver == 0x20:
        return (LDPC_LEN_50MHZ * ofdmb) // ((FFT_LEN_50MHZ + gap * 2 + 10) * 26)
    return (LDPC_LEN_100MHZ * ofdmb) // ((FFT_LEN_100MHZ + (gap + 10) * 2) * 46)


def _rate_vlper(gap: int, ofdmb: int) -> int:
    if gap == 0:
        return 0
    return (LDPC_LEN_100MHZ * ofdmb) // ((FFT_LEN_100MHZ + (gap + 10) * 2) * 46)


def compute_phy_rates(
    local: list[int],
    net_info: dict[int, list[int]],
    fmr_raw: dict[int, list[int]],
) -> tuple[dict[tuple[int, int], PhyRate], dict[int, int | None]]:
    """Berechnet die Ratenmatrix und die GCD-Rate je Knoten.

    Rueckgabe: ({(von, nach): PhyRate}, {node: gcd_oder_None})
    """
    node_mask = local[12]
    nc_moca_ver = net_info[local[1] & 0xFF][NET_MOCA_VER] & 0xFF

    rates: dict[tuple[int, int], PhyRate] = {}
    gcd: dict[int, int | None] = {}

    for i in sorted(net_info):
        node_ver = net_info[i][NET_MOCA_VER] & 0xFF
        entry_ver = min(node_ver, nc_moca_ver)
        read_idx = 10  # Startoffset in der FMR-Payload
        align = True
        gcd[i] = None

        # WICHTIG: ueber alle 16 Slots iterieren, nicht nur ueber die aktiven.
        # Abwesende Knoten verschieben read_idx mit, und align togglet bei jedem
        # Slot. Wer nur ueber die vorhandenen Knoten laeuft, bekommt fuer jeden
        # Knoten hinter einer Luecke plausible, aber falsche Zahlen.
        for j in range(MAX_NODES):
            if not (node_mask & (1 << j)):
                if node_ver >= 0x20:
                    read_idx += 1 if align else 2
                elif not align:
                    read_idx += 1
                align = not align
                continue

            if nc_moca_ver < 0x20:
                payload_ver = min(entry_ver, net_info[j][NET_MOCA_VER] & 0xFF)
            else:
                payload_ver = node_ver

            words = fmr_raw[i]
            if payload_ver in (0x20, 0x25):
                if align:
                    gap_nper = (words[read_idx] >> 24) & 0xFF
                    gap_vlper = (words[read_idx] >> 16) & 0xFF
                    ofdmb_nper = words[read_idx] & 0xFFFF
                    ofdmb_vlper = (words[read_idx + 1] >> 16) & 0xFFFF
                    read_idx += 1
                else:
                    gap_nper = (words[read_idx] >> 8) & 0xFF
                    gap_vlper = words[read_idx] & 0xFF
                    ofdmb_nper = (words[read_idx + 1] >> 16) & 0xFFFF
                    ofdmb_vlper = words[read_idx + 1] & 0xFFFF
                    read_idx += 2
            else:
                # MoCA 1.x: kein VLPER im Payload
                gap_vlper = 0
                ofdmb_vlper = 0
                if align:
                    gap_nper = (words[read_idx] & 0xF8000000) >> 27
                    ofdmb_nper = (words[read_idx] & 0x07FF0000) >> 16
                else:
                    gap_nper = (words[read_idx] & 0x0000F800) >> 11
                    ofdmb_nper = words[read_idx] & 0x000007FF
                    read_idx += 1

            align = not align

            rates[(i, j)] = PhyRate(
                nper=_rate_nper(gap_nper, ofdmb_nper, gap_vlper, payload_ver),
                vlper=_rate_vlper(gap_vlper, ofdmb_vlper),
            )

            if i == j:
                if node_ver & 0xF0 == 0x20:
                    gcd[i] = (LDPC_LEN_100MHZ * ofdmb_nper) // (
                        (FFT_LEN_100MHZ + (gap_nper + 10) * 2) * 46
                    )
                elif node_ver & 0xF0 == 0x10:
                    # Reiner 1.x-Knoten: der Mix-Mode-Zweig fehlt, also lieber
                    # kein Wert als ein falscher.
                    _LOGGER.warning(
                        "Knoten %s meldet MoCA 1.x -- GCD wird nicht berechnet", i
                    )

    return rates, gcd
