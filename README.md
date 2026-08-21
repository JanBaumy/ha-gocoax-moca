# GoCoax MoCA — Home Assistant Custom Integration

Liest GoCoax-/MaxLinear-MoCA-Adapter (MXL371x) über die JSON-API ihres Web-UI aus.
Kein Webscraping: die PHY-Raten stehen gar nicht im HTML, sondern werden im Browser
aus FMR-Rohdaten berechnet — diese Integration rechnet sie direkt nach.

## Voraussetzungen

- Home Assistant **2026.8** oder neuer (setzt Python ≥ 3.14.2 voraus)
- Mindestens ein erreichbarer Adapter mit aktiviertem Web-UI

## Installation

HACS → *Custom Repositories* → `https://github.com/JanBaumy/ha-gocoax-moca`,
Kategorie *Integration*. Danach *Einstellungen → Geräte & Dienste → Integration
hinzufügen → GoCoax MoCA*.

Es genügt, **einen** Adapter einzutragen: Die Register `0x16` und `0x1D` liefern
Daten für alle Knoten des MoCA-Netzes. Im zweiten Schritt kannst du die IPs der
übrigen Adapter ergänzen — dann kommen deren Ethernet-Zähler dazu, und der
Coordinator kann bei einem Ausfall auf sie ausweichen.

MoCA überträgt nur MAC-Adressen, keine IPs. Deshalb kann Home Assistant die
Adressen der anderen Adapter nicht selbst ermitteln.

## Entities

**Netzwerk-Device:** Link, aktive Knoten, MoCA-Version des Netzes, Network
Coordinator, Beacon-Kanal, Kanäle, LOF.

**Je Adapter:** Online, GCD-Rate, MoCA-Version, Node-ID, gerichtete PHY-Raten zu
jedem Peer, sowie Ethernet-Zähler (Tx/Rx good, bad, dropped) — letztere nur, wenn
die IP dieses Adapters bekannt ist.

Standardmäßig aktiv sind die Werte mit Alarmwert: **GCD-Rate**, **PHY-Raten** und
die **Fehlerzähler** (`bad`, `dropped`). Eine einseitig einbrechende PHY-Rate oder
eine sinkende GCD-Rate zeigen ein Kabel- oder Splitter-Problem an, bevor der
Durchsatz spürbar leidet.

VLPER-Raten und die `good`-Zähler sind als Diagnose vorhanden, aber deaktiviert.

## Sicherheit

Die Integration greift **ausschließlich lesend** zu. Die erlaubten Register stehen
in einer eingefrorenen Allowlist (`api/registers.py`) — im selben Adressraum des
Geräts liegen Schreibzugriffe und der Reboot-Aufruf, die damit strukturell
unerreichbar sind.

## Entwicklung

```bash
uv sync
uv run pytest                                   # api/-Tests
uv run python scripts/dump_registers.py <ip> --decode   # gegen echte Hardware
```

Die HA-abhängigen Tests brauchen `pytest-homeassistant-custom-component`.
