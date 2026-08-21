"""Config Flow: Einrichtung, Peers, Reauth, Reconfigure, Optionen."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .api import GoCoaxAuthError, GoCoaxClient, GoCoaxError
from .api.decode import (
    LOCAL_NODE_BITMASK,
    NET_MAC_HI,
    NET_MAC_LO,
    mac_from_words,
    nodes_from_bitmask,
    normalize_mac,
)
from .const import (
    CHIP_ID_MXL371X,
    CONF_PEERS,
    CONF_SCAN_INTERVAL,
    DEFAULT_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import GoCoaxConfigEntry

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
    }
)


async def _probe(hass, host: str, username: str, password: str) -> dict[str, Any]:
    """Liest Identitaet und Knotenliste eines Adapters.

    Rueckgabe: {"own_mac": str, "node_macs": {node_id: mac}, "chip_id": int}
    """
    session = async_get_clientsession(hass)
    client = GoCoaxClient(session, host, username, password)

    own = await client.async_own_mac()
    own_mac = normalize_mac(mac_from_words(own[0], own[1]))
    chip_id = (await client.async_chip_id())[0]

    local = await client.async_local_info()
    node_macs = {}
    for node in nodes_from_bitmask(local[LOCAL_NODE_BITMASK]):
        words = await client.async_net_info(node)
        node_macs[node] = normalize_mac(
            mac_from_words(words[NET_MAC_HI], words[NET_MAC_LO])
        )

    return {"own_mac": own_mac, "node_macs": node_macs, "chip_id": chip_id}


class GoCoaxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ein Config-Entry steht fuer ein ganzes MoCA-Netz."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._node_macs: dict[int, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _probe(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except GoCoaxAuthError:
                errors["base"] = "invalid_auth"
            except (GoCoaxError, ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except (IndexError, KeyError, ValueError):
                _LOGGER.exception("Unerwartete Antwort von %s", user_input[CONF_HOST])
                errors["base"] = "unknown"
            else:
                if info["chip_id"] != CHIP_ID_MXL371X:
                    # Kein Abbruch: die Feldindizes sind nur fuer MXL371x belegt,
                    # aber verwandte Chips koennen trotzdem funktionieren.
                    _LOGGER.warning(
                        "Unerwartete ChipID 0x%x -- Feldindizes sind nur fuer "
                        "MXL371x belegt",
                        info["chip_id"],
                    )

                await self.async_set_unique_id(info["own_mac"])
                self._abort_if_unique_id_configured()

                if self._network_already_configured(info["node_macs"].values()):
                    return self.async_abort(reason="already_configured_network")

                self._data = dict(user_input)
                self._node_macs = info["node_macs"]
                return await self.async_step_peers()

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    def _network_already_configured(self, node_macs) -> bool:
        """Wurde dasselbe Netz schon ueber einen anderen Adapter angelegt?

        Der unique_id-Check greift dafuer nicht: die Host-MACs unterscheiden
        sich, obwohl es dasselbe Netz ist.
        """
        registry = async_get_device_registry(self.hass)
        for mac in node_macs:
            device = registry.async_get_device(identifiers={(DOMAIN, mac)})
            if device is not None:
                return True
        return False

    async def async_step_peers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionale IPs der weiteren Adapter.

        MoCA transportiert nur die MAC, nicht die IP -- HA kann sie also nicht
        selbst herausfinden. Ohne IP wird der Knoten trotzdem angelegt, ihm
        fehlen dann nur die Ethernet-Zaehler.
        """
        own_mac = normalize_mac(self.unique_id or "")
        peers = {
            mac: node for node, mac in self._node_macs.items() if mac != own_mac
        }

        if not peers:
            return self._create_entry({})

        errors: dict[str, str] = {}
        if user_input is not None:
            configured: dict[str, str] = {}
            for mac in peers:
                host = (user_input.get(mac) or "").strip()
                if not host:
                    continue
                try:
                    info = await _probe(
                        self.hass,
                        host,
                        self._data[CONF_USERNAME],
                        self._data[CONF_PASSWORD],
                    )
                except GoCoaxAuthError:
                    errors["base"] = "invalid_auth"
                    break
                except (GoCoaxError, ClientError, TimeoutError):
                    errors["base"] = "cannot_connect"
                    break
                # Eine vertippte IP wuerde sonst die Ethernet-Zaehler eines
                # fremden Adapters still dem falschen Knoten zuordnen.
                if info["own_mac"] != mac:
                    errors["base"] = "peer_mac_mismatch"
                    break
                configured[mac] = host
            else:
                return self._create_entry(configured)

        schema = vol.Schema(
            {vol.Optional(mac, default=""): str for mac in peers}
        )
        return self.async_show_form(
            step_id="peers",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "peers": ", ".join(sorted(peers)),
            },
        )

    def _create_entry(self, peers: dict[str, str]) -> ConfigFlowResult:
        return self.async_create_entry(
            title=f"MoCA-Netz ({self._data[CONF_HOST]})",
            data={**self._data, CONF_PEERS: peers},
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _probe(
                    self.hass,
                    entry.data[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except GoCoaxAuthError:
                errors["base"] = "invalid_auth"
            except (GoCoaxError, ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """IP-Wechsel (DHCP). Unkritisch, weil die Identitaet an der MAC haengt."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _probe(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except GoCoaxAuthError:
                errors["base"] = "invalid_auth"
            except (GoCoaxError, ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                if info["own_mac"] != entry.unique_id:
                    errors["base"] = "wrong_device"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates=user_input
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, entry.data
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: GoCoaxConfigEntry) -> OptionsFlow:
        return GoCoaxOptionsFlow()


class GoCoaxOptionsFlow(OptionsFlow):
    """Poll-Intervall und die IPs der weiteren Adapter.

    Die Peer-IPs gehoeren hierher und nicht nur in den Einrichtungsdialog: wer
    sie dort leer laesst -- was ausdruecklich erlaubt ist -- soll sie spaeter
    nachtragen koennen, ohne die Integration neu anzulegen.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        peers = self._known_peers()
        errors: dict[str, str] = {}

        if user_input is not None:
            configured: dict[str, str] = {}
            for mac in peers:
                host = (user_input.get(mac) or "").strip()
                if not host:
                    continue
                try:
                    info = await _probe(
                        self.hass,
                        host,
                        self.config_entry.data[CONF_USERNAME],
                        self.config_entry.data[CONF_PASSWORD],
                    )
                except GoCoaxAuthError:
                    errors["base"] = "invalid_auth"
                    break
                except (GoCoaxError, ClientError, TimeoutError):
                    errors["base"] = "cannot_connect"
                    break
                if info["own_mac"] != mac:
                    errors["base"] = "peer_mac_mismatch"
                    break
                configured[mac] = host
            else:
                # Peers liegen im Entry-Data (der Setup-Pfad schreibt sie dort),
                # das Intervall in den Optionen.
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_PEERS: configured},
                )
                return self.async_create_entry(
                    data={CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]}
                )

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        known_hosts = self.config_entry.data.get(CONF_PEERS, {})
        schema = {
            vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
            )
        }
        for mac in peers:
            schema[vol.Optional(mac, default=known_hosts.get(mac, ""))] = str

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema), errors=errors
        )

    def _known_peers(self) -> list[str]:
        """MACs aller Knoten ausser dem Host des Entries.

        Quelle ist der letzte Poll; ist die Integration nicht geladen, bleiben
        die bereits konfigurierten Peers uebrig.
        """
        own = self.config_entry.unique_id
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is not None and coordinator.data is not None:
            return sorted(mac for mac in coordinator.data.nodes if mac != own)
        return sorted(self.config_entry.data.get(CONF_PEERS, {}))
