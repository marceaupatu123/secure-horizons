"""Volume deduplique des relais dans une tranche (#87).

Donnees fictives uniquement. Verifie qu'un montant qui transite A -> B -> C
dans la meme tranche n'est compte qu'une fois (regle PROVISOIRE, voir
`SlotAggregate.volume` et docs/OPEN_QUESTIONS.md §2).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from detection.tests.test_transfer_rules import (
    ATTACK_TOTAL,
    BRIDGES,
    RELAYS,
    _attack,
    _transfer,
)
from detection.transfers import SlotAggregate

AT = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
A, B, C, D = (f"0x{n:040x}" for n in (0xA1, 0xB2, 0xC3, 0xD4))


def _slot(*transfers: tuple[str, str, int]) -> SlotAggregate:
    slot = SlotAggregate(0)
    for sender, recipient, amount in transfers:
        slot.add(_transfer(sender, recipient, amount, AT))
    return slot


def test_reference_attack_counts_once() -> None:
    slot = SlotAggregate(0)
    for event in _attack(0):
        slot.add(event)
    assert slot.gross_volume == 2 * ATTACK_TOTAL
    assert slot.volume == ATTACK_TOTAL
    # Les relais (solde net nul) ne sont plus des destinataires.
    assert set(slot.net_inflows()) == {b.lower() for b in BRIDGES}
    assert not {r.lower() for r in RELAYS} & set(slot.net_inflows())
    assert slot.herfindahl() == pytest.approx(0.25, rel=1e-6)


def test_chain_a_b_c_counts_once() -> None:
    slot = _slot((A, B, 100), (B, C, 100))
    assert slot.gross_volume == 200
    assert slot.volume == 100
    assert slot.herfindahl() == 1.0


def test_partial_relay_keeps_its_remainder() -> None:
    # B garde 40 : volume = 60 arrive chez C + 40 reste chez B.
    slot = _slot((A, B, 100), (B, C, 60))
    assert slot.volume == 100
    assert slot.net_inflows() == {B.lower(): 40, C.lower(): 60}


def test_independent_transfers_unchanged() -> None:
    slot = _slot((A, B, 30), (C, D, 70))
    assert slot.volume == slot.gross_volume == 100


def test_round_trip_counts_zero_documented_limit() -> None:
    slot = _slot((A, B, 50), (B, A, 50))
    assert slot.gross_volume == 100
    assert slot.volume == 0
    assert slot.herfindahl() == 0.0


def test_address_case_does_not_break_dedup() -> None:
    slot = _slot((A, B.upper().replace("0X", "0x"), 10), (B, C, 10))
    assert slot.volume == 10
