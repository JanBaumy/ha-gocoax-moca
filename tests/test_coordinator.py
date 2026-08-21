"""Tests des Coordinators: Failover, Fehlerklassifikation, Verfuegbarkeit.

Laeuft gegen den HA-Testharness. Achtung: der Harness zieht HA 2026.2, nicht
die Zielversion 2026.8 -- die benoetigt Python >= 3.14.2, das hier nicht
verfuegbar ist. Die genutzten APIs sind zwischen beiden Versionen stabil,
aber gruen heisst hier nicht "gegen 2026.8 verifiziert".
"""

from __future__ import annotations

import pytest
from aiohttp import ClientError
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gocoax_moca.api import GoCoaxAuthError, GoCoaxError
from custom_components.gocoax_moca.const import DOMAIN
from custom_components.gocoax_moca.coordinator import GoCoaxCoordinator

from .conftest import MAC_A, MAC_B, FakeClient  # noqa: F401


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Ohne dieses Fixture laedt HA keine custom_components im Test."""
    return


def _entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="94cc0400aa01")
    entry.add_to_hass(hass)
    return entry


async def _make(hass, clients):
    """Setup + erster Poll.

    async_config_entry_first_refresh() ist nur waehrend SETUP_IN_PROGRESS
    erlaubt, deshalb hier der explizite Zweischritt.
    """
    coordinator = GoCoaxCoordinator(hass, _entry(hass), clients, 30)
    await coordinator._async_setup()
    await coordinator.async_refresh()
    return coordinator


async def test_network_data_is_decoded(hass):
    a = FakeClient("192.0.2.10", MAC_A)
    coordinator = await _make(hass, [a])

    net = coordinator.data
    assert net.link_up is True
    assert net.moca_version == "2.5"
    assert set(net.nodes) == {"94cc0400aa01", "94cc0400aa02"}
    assert net.nc_mac == "94cc0400aa01"
    assert net.rates[("94cc0400aa01", "94cc0400aa02")].nper == 1220
    assert net.nodes["94cc0400aa01"].local is not None


async def test_failover_to_second_adapter(hass):
    """Faellt der primaere Adapter aus, uebernimmt der zweite -- ohne UpdateFailed."""
    a = FakeClient("192.0.2.10", MAC_A, fail=ClientError("tot"))
    b = FakeClient("192.0.2.11", MAC_B)

    coordinator = await _make(hass, [a, b])

    assert coordinator.last_update_success
    assert coordinator.data.link_up is True
    # Naechster Poll versucht den zuletzt erfolgreichen Host zuerst.
    assert coordinator._ordered_clients()[0] is b


async def test_dead_adapter_counters_are_none_not_zero(hass):
    """Der Kernpunkt: unavailable statt 0.

    Wuerden die Zaehler eines ausgefallenen Adapters 0 zeigen, saehe der
    Ausfall in der Historie wie ein Traffic-Einbruch aus.
    """
    a = FakeClient("192.0.2.10", MAC_A)
    b = FakeClient("192.0.2.11", MAC_B)
    b.frame_fail = ClientError("tot")

    coordinator = await _make(hass, [a, b])

    assert coordinator.data.nodes["94cc0400aa01"].local is not None
    assert coordinator.data.nodes["94cc0400aa02"].local is None
    assert "94cc0400aa02" in coordinator.data.unreachable


async def test_all_adapters_dead_raises_update_failed(hass):
    a = FakeClient("192.0.2.10", MAC_A, fail=GoCoaxError("weg"))
    coordinator = GoCoaxCoordinator(hass, _entry(hass), [a], 30)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_auth_error_triggers_reauth(hass):
    """401 ist kein transienter Fehler -- es muss den Reauth-Flow ausloesen."""
    a = FakeClient("192.0.2.10", MAC_A, fail=GoCoaxAuthError("401"))
    coordinator = GoCoaxCoordinator(hass, _entry(hass), [a], 30)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_unreachable_peer_at_setup_does_not_block(hass):
    """Ein beim Setup toter Peer darf die Integration nicht verhindern."""
    a = FakeClient("192.0.2.10", MAC_A)
    b = FakeClient("192.0.2.11", MAC_B)
    b.fail = ClientError("tot")

    coordinator = await _make(hass, [a, b])

    assert coordinator.last_update_success
    assert "192.0.2.10" in coordinator.host_macs
