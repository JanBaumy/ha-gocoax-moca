"""Konstanten der Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "gocoax_moca"

CONF_PEERS: Final = "peers"  # {mac: host} fuer Adapter mit bekannter IP

DEFAULT_USERNAME: Final = "admin"
DEFAULT_PASSWORD: Final = "gocoax"
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300

CONF_SCAN_INTERVAL: Final = "scan_interval"

# ChipID 0x16 = MXL371x. Abweichende Werte sind kein Abbruchgrund, aber eine
# Warnung wert -- die Feldindizes sind nur fuer diese Familie belegt.
CHIP_ID_MXL371X: Final = 0x16
