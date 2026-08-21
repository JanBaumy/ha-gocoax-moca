"""Tests der PHY-Raten-Berechnung."""

from __future__ import annotations

from api.fmr import compute_phy_rates


def test_live_rates_match_reference(live_2nodes):
    """Regression gegen die aufgezeichneten Rohdaten von 192.0.2.10.

    Die exakten Werte gehoeren zu dieser Aufzeichnung; zwischen zwei Polls
    schwanken die Raten um wenige Mbit/s. Zusaetzlich wird die Groessenordnung
    gegen die unabhaengig verifizierte Referenz geprueft (~1200 off-diagonal,
    ~600 auf der Diagonalen) -- ein Offset-Fehler faellt dort sofort auf.
    """
    rates, gcd = compute_phy_rates(
        live_2nodes["local_info"], live_2nodes["net_info"], live_2nodes["fmr"]
    )

    assert rates[(0, 1)].nper == 1220
    assert rates[(1, 0)].nper == 1183
    assert gcd[0] == 597
    assert gcd[1] == 578

    assert 1100 < rates[(0, 1)].nper < 1300
    assert 500 < gcd[0] < 700

    # VLPER ist off-diagonal 0, auf der Diagonalen belegt.
    assert rates[(0, 1)].vlper == 0
    assert rates[(1, 0)].vlper == 0
    assert rates[(0, 0)].vlper > 0


def test_absent_slot_shifts_read_index(synth_gap):
    """Der eigentliche Zweck dieses Testmoduls.

    Bitmask 0b1101 -- Slot 1 ist leer und verschiebt read_idx um zwei Woerter.
    Eine Implementierung, die nur ueber die aktiven Knoten iteriert, liest an
    Slot 2 das absichtlich als 0xdeadbeef gesetzte Fuellwort und faellt hier
    sichtbar durch. Die Live-Fixture kann das nicht abfangen: dort sind die
    Knoten 0 und 1 lueckenlos, und beide Varianten liefern dasselbe.

    Erwartungswerte von Hand aus phyRates.html hergeleitet:
      j=0: w[10] -> gap 26, ofdmb 3924 -> 569 Mbit/s (VLPER: gap 26, 3840 -> 557)
      j=1: abwesend, align=False, ver>=0x20 -> read_idx += 2
      j=2: w[13] -> gap 16, ofdmb 8149 -> 1224 Mbit/s
      j=3: w[14] lo + w[15] -> gap 26, ofdmb 3973 -> 576 Mbit/s
    """
    rates, gcd = compute_phy_rates(
        synth_gap["local_info"], synth_gap["net_info"], synth_gap["fmr"]
    )

    assert rates[(0, 0)].nper == 569
    assert rates[(0, 0)].vlper == 557
    assert rates[(0, 2)].nper == 1224
    assert rates[(0, 3)].nper == 576

    # Slot 1 ist leer -- es darf keine Rate dorthin geben.
    assert (0, 1) not in rates

    # GCD steht auf der Diagonalen, also bei j == Knoten-ID.
    assert gcd[0] == 569
    assert gcd[2] == 1224
    assert gcd[3] == 576


def test_moca1_node_has_no_gcd(synth_gap):
    """Fuer 1.x-Knoten fehlt der Mix-Mode-Zweig -> lieber None als eine Zahl."""
    synth_gap["net_info"][2][4] = 0x11  # Knoten 2 auf MoCA 1.1 setzen
    _, gcd = compute_phy_rates(
        synth_gap["local_info"], synth_gap["net_info"], synth_gap["fmr"]
    )
    assert gcd[2] is None
