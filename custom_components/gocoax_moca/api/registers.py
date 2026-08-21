"""Erlaubte Leseregister der MXL371x-JSON-API.

Bewusst eingefroren: im selben Adressraum liegen PUT-Schreibzugriffe und der
Reboot-Aufruf (/ms/1/0xb00, /ms/1/0xb01). Der Client kennt keinen frei
waehlbaren Pfad, sondern nur die Schluessel aus dieser Tabelle -- damit kann
keine spaetere Aenderung versehentlich schreibend zugreifen.

Alle Eintraege sind am Geraet verifiziert und stammen aus dem Web-UI.
"""

from __future__ import annotations

from types import MappingProxyType

READ_REGISTERS = MappingProxyType(
    {
        "local_info": "/ms/0/0x15",  # NodeID, NC, Link, Netzversion, Bitmask, SoC
        "net_info": "/ms/0/0x16",  # je Knoten: MAC, MoCA-Version
        "fmr": "/ms/0/0x1D",  # FMR-Rohdaten -> PHY-Raten
        "frame_info": "/ms/0/0x14",  # Ethernet-Zaehler (nur lokal)
        "misc_phy": "/ms/0/0x24",  # Beacon-Kanal
        "m25_phy": "/ms/0/0x7f",  # First Channel, Num Channels
        "lof": "/ms/0/0x1003/GET",
        "own_mac": "/ms/1/0x103/GET",
        "own_ip": "/ms/1/0x20b/GET",
        "chip_id": "/ms/1/0x303/GET",
    }
)
