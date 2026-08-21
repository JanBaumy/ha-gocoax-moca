"""Lesender aiohttp-Client fuer die JSON-API eines MXL371x-Adapters.

Das Web-UI des Adapters ist eine reine JavaScript-Shell ueber dieser API.
Aufrufkonvention (am Geraet verifiziert):

    POST /ms/<iface>/<register>   Body: {"data":[...]}   ->  {"data":["0x..", ..]}

- HTTP Basic Auth, ohne -> 401
- CSRF: GET /devStatus.html liefert Set-Cookie csrf_token. Jedes POST braucht
  Cookie UND Header X-CSRF-TOKEN -- eines allein -> 400.
- Request-Content-Type muss x-www-form-urlencoded sein, obwohl der Body JSON ist.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from aiohttp import ClientSession, ClientTimeout

from .exceptions import GoCoaxAuthError, GoCoaxCsrfError
from .registers import READ_REGISTERS

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = ClientTimeout(total=10)


class GoCoaxClient:
    """Lesender Zugriff auf genau einen Adapter."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self.host = host
        self._base = f"http://{host}"
        # Header selbst bauen statt aiohttp.BasicAuth: das ist in aiohttp 3.14
        # deprecated, und der Ersatz existiert in aelteren Versionen nicht --
        # welche HA mitbringt, soll hier keine Rolle spielen.
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._auth_header = {"Authorization": f"Basic {token}"}
        self._csrf: str | None = None
        # Serialisiert alle Requests dieses Hosts. Liefen sie parallel, wuerde ein
        # rotiertes Token zu mehreren gleichzeitigen Refreshes fuehren, die sich
        # gegenseitig entwerten.
        self._lock = asyncio.Lock()

    async def _refresh_token(self) -> None:
        """Holt ein frisches CSRF-Token.

        Das Token rotiert, sobald parallel jemand das Web-UI oeffnet -- deshalb
        ist das kein reiner Setup-Schritt, sondern auch der Retry-Pfad.
        """
        async with self._session.get(
            f"{self._base}/devStatus.html",
            headers=self._auth_header,
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status == 401:
                raise GoCoaxAuthError(f"{self._base}: Basic Auth abgelehnt")
            resp.raise_for_status()
            # Direkt aus dem Set-Cookie-Header statt aus dem Cookie-Jar: der Jar
            # von async_get_clientsession ist mit allen Integrationen geteilt, und
            # aiohttp speichert Cookies fuer nackte IP-Hosts nur mit unsafe=True.
            for morsel in resp.cookies.values():
                if morsel.key == "csrf_token":
                    self._csrf = morsel.value
                    return
        raise GoCoaxCsrfError(f"{self._base}: kein csrf_token im Set-Cookie")

    async def _post(self, key: str, data: list[int] | None = None) -> list[int]:
        """Liest ein Register aus der Allowlist."""
        path = READ_REGISTERS[key]  # KeyError statt frei waehlbarer Pfad
        body = json.dumps({"data": data if data is not None else []})

        async with self._lock:
            if self._csrf is None:
                await self._refresh_token()

            for attempt in (1, 2):  # genau ein Retry
                async with self._session.post(
                    f"{self._base}{path}",
                    data=body,
                    headers={
                        **self._auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-CSRF-TOKEN": self._csrf or "",
                        "Cookie": f"csrf_token={self._csrf}",
                    },
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status == 401:
                        raise GoCoaxAuthError(f"{self._base}: Basic Auth abgelehnt")
                    if resp.status == 400:
                        if attempt == 1:
                            _LOGGER.debug("%s: 400, hole neues Token", path)
                            await self._refresh_token()
                            continue
                        # Zweites 400 trotz frischem Token: kein CSRF-Problem mehr,
                        # sondern ein falsches Argument fuer dieses Register.
                        raise GoCoaxCsrfError(
                            f"{self._base}{path}: 400 auch nach Token-Refresh"
                        )
                    resp.raise_for_status()
                    payload = await resp.json()
                return [int(word, 16) for word in payload["data"]]

        raise AssertionError("unerreichbar")  # pragma: no cover

    # -- Benannte Lesezugriffe -------------------------------------------------

    async def async_local_info(self) -> list[int]:
        """0x15: eigene NodeID, NC, Link, Netzversion, Node-Bitmask, SoC-Version."""
        return await self._post("local_info")

    async def async_net_info(self, node: int) -> list[int]:
        """0x16: MAC und MoCA-Version eines Knotens (netzwerkweit lesbar)."""
        return await self._post("net_info", [node])

    async def async_fmr(self, node: int, version: int) -> list[int]:
        """0x1D: FMR-Rohdaten eines Knotens, Grundlage der PHY-Raten."""
        return await self._post("fmr", [1 << node, version])

    async def async_frame_info(self) -> list[int]:
        """0x14: Ethernet-Zaehler -- nur fuer diesen Adapter selbst."""
        return await self._post("frame_info", [0])

    async def async_misc_phy(self) -> list[int]:
        """0x24: Beacon-Kanal."""
        return await self._post("misc_phy")

    async def async_m25_phy(self) -> list[int]:
        """0x7f: First Channel, Num Channels."""
        return await self._post("m25_phy")

    async def async_lof(self) -> list[int]:
        return await self._post("lof")

    async def async_own_mac(self) -> list[int]:
        """0x103: MAC des befragten Geraets (unabhaengig vom Argument)."""
        return await self._post("own_mac", [0])

    async def async_own_ip(self) -> list[int]:
        return await self._post("own_ip")

    async def async_chip_id(self) -> list[int]:
        return await self._post("chip_id", [0])
