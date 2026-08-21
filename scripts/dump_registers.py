#!/usr/bin/env python3
"""Rohregister eines Adapters auslesen.

Zwei Zwecke:
  * ohne Flag  -> JSON-Dump als Test-Fixture (tests/fixtures/)
  * --decode   -> dekodierte Werte zum Abgleich mit /root/plans/gocoax_api.py

Nur lesende Zugriffe.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Das api-Paket direkt einbinden: custom_components/gocoax_moca/__init__.py
# importiert homeassistant und ist hier nicht ladbar.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "gocoax_moca"))

from aiohttp import ClientSession  # noqa: E402
from api import GoCoaxClient  # noqa: E402
from api.decode import (  # noqa: E402
    FRAME_RX_BAD,
    FRAME_RX_DROPPED,
    FRAME_RX_GOOD,
    FRAME_TX_BAD,
    FRAME_TX_DROPPED,
    FRAME_TX_GOOD,
    mac_from_words,
    moca_version,
    nodes_from_bitmask,
    soc_version,
    u64,
)
from api.fmr import compute_phy_rates  # noqa: E402


async def collect(host: str, user: str, password: str) -> dict:
    async with ClientSession() as session:
        client = GoCoaxClient(session, host, user, password)
        local = await client.async_local_info()
        nodes = nodes_from_bitmask(local[12])

        net_info = {n: await client.async_net_info(n) for n in nodes}
        nc_ver = net_info[local[1] & 0xFF][4] & 0xFF

        fmr = {}
        for n in nodes:
            ver = 1 if min(nc_ver, net_info[n][4] & 0xFF) < 0x20 else 2
            fmr[n] = await client.async_fmr(n, ver)

        return {
            "host": host,
            "local_info": local,
            "net_info": {str(k): v for k, v in net_info.items()},
            "fmr": {str(k): v for k, v in fmr.items()},
            "frame_info": await client.async_frame_info(),
            "misc_phy": await client.async_misc_phy(),
            "m25_phy": await client.async_m25_phy(),
            "lof": await client.async_lof(),
            "own_mac": await client.async_own_mac(),
            "own_ip": await client.async_own_ip(),
            "chip_id": await client.async_chip_id(),
        }


def show(data: dict) -> None:
    local = data["local_info"]
    net_info = {int(k): v for k, v in data["net_info"].items()}
    fmr = {int(k): v for k, v in data["fmr"].items()}

    print(f"Host {data['host']}")
    print(f"  eigene NodeID {local[0]}   NC {local[1]}   Link {'Up' if local[5] else 'Down'}")
    print(f"  Netz-MoCA {moca_version(local[11])}   SoC {soc_version(local)!r}")
    print(f"  Node-Bitmask 0x{local[12]:x} -> Knoten {nodes_from_bitmask(local[12])}")
    print(f"  Beacon-Kanal {data['misc_phy'][1]} MHz   ChipID 0x{data['chip_id'][0]:x}")

    for node, words in sorted(net_info.items()):
        mac = mac_from_words(words[0], words[1])
        print(f"  Knoten {node}: MAC {mac}  MoCA {moca_version(words[4] & 0xFF)}")

    rates, gcd = compute_phy_rates(local, net_info, fmr)
    print("\nPHY-Raten NPER/VLPER (Mbit/s):")
    for (src, dst), rate in sorted(rates.items()):
        print(f"  {src} -> {dst}: {rate.nper:5d} / {rate.vlper:5d}")
    print(f"GCD je Knoten: {gcd}")

    fi = data["frame_info"]
    print(f"\nEthernet Tx good/bad/dropped: {u64(fi, FRAME_TX_GOOD)} / "
          f"{u64(fi, FRAME_TX_BAD)} / {u64(fi, FRAME_TX_DROPPED)}")
    print(f"Ethernet Rx good/bad/dropped: {u64(fi, FRAME_RX_GOOD)} / "
          f"{u64(fi, FRAME_RX_BAD)} / {u64(fi, FRAME_RX_DROPPED)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("host")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="gocoax")
    ap.add_argument("--decode", action="store_true", help="dekodiert ausgeben statt JSON")
    ap.add_argument("--out", type=Path, help="JSON-Dump in diese Datei schreiben")
    args = ap.parse_args()

    data = asyncio.run(collect(args.host, args.user, args.password))
    if args.decode:
        show(data)
    elif args.out:
        args.out.write_text(json.dumps(data, indent=2) + "\n")
        print(f"geschrieben: {args.out}")
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
