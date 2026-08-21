"""GoCoax MoCA — Custom Integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GoCoaxClient
from .const import CONF_PEERS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .coordinator import GoCoaxConfigEntry, GoCoaxCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: GoCoaxConfigEntry) -> bool:
    """Richtet einen Config-Entry ein."""
    session = async_get_clientsession(hass)
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    # Der zuerst konfigurierte Host zuerst; die Peers dienen als Failover und
    # liefern zusaetzlich ihre eigenen Ethernet-Zaehler.
    hosts = [entry.data[CONF_HOST]]
    hosts += [h for h in entry.data.get(CONF_PEERS, {}).values() if h not in hosts]
    clients = [GoCoaxClient(session, host, username, password) for host in hosts]

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = GoCoaxCoordinator(hass, entry, clients, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GoCoaxConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: GoCoaxConfigEntry) -> None:
    """Optionsaenderung (Poll-Intervall, Peer-Hosts) -> Reload."""
    await hass.config_entries.async_reload(entry.entry_id)
