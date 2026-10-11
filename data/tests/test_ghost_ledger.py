"""Tests du registre de reference Ghost (§0bis-b, §0bis-c, §3, §9)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.ghost_ledger import GhostLedger, LedgerParams

T = datetime(2026, 10, 10, 14, 0, 30, tzinfo=timezone.utc)
W = timedelta(minutes=10)
A, B, C = ("0x" + c * 40 for c in "abc")


def ledger(**overrides: object) -> GhostLedger:
    return GhostLedger(LedgerParams(**overrides))  # type: ignore[arg-type]


def test_maturity_is_rounded_up_to_the_slot() -> None:
    lg = ledger()
    assert lg.maturity_for(T) == datetime(2026, 10, 10, 14, 11, tzinfo=timezone.utc)


def test_real_transfer_produces_ghost_with_fresh_maturity() -> None:
    lg = ledger()
    lg.credit_real(A, 100)
    mv = lg.transfer(A, B, 40, T, from_ghost=False)

    assert lg.account(B).ghost == 40 and lg.account(B).real == 0
    assert mv.expires_at == lg.maturity_for(T)


def test_ghost_transfer_keeps_maturity_and_sends_oldest_first() -> None:
    lg = ledger()
    lg.mint(A, 100, T, backed=True)
    lg.mint(A, 100, T + timedelta(minutes=5), backed=True)
    mv = lg.transfer(A, B, 150, T + timedelta(minutes=6), from_ghost=True)

    old, new = lg.maturity_for(T), lg.maturity_for(T + timedelta(minutes=5))
    assert dict(mv.maturities) == {old: 100, new: 50}
    assert lg.account(B).tranches == {old: 100, new: 50}
    assert lg.account(A).tranches == {new: 50}


def test_nothing_converts_before_window() -> None:
    lg = ledger()
    lg.mint(A, 100, T, backed=True)

    assert lg.convert(A, T + W - timedelta(seconds=1)).amount == 0
    assert lg.convert(A, lg.maturity_for(T)).amount == 100
    assert lg.account(A).real == 100


def test_dust_does_not_delay_the_rest_of_the_balance() -> None:
    lg = ledger()
    lg.mint(A, 1_000, T, backed=True)
    lg.mint(B, 1, T, backed=True)
    lg.transfer(B, A, 1, T + timedelta(minutes=9), from_ghost=True)  # vieux Ghost : echeance gardee
    lg.mint(C, 1, T + timedelta(minutes=9), backed=True)
    lg.transfer(C, A, 1, T + timedelta(minutes=9), from_ghost=True)  # Ghost frais

    result = lg.convert(A, lg.maturity_for(T))
    assert result.amount == 1_001
    assert lg.account(A).ghost == 1


def test_suspicion_is_conserved_by_transfers() -> None:
    lg = ledger()
    lg.mint(A, 1_000, T, backed=False)
    lg.mark_suspect(A, 1_000)
    lg.mint(B, 3_000, T, backed=True)
    lg.transfer(A, B, 400, T, from_ghost=True)
    lg.transfer(B, C, 700, T, from_ghost=True)

    assert lg.total_suspect() == pytest.approx(1_000)
    assert lg.account(B).ratio == pytest.approx(400 / 3_400)
    assert lg.account(C).suspect == pytest.approx(700 * 400 / 3_400)


def test_conversion_is_blocked_by_delay_ratio_and_absolute_amount() -> None:
    lg = ledger(ratio_threshold=0.1, suspect_threshold=50)
    due = lg.maturity_for(T)
    for address in (A, B, C):
        lg.mint(address, 1_000, T, backed=True)
    lg.delay(A, due + timedelta(hours=1))
    lg.mark_suspect(B, 200)  # ratio 0.2
    lg.mark_suspect(C, 60)  # ratio 0.06 mais 60 > 50

    assert lg.convert(A, due).blocked_reason == "fenetre allongee"
    assert lg.convert(B, due).blocked_reason == "ratio au-dessus du seuil"
    assert lg.convert(C, due).blocked_reason == "montant suspect au-dessus du seuil"


def test_delay_never_shortens() -> None:
    lg = ledger()
    lg.delay(A, T + timedelta(hours=1))
    lg.delay(A, T + timedelta(minutes=5))

    assert lg.account(A).delayed_until == T + timedelta(hours=1)


def test_burn_takes_the_suspect_fraction_only() -> None:
    lg = ledger()
    lg.mint(A, 1_000, T, backed=True)
    lg.mark_suspect(A, 20)  # porteur de bonne foi a 2 %

    assert lg.burn_suspect(A) == 20
    assert lg.account(A).ghost == 980
    assert lg.account(A).ratio == 0.0


def test_burn_spreads_over_tranches() -> None:
    lg = ledger()
    lg.mint(A, 300, T, backed=True)
    lg.mint(A, 700, T + timedelta(minutes=3), backed=True)
    lg.mark_suspect(A, 500)

    assert lg.burn_suspect(A) == 500
    assert sorted(lg.account(A).tranches.values()) == [150, 350]


def test_reserve_and_deficit() -> None:
    lg = ledger()
    lg.mint(A, 1_000, T, backed=False)
    assert lg.deficit == 1_000

    lg.mark_suspect(A, 1_000)
    lg.burn_suspect(A)
    assert lg.deficit == 0 and lg.reserve == 0

    lg.mint(B, 500, T, backed=True)
    lg.mark_suspect(B, 100)
    lg.burn_suspect(B)
    assert lg.reserve == 100  # Ghost adosse brule : excedent cantonne (§0bis-c)


def test_zero_window_means_no_ghost() -> None:
    lg = ledger(window=timedelta(0))
    lg.mint(A, 1_000, T, backed=False)

    assert lg.account(A).real == 1_000
    assert lg.account(A).ghost == 0
    assert lg.deficit == 1_000


def test_invalid_operations() -> None:
    lg = ledger()
    with pytest.raises(ValueError):
        lg.transfer(A, B, 1, T, from_ghost=True)
    with pytest.raises(ValueError):
        lg.mint(A, 0, T, backed=True)
    with pytest.raises(ValueError):
        LedgerParams(ratio_threshold=2.0)
    with pytest.raises(ValueError):
        LedgerParams(commission_rate=1.5)


# --- Marche du Ghost + sequestre / saisie (docs/GHOST_MARKET_SEIZURE.md) ---


def test_market_sell_applies_discount_and_commission_without_minting() -> None:
    lg = ledger(commission_rate=0.02)
    lg.mint(A, 1_000, T, backed=True)  # A detient 1000 de Ghost
    lg.credit_real(B, 1_000)  # B a de quoi payer

    supply_before = lg.supply_real
    sale = lg.market_sell(A, B, amount=1_000, price=950, at=T)  # 5 % de decote

    assert (sale.amount, sale.price, sale.discount) == (1_000, 950, 50)
    assert sale.commission == 19 and sale.seller_proceeds == 931  # 2 % de 950
    assert lg.commission_collected == 19
    assert lg.account(A).real == 931 and lg.account(B).real == 50
    assert lg.account(B).ghost == 1_000 and lg.account(A).ghost == 0
    # Aucun vrai token minte : la valeur reelle est conservee (en circulation + pot commission).
    assert lg.supply_real + lg.commission_collected == supply_before


def test_market_sell_rejects_price_above_face_value() -> None:
    lg = ledger()
    lg.mint(A, 100, T, backed=True)
    lg.credit_real(B, 1_000)
    with pytest.raises(ValueError):
        lg.market_sell(A, B, amount=100, price=101, at=T)  # paierait plus que la valeur faciale


def test_first_alerting_address_anchors_the_chain() -> None:
    lg = ledger()
    lg.lock_escrow(A, 1_000)  # sequestre a la source
    anchor1 = lg.flag_alert(A, T)  # A declenche la 1re alerte -> ancre
    anchor2 = lg.flag_alert(B, T + timedelta(minutes=1))  # alerte isolee de B

    assert anchor1 == A  # D2 : premiere adresse a alerter = ancre
    assert anchor2 == B  # chaine independante


def test_seize_burns_downstream_and_restitutes_escrow_to_authorities() -> None:
    lg = ledger()
    AUTH = "0x" + "ff" * 20
    # Fraude : mint non adosse chez A, sequestre bloque a la source.
    lg.mint(A, 1_000, T, backed=False)
    lg.lock_escrow(A, 1_000)
    anchor = lg.flag_alert(A, T, suspect_amount=1_000)
    # A revend son Ghost a C (dernier acheteur) sur le marche.
    lg.credit_real(C, 1_000)
    lg.market_sell(A, C, amount=1_000, price=600, at=T)

    seizure = lg.seize(anchor, AUTH, T + timedelta(minutes=5), decision_id="dec-1")

    # Dernier acheteur (C) perd tout son Ghost (D1).
    assert seizure.burned_ghost == 1_000 and lg.account(C).ghost == 0
    # Le sequestre est restitue aux autorites (coffre hors systeme), D1.
    assert seizure.seized_collateral == 1_000
    assert lg.seized_total == 1_000 and lg.escrow.get(anchor, 0) == 0


def test_seize_keeps_solvency_coherent() -> None:
    lg = ledger()
    AUTH = "0x" + "ff" * 20
    lg.mint(A, 1_000, T, backed=True)  # Ghost adosse
    lg.lock_escrow(A, 1_000)
    anchor = lg.flag_alert(A, T, suspect_amount=1_000)

    lg.seize(anchor, AUTH, T + timedelta(minutes=5), decision_id="dec-2")

    # Ghost detruit (offre Ghost tombe), collateral restitue aux autorites : pas de deficit cree.
    assert lg.supply_ghost == 0
    assert lg.deficit == 0 and lg.reserve == 0
