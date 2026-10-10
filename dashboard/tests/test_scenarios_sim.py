"""Briques de simulation hors chaine (#47) : detecteur, trafic, contrats."""

import random
from datetime import timedelta

import pytest

from dashboard.demo_data import DEMO_CHAIN_ID, DEMO_REFERENCE_TIME
from dashboard.scenarios.config import DEFAULT_PARAMS
from dashboard.scenarios.sim_contracts import (
    ConstantProductPool,
    GhostLedger,
    LendingMarket,
    ProtectedMinter,
    VulnerableMinter,
)
from dashboard.scenarios.sim_detector import bucket_stats, robust_zscore
from dashboard.scenarios.sim_traffic import attacker_transfers, legit_addresses, legit_traffic
from shared.models import MintRequest

PARAMS = DEFAULT_PARAMS


def test_robust_zscore() -> None:
    history = [1.0, 2.0, 3.0, 4.0, 5.0]  # mediane 3, MAD 1
    assert robust_zscore(3.0, history, 1e-9) == 0.0
    assert robust_zscore(4.4826, history, 1e-9) == pytest.approx(1.0)
    assert robust_zscore(2.0, [2.0, 2.0, 2.0], 0.5) == 0.0  # plancher : pas de division par zero
    with pytest.raises(ValueError):
        robust_zscore(1.0, [], 1e-9)


def test_legit_traffic_has_high_dispersion() -> None:
    rng = random.Random(1)
    traffic = legit_traffic(rng, legit_addresses(rng, PARAMS.legit_address_count),
                            DEMO_REFERENCE_TIME, 6, PARAMS)
    stats = bucket_stats(traffic, DEMO_REFERENCE_TIME, PARAMS.bucket_minutes, PARAMS.supply)
    assert stats and all(s.dispersion > PARAMS.dispersion_threshold for s in stats)


def test_attacker_transfers_collapse_dispersion_under_cap() -> None:
    rng = random.Random(1)
    attackers = legit_addresses(rng, PARAMS.attacker_address_count)
    attack = attacker_transfers(rng, attackers, DEMO_REFERENCE_TIME, PARAMS)
    stats = bucket_stats(attack, DEMO_REFERENCE_TIME, PARAMS.bucket_minutes, PARAMS.supply)
    assert all(s.dispersion < PARAMS.dispersion_threshold for s in stats)
    assert all(t.amount < PARAMS.onchain_cap_per_tx for t in attack)


def test_protected_minter_ignores_signed_amount() -> None:
    rng = random.Random(1)
    request = MintRequest(
        request_id=1, requester="0x" + "1" * 40, deposit_token="0x" + "2" * 40,
        deposit_amount=1_000, created_at=DEMO_REFERENCE_TIME, chain_id=DEMO_CHAIN_ID,
        signature="0x" + format(rng.getrandbits(64), "016x"),
    )
    protected = ProtectedMinter()
    assert protected.process(request) == 1_000
    assert protected.unbacked() == 0
    vulnerable = VulnerableMinter()
    vulnerable.mint(1_000_000, 1_000)
    assert vulnerable.unbacked() == 999_000


def test_pool_preserves_constant_product() -> None:
    pool = ConstantProductPool(1_000_000, 2_000_000)
    k = pool.ghost_reserve * pool.stable_reserve
    out = pool.sell_ghost(100_000)
    assert out > 0
    product = pool.ghost_reserve * pool.stable_reserve
    assert k <= product < k + pool.ghost_reserve


def test_lending_market_refuses_above_threshold_only_if_reading_beacon() -> None:
    reader = LendingMarket(reads_beacon=True, ltv=0.5, ratio_threshold=0.5)
    blind = LendingMarket(reads_beacon=False, ltv=0.5, ratio_threshold=0.5)
    assert reader.deposit_and_borrow("a", 1_000, 0.9) is False
    assert reader.deposit_and_borrow("b", 1_000, 0.1) is True
    assert blind.deposit_and_borrow("a", 1_000, 0.9) is True
    assert reader.bad_debt({"b"}) == 500
    assert blind.bad_debt({"a"}) == 500


def test_ghost_ledger_hold_then_burn() -> None:
    ledger = GhostLedger(timedelta(minutes=10))
    t0 = DEMO_REFERENCE_TIME
    ledger.credit("x", 1_000, 1.0, t0)
    ledger.hold("x", t0 + timedelta(hours=1))
    assert ledger.convert_after_window(t0 + timedelta(minutes=30)) == {}
    assert ledger.burn("x", 1.0, t0 + timedelta(minutes=30)) == 1_000
    ledger.convert_after_window(t0 + timedelta(hours=2))
    assert ledger.total_converted_suspect() == 0
