"""Tests des aiohttp-Transports: Auth, CSRF-Retry, Serialisierung, Allowlist.

Getestet wird gegen einen echten lokalen aiohttp-Server statt gegen einen
HTTP-Mock. Das ist hier bewusst so: der riskante Teil ist die Cookie- und
Header-Behandlung, und die will man auf dem realen HTTP-Pfad pruefen.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field

import pytest
from aiohttp import ClientSession, web
from api import GoCoaxAuthError, GoCoaxClient, GoCoaxCsrfError
from api.registers import READ_REGISTERS

PAYLOAD = '{\n"data":["0x00000000","0x00000001"]\n}'


@dataclass
class FakeAdapter:
    """Nachbau des Adapter-Verhaltens, so wie es am Geraet verifiziert wurde."""

    token: str = "TOKEN-1"
    status_status: int = 200
    send_cookie: bool = True
    # Antwortcodes fuer aufeinanderfolgende POSTs; danach immer 200.
    post_statuses: list[int] = field(default_factory=list)
    require_valid_token: bool = True

    get_calls: int = 0
    post_calls: int = 0
    seen_headers: list[dict] = field(default_factory=list)

    async def handle_status(self, request: web.Request) -> web.Response:
        self.get_calls += 1
        if self.status_status == 401:
            return web.Response(status=401, text="401 Unauthorized")
        headers = {}
        if self.send_cookie:
            headers["Set-Cookie"] = f"csrf_token={self.token}; SameSite=Strict"
        return web.Response(status=200, text="<html></html>", headers=headers)

    async def handle_post(self, request: web.Request) -> web.Response:
        self.post_calls += 1
        self.seen_headers.append(dict(request.headers))

        if self.post_statuses:
            status = self.post_statuses.pop(0)
            if status != 200:
                return web.Response(status=status, text="")

        if self.require_valid_token:
            # Beides muss stimmen -- genau wie am echten Geraet.
            header_token = request.headers.get("X-CSRF-TOKEN")
            cookie_token = request.cookies.get("csrf_token")
            if header_token != self.token or cookie_token != self.token:
                return web.Response(status=400, text="")

        return web.Response(
            status=200, text=PAYLOAD, content_type="application/json"
        )


@pytest.fixture(autouse=True)
def allow_local_sockets():
    """Diese Tests sprechen einen echten lokalen Server an.

    Laeuft die Suite zusammen mit pytest-homeassistant-custom-component, blockt
    dessen pytest-socket alle Sockets -- fuer dieses Modul wird das aufgehoben.
    """
    try:
        import pytest_socket
    except ImportError:
        return
    pytest_socket.enable_socket()


@pytest.fixture
async def adapter():
    return FakeAdapter()


@pytest.fixture
async def client(adapter, aiohttp_server):
    app = web.Application()
    app.router.add_get("/devStatus.html", adapter.handle_status)
    app.router.add_post("/ms/0/0x15", adapter.handle_post)
    server = await aiohttp_server(app)

    async with ClientSession() as session:
        yield GoCoaxClient(
            session, f"{server.host}:{server.port}", "admin", "gocoax"
        )


async def test_happy_path_sends_auth_cookie_and_header(client, adapter):
    """Beide CSRF-Traeger muessen mit -- eines allein quittiert das Geraet mit 400."""
    assert await client.async_local_info() == [0, 1]

    headers = adapter.seen_headers[-1]
    expected = base64.b64encode(b"admin:gocoax").decode()
    assert headers["Authorization"] == f"Basic {expected}"
    assert headers["X-CSRF-TOKEN"] == "TOKEN-1"
    assert headers["Cookie"] == "csrf_token=TOKEN-1"
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"


async def test_rotated_token_triggers_exactly_one_retry(client, adapter):
    """Oeffnet jemand parallel das Web-UI, rotiert das Token -> 400, dann Retry."""
    adapter.post_statuses = [400]

    assert await client.async_local_info() == [0, 1]
    assert adapter.post_calls == 2
    assert adapter.get_calls == 2


async def test_400_after_refresh_raises(client, adapter):
    """Zweites 400 trotz frischem Token ist kein CSRF-Problem mehr."""
    adapter.post_statuses = [400, 400]

    with pytest.raises(GoCoaxCsrfError):
        await client.async_local_info()
    assert adapter.post_calls == 2  # genau ein Retry, kein Dauerschleifen


async def test_401_on_post_raises_auth_error(client, adapter):
    adapter.post_statuses = [401]

    with pytest.raises(GoCoaxAuthError):
        await client.async_local_info()


async def test_401_on_token_fetch_raises_auth_error(client, adapter):
    adapter.status_status = 401

    with pytest.raises(GoCoaxAuthError):
        await client.async_local_info()


async def test_missing_cookie_raises_csrf_error(client, adapter):
    adapter.send_cookie = False

    with pytest.raises(GoCoaxCsrfError):
        await client.async_local_info()


async def test_parallel_calls_refresh_token_only_once(client, adapter):
    """Ohne Lock wuerden parallele 400er mehrere Refreshes ausloesen, die sich
    gegenseitig entwerten. Der Lock serialisiert alle Requests eines Hosts."""
    adapter.post_statuses = [400]

    results = await asyncio.gather(*(client.async_local_info() for _ in range(5)))

    assert results == [[0, 1]] * 5
    assert adapter.get_calls == 2  # einmal initial, einmal nach dem 400
    assert adapter.post_calls == 6  # 5 Aufrufe + 1 Retry


def test_allowlist_contains_no_write_access():
    """Strukturelle Absicherung: im selben Adressraum liegen PUT und Reboot."""
    for path in READ_REGISTERS.values():
        assert "PUT" not in path
        assert "0xb00" not in path
        assert "0xb01" not in path


async def test_unknown_register_key_is_rejected(client):
    """Kein frei waehlbarer Pfad -- unbekannte Schluessel scheitern hart."""
    with pytest.raises(KeyError):
        await client._post("reboot")
