"""Diagnose-Export: Rohregister, Zugangsdaten redigiert."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import GoCoaxConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GoCoaxConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    network = coordinator.data

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "network": {
            "link_up": network.link_up,
            "moca_version": network.moca_version,
            "node_mask": hex(network.node_mask),
            "nc_mac": network.nc_mac,
            "beacon_channel": network.beacon_channel,
            "first_channel": network.first_channel,
            "num_channels": network.num_channels,
            "lof": network.lof,
            "unreachable": sorted(network.unreachable),
        },
        "nodes": {
            mac: {
                "node_id": node.node_id,
                "moca_version": node.moca_version,
                "gcd": node.gcd,
                "is_nc": node.is_nc,
                "local": None if node.local is None else asdict(node.local),
            }
            for mac, node in network.nodes.items()
        },
        "rates": {
            f"{src}->{dst}": {"nper": rate.nper, "vlper": rate.vlper}
            for (src, dst), rate in network.rates.items()
        },
        "host_macs": coordinator.host_macs,
    }
