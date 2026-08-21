# GoCoax MoCA — Home Assistant Custom Integration

[![hacs][hacs-badge]][hacs-url]
[![license][license-badge]](LICENSE)

Monitors GoCoax / MaxLinear MoCA adapters (MXL371x) through the JSON API behind
their web interface.

No web scraping: the PHY rates are not in the HTML at all — the web UI computes
them in the browser from raw FMR data. This integration does that calculation
directly, which also makes values available that a scraper never sees, above all
the **GCD rate** and the **error counters**.

## Requirements

- Home Assistant **2026.8** or newer (which requires Python ≥ 3.14.2)
- At least one reachable adapter with its web interface enabled

## Installation

### Via HACS (recommended)

This integration is not in the HACS default store, so it has to be added as a
custom repository once:

1. In Home Assistant, open **HACS** from the sidebar.
2. Click the **⋮** menu in the top right and choose **Custom repositories**.
3. Paste `https://github.com/JanBaumy/ha-gocoax-moca` into **Repository**,
   select **Integration** as the **Type**, and click **Add**.
4. Close the dialog, search HACS for **GoCoax MoCA** and open it.
5. Click **Download** and confirm the version.
6. **Restart Home Assistant** — a custom integration is only picked up on start.

Once HACS knows the repository, future updates show up in HACS like those of any
other integration.

### Manually

Copy `custom_components/gocoax_moca/` into the `custom_components/` directory of
your Home Assistant configuration, so that `configuration.yaml` and
`custom_components/gocoax_moca/manifest.json` sit in the same config folder.
Then restart Home Assistant.

### Setup

After the restart, go to **Settings → Devices & Services → Add Integration** and
search for **GoCoax MoCA**. Enter the host or IP address of one adapter together
with its credentials — the defaults `admin` / `gocoax` are pre-filled.

Adding **one** adapter is enough: registers `0x16` and `0x1D` return data for
every node of the MoCA network, so a single poll covers all of them.

A second step then lists the other nodes that were discovered and lets you enter
their IP addresses. Doing so adds their Ethernet counters and lets the
coordinator fall back to them if the first adapter becomes unreachable. Leaving a
field empty is fine — the node is still created, it just has no Ethernet
counters.

MoCA only carries MAC addresses, never IPs, which is why Home Assistant cannot
discover those addresses on its own. You can add them later at any time via
**Configure** on the integration.

## Entities

**Network device:** link, active nodes, network MoCA version, network
coordinator, beacon channel, channels, LOF.

**Per adapter:** online, GCD rate, MoCA version, node ID, directional PHY rates
to every peer, and the Ethernet counters (Tx/Rx good, bad, dropped) — the latter
only for adapters whose IP address is known.

Enabled by default are the values that carry a warning signal: **GCD rate**,
**PHY rates** and the **error counters** (`bad`, `dropped`). A PHY rate that
drops in one direction only, or a falling GCD rate, points at a cable or splitter
problem well before throughput suffers noticeably.

VLPER rates and the `good` counters ship as diagnostic entities but are disabled,
since on a healthy MoCA 2.5 network they read 0 and a permanently-zero sensor
looks like a defect.

Devices and entities are identified by MAC address, never by MoCA node ID: node
IDs are not stable across reboots and the network-coordinator role moves between
adapters.

## Safety

The integration only ever **reads**. The permitted registers live in a frozen
allowlist (`api/registers.py`) and the client exposes no free-form path. Write
access and the reboot call sit in the same address space on the device, so this
is enforced structurally rather than by convention.

## Development

Source comments and docstrings are in German; user-facing strings are translated
via `strings.json` and `translations/`.

```bash
uv python install 3.14.2      # required by HA 2026.8
uv sync
uv run pytest -q
uv run python scripts/dump_registers.py <ip> --decode   # against real hardware
```

Tests run against HA 2026.8.2 on Python 3.14.2 — the target version.

`scripts/dump_registers.py` also records the test fixtures: without `--decode` it
writes the raw registers as JSON.

## License

MIT — see [LICENSE](LICENSE).

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://hacs.xyz/
[license-badge]: https://img.shields.io/badge/license-MIT-blue.svg
