"""End-to-End-Setup: Entry laden, Entities pruefen, Knoten kommen und gehen.

Laeuft gegen HA 2026.2 (Testharness), nicht gegen 2026.8.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gocoax_moca.const import CONF_PEERS, DOMAIN

from .conftest import MAC_A, MAC_B, FakeClient  # noqa: F401

MAC_A_NORM = "94cc0400aa01"
MAC_B_NORM = "94cc0400aa02"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


async def _setup(hass, clients):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC_A_NORM,
        data={
            CONF_HOST: "192.0.2.10",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "gocoax",
            CONF_PEERS: {MAC_B_NORM: "192.0.2.11"},
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.gocoax_moca.GoCoaxClient",
        side_effect=lambda session, host, user, pw: clients[host],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_entry_loads_and_creates_entities(hass, fake_clients, entity_registry):
    entry = await _setup(hass, fake_clients)
    assert entry.state is ConfigEntryState.LOADED

    entities = {
        e.unique_id: e
        for e in entity_registry.entities.get_entries_for_config_entry_id(
            entry.entry_id
        )
    }

    # Netz-Device
    assert f"net_{MAC_A_NORM}_link" in entities
    assert f"net_{MAC_A_NORM}_node_count" in entities
    # Knoten-Device, beide Adapter
    assert f"{MAC_A_NORM}_gcd" in entities
    assert f"{MAC_B_NORM}_gcd" in entities
    # Gerichtete PHY-Raten, keine Node-IDs im unique_id
    assert f"{MAC_A_NORM}_{MAC_B_NORM}_phy_nper" in entities
    assert f"{MAC_B_NORM}_{MAC_A_NORM}_phy_nper" in entities
    # VLPER ist standardmaessig deaktiviert
    assert entities[f"{MAC_A_NORM}_{MAC_B_NORM}_phy_vlper"].disabled_by is not None
    # Fehlerzaehler sind standardmaessig aktiv, good-Zaehler nicht
    assert entities[f"{MAC_A_NORM}_rx_bad"].disabled_by is None
    assert entities[f"{MAC_A_NORM}_rx_good"].disabled_by is not None


async def test_states_match_the_recorded_hardware(hass, fake_clients):
    await _setup(hass, fake_clients)

    link = hass.states.get("binary_sensor.moca_netzwerk_link")
    assert link is not None and link.state == "on"

    rates = [
        s for s in hass.states.async_all("sensor") if s.attributes.get("device_class") == "data_rate"
    ]
    values = sorted(int(s.state) for s in rates if s.state not in ("unknown", "unavailable"))
    # Zwei GCD-Werte (~590) und zwei gerichtete PHY-Raten (~1200).
    assert values[-1] > 1100
    assert values[0] < 700


async def test_dead_peer_makes_its_counters_unavailable(hass, fake_clients):
    """Der Kernpunkt der Verfuegbarkeitslogik -- unavailable, nicht 0."""
    fake_clients["192.0.2.11"].frame_fail = ClientError("tot")
    await _setup(hass, fake_clients)

    # rx_bad des lebenden Adapters hat einen Wert ...
    alive = hass.states.get("sensor.moca_adapter_94_cc_04_00_aa_01_ethernet_rx_fehlerhaft")
    # ... der des toten nicht. Entity-IDs haengen an den Uebersetzungen, deshalb
    # ueber die Registry statt ueber geratene IDs.
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    dead_id = registry.async_get_entity_id("sensor", DOMAIN, f"{MAC_B_NORM}_rx_bad")
    assert dead_id is not None
    assert hass.states.get(dead_id).state == "unavailable"

    alive_id = registry.async_get_entity_id("sensor", DOMAIN, f"{MAC_A_NORM}_rx_bad")
    assert hass.states.get(alive_id).state == "0"
    assert alive is None or alive.state != "unavailable"


async def test_unload(hass, fake_clients):
    entry = await _setup(hass, fake_clients)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
