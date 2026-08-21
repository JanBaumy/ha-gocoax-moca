"""Dekodierung der rohen 32-Bit-Woerter aus der JSON-API."""

from __future__ import annotations

# Feldindizes, alle aus devStatus.html / phyRates.html belegt.
LOCAL_NODE_ID = 0
LOCAL_NC_ID = 1
LOCAL_LINK_STATUS = 5
LOCAL_NET_MOCA_VER = 11
LOCAL_NODE_BITMASK = 12
LOCAL_SOC_VERSION = 21

NET_MAC_HI = 0
NET_MAC_LO = 1
NET_MOCA_VER = 4

# frameInfo: 64-Bit-Zaehler, jeweils high word + low word.
FRAME_TX_GOOD = 12
FRAME_TX_BAD = 30
FRAME_TX_DROPPED = 48
FRAME_RX_GOOD = 66
FRAME_RX_BAD = 84
FRAME_RX_DROPPED = 102


def u64(words: list[int], index: int) -> int:
    """Setzt einen 64-Bit-Zaehler aus zwei aufeinanderfolgenden Woertern zusammen."""
    return (words[index] << 32) | words[index + 1]


def mac_from_words(hi: int, lo: int) -> str:
    """MAC aus zwei Woertern; die unteren 16 Bit von `lo` sind ungenutzt."""
    raw = f"{hi:08x}{lo >> 16:04x}"
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


def normalize_mac(mac: str) -> str:
    """Trennzeichenfreie Kleinschreibung -- Form fuer Device-Identifier."""
    return mac.replace(":", "").replace("-", "").lower()


def moca_version(raw: int) -> str:
    """0x25 -> '2.5'."""
    return f"{(raw >> 4) & 0xF}.{raw & 0xF}"


def soc_version(words: list[int], start: int = LOCAL_SOC_VERSION) -> str:
    """Liest den ASCII-String, der ab `start` in den Woertern steckt.

    Das Web-UI liest so lange weiter, bis ein Wort keine druckbaren
    ASCII-Bytes mehr liefert.
    """
    out: list[str] = []
    for word in words[start:]:
        chunk = ""
        for shift in (24, 16, 8, 0):
            byte = (word >> shift) & 0xFF
            if not 0 < byte < 0x80:
                break
            chunk += chr(byte)
        if not chunk:
            break
        out.append(chunk)
        if len(chunk) < 4:  # abgeschnitten -> String ist zu Ende
            break
    return "".join(out)


def nodes_from_bitmask(bitmask: int, max_nodes: int = 16) -> list[int]:
    """Node-IDs, deren Bit in der Bitmask gesetzt ist."""
    return [n for n in range(max_nodes) if bitmask & (1 << n)]
