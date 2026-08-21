"""Gemeinsame Test-Fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Das api-Paket direkt einbinden -- custom_components/gocoax_moca/__init__.py
# importiert homeassistant und laesst sich hier nicht laden.
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "gocoax_moca")
)

FIXTURES = Path(__file__).parent / "fixtures"

MAC_A = [0x94CC0400, 0xAA010000]  # Knoten 0
MAC_B = [0x94CC0400, 0xAA020000]  # Knoten 1


def load_fixture(name: str) -> dict:
    """Laedt eine Rohregister-Aufzeichnung und normalisiert die Knoten-Keys."""
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    data["net_info"] = {int(k): v for k, v in data["net_info"].items()}
    data["fmr"] = {int(k): v for k, v in data["fmr"].items()}
    return data


@pytest.fixture
def live_2nodes() -> dict:
    """Echte Aufzeichnung von 192.0.2.10 (Knoten 0 und 1, lueckenlos)."""
    return load_fixture("live_2nodes")


@pytest.fixture
def synth_gap() -> dict:
    """Synthetisch: Bitmask 0b1101, Slot 1 leer -- prueft die read_idx-Falle."""
    return load_fixture("synth_gap")


class FakeClient:
    """Client-Ersatz, der aus der Live-Fixture antwortet."""

    def __init__(self, host: str, mac_words: list[int], *, fail: Exception | None = None):
        self.host = host
        self._mac_words = mac_words
        self.fail = fail
        self.frame_fail: Exception | None = None
        raw = json.loads((FIXTURES / "live_2nodes.json").read_text())
        self._local = raw["local_info"]
        self._net = {int(k): v for k, v in raw["net_info"].items()}
        self._fmr = {int(k): v for k, v in raw["fmr"].items()}
        self._frame = raw["frame_info"]
        self._misc = raw["misc_phy"]
        self._m25 = raw["m25_phy"]
        self._lof = raw["lof"]

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    async def async_own_mac(self):
        return self._mac_words

    async def async_local_info(self):
        self._check()
        return self._local

    async def async_net_info(self, node):
        self._check()
        return self._net[node]

    async def async_fmr(self, node, version):
        self._check()
        return self._fmr[node]

    async def async_misc_phy(self):
        self._check()
        return self._misc

    async def async_m25_phy(self):
        self._check()
        return self._m25

    async def async_lof(self):
        self._check()
        return self._lof

    async def async_frame_info(self):
        if self.frame_fail is not None:
            raise self.frame_fail
        self._check()
        return self._frame



@pytest.fixture
def fake_clients():
    """Beide Adapter, antwortend aus der Live-Fixture."""
    return {
        "192.0.2.10": FakeClient("192.0.2.10", MAC_A),
        "192.0.2.11": FakeClient("192.0.2.11", MAC_B),
    }
