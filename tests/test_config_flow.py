"""Tests des Config Flows."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gocoax_moca.api import GoCoaxAuthError
from custom_components.gocoax_moca.const import CONF_PEERS, DOMAIN

MAC_A = "94cc0400aa01"
MAC_B = "94cc0400aa02"

USER_INPUT = {
    CONF_HOST: "192.0.2.10",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "gocoax",
}

PROBE_A = {"own_mac": MAC_A, "node_macs": {0: MAC_A, 1: MAC_B}, "chip_id": 0x16}
PROBE_B = {"own_mac": MAC_B, "node_macs": {0: MAC_A, 1: MAC_B}, "chip_id": 0x16}

PROBE = "custom_components.gocoax_moca.config_flow._probe"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


async def _start(hass, probe_side_effect):
    with patch(PROBE, side_effect=probe_side_effect):
        return await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )


async def test_full_flow_with_peer(hass):
    """Happy Path: Adapter eintragen, Peer-IP ergaenzen, Entry entsteht."""
    result = await _start(hass, [PROBE_A])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "peers"

    with (
        patch(PROBE, return_value=PROBE_B),
        patch("custom_components.gocoax_moca.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {MAC_B: "192.0.2.11"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PEERS] == {MAC_B: "192.0.2.11"}
    assert result["result"].unique_id == MAC_A


async def test_peer_can_be_left_empty(hass):
    """Ohne IP wird der Knoten trotzdem angelegt -- nur ohne Ethernet-Zaehler."""
    result = await _start(hass, [PROBE_A])

    with patch("custom_components.gocoax_moca.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {MAC_B: ""}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PEERS] == {}


async def test_wrong_peer_ip_is_rejected(hass):
    """Eine vertippte IP wuerde sonst Zaehler dem falschen Knoten zuordnen."""
    result = await _start(hass, [PROBE_A])

    # Unter der eingegebenen Adresse antwortet ein fremder Adapter.
    other = {"own_mac": "aabbccddeeff", "node_macs": {}, "chip_id": 0x16}
    with patch(PROBE, return_value=other):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {MAC_B: "192.0.2.99"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "peer_mac_mismatch"}


async def test_invalid_auth(hass):
    result = await _start(hass, GoCoaxAuthError("401"))
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect(hass):
    result = await _start(hass, ClientError("weg"))
    assert result["errors"] == {"base": "cannot_connect"}


async def test_unexpected_payload(hass):
    result = await _start(hass, IndexError("kaputt"))
    assert result["errors"] == {"base": "unknown"}


async def test_same_adapter_aborts(hass):
    MockConfigEntry(domain=DOMAIN, unique_id=MAC_A, data=USER_INPUT).add_to_hass(hass)

    result = await _start(hass, [PROBE_A])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_same_network_via_other_adapter_aborts(hass, device_registry):
    """Der unique_id-Check greift hier nicht: die Host-MACs unterscheiden sich."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="ffffffffffff", data=USER_INPUT)
    entry.add_to_hass(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, MAC_B)}
    )

    result = await _start(hass, [PROBE_A])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured_network"


async def test_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC_A, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with (
        patch(PROBE, return_value=PROBE_A),
        patch("custom_components.gocoax_moca.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "neu"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "neu"


async def test_reauth_rejects_bad_credentials(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC_A, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    with patch(PROBE, side_effect=GoCoaxAuthError("401")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "falsch"}
        )

    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_flow_sets_scan_interval(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC_A, data=USER_INPUT)
    entry.add_to_hass(hass)

    with patch("custom_components.gocoax_moca.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 60}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["scan_interval"] == 60


async def test_options_flow_can_add_peer_later(hass):
    """Wer die Peer-IP bei der Einrichtung leer laesst, muss sie nachtragen
    koennen -- ohne die Integration zu loeschen und neu anzulegen."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC_A,
        data={**USER_INPUT, CONF_PEERS: {MAC_B: ""}},
    )
    entry.add_to_hass(hass)

    with (
        patch(PROBE, return_value=PROBE_B),
        patch("custom_components.gocoax_moca.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 30, MAC_B: "192.0.2.11"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_PEERS] == {MAC_B: "192.0.2.11"}


async def test_options_flow_rejects_wrong_peer_ip(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC_A,
        data={**USER_INPUT, CONF_PEERS: {MAC_B: ""}},
    )
    entry.add_to_hass(hass)

    other = {"own_mac": "aabbccddeeff", "node_macs": {}, "chip_id": 0x16}
    with (
        patch(PROBE, return_value=other),
        patch("custom_components.gocoax_moca.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 30, MAC_B: "192.0.2.99"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "peer_mac_mismatch"}
    assert entry.data[CONF_PEERS] == {MAC_B: ""}


async def test_options_flow_rejects_too_short_interval(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MAC_A, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 1}
        )
