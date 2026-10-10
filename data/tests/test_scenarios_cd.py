"""Tests des scenarios C et D (#25) : proprietes attendues, pas des chiffres figes."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from data.generate import event_time, load_jsonl, write_scenario
from data.scenarios_cd import ContagionParams, generate_scenario_c, generate_scenario_d
from shared.models import GhostTokenBurnEvent, RiskBeaconUpdate

PARAMS = ContagionParams(seed=3)


@pytest.fixture(scope="module")
def d() -> dict:  # type: ignore[type-arg]
    return generate_scenario_d(PARAMS)


@pytest.fixture(scope="module")
def c() -> dict:  # type: ignore[type-arg]
    return generate_scenario_c(PARAMS)


def results(scenario) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return scenario.manifest["results"]


# --- D : marche secondaire du Ghost ----------------------------------------------------


def test_without_ghost_the_protocol_absorbs_the_whole_fraud(d) -> None:  # type: ignore[no-untyped-def]
    r = results(d["no_ghost"])
    assert r["protocol_deficit"] == d["no_ghost"].manifest["attack"]["minted"]
    assert r["burned_total"] == 0


def test_with_ghost_the_deficit_is_only_the_measured_leak(d) -> None:  # type: ignore[no-untyped-def]
    """Le deficit restant est exactement le soupcon sorti par conversion (avant ou apres l'alerte)."""
    for variant in ("otc", "pool"):
        r = results(d[variant])
        minted = d[variant].manifest["attack"]["minted"]
        leak = r["suspect_leaked_before_alert"] + r["suspect_escaped_by_conversion"]
        assert minted <= r["burned_total"] + r["protocol_deficit"] <= minted + 100  # arrondi au-dessus
        assert r["protocol_deficit"] <= leak + 2  # arrondis
        assert r["protocol_deficit"] < minted // 100
        assert r["margin_before_conversion_seconds"] > 0


def test_default_scenario_is_fully_recovered() -> None:
    for variant in ("otc", "pool"):
        r = results(generate_scenario_d()[variant])
        assert r["protocol_deficit"] == 0
        assert r["suspect_leaked_before_alert"] == 0


def test_otc_loss_is_carried_by_the_secondary_market(d) -> None:  # type: ignore[no-untyped-def]
    r = results(d["otc"])
    assert r["attacker_usdc"] > 0
    assert r["speculators_net_value"] < 0
    assert set(r["burned_by_group"]) <= {"speculator", "legit", "attacker"}


def test_pool_claims_follow_section_10(d) -> None:  # type: ignore[no-untyped-def]
    """Creance annulee a hauteur du ratio du vendeur AU MOMENT du swap (§10).

    Consequence mesuree : un swap fait avant l'alerte (ratio 0) est paye a l'attaquant.
    """
    r = results(d["pool"])
    alert_at = r["alert_at"]
    for claim in r["claims"]:
        assert claim["paid"] + claim["cancelled"] == claim["usdc"]
        assert claim["cancelled"] == int(claim["ratio_at_swap"] * claim["usdc"])
    assert r["attacker_usdc"] == sum(cl["paid"] for cl in r["claims"])
    assert r["pool_usdc_paid"] == r["attacker_usdc"]
    assert alert_at is not None


# --- C : contagion vers un faux marche de pret --------------------------------------------


def test_beacon_reduces_bad_debt(c) -> None:  # type: ignore[no-untyped-def]
    with_b, without_b = results(c["with_beacon"]), results(c["without_beacon"])
    assert with_b["bad_debt_usdc"] <= without_b["bad_debt_usdc"]
    assert without_b["bad_debt_usdc"] > 0
    assert with_b["refused_legit"] == 0
    assert with_b["loans_attacker"] == with_b["attacker_loans_before_alert"]


def test_market_without_beacon_lends_to_every_attacker_hop(c) -> None:  # type: ignore[no-untyped-def]
    r = results(c["without_beacon"])
    assert r["loans_attacker"] == PARAMS.attacker_hops
    assert r["defaults"] >= r["loans_attacker"]


def test_legit_loans_are_never_hurt(c) -> None:  # type: ignore[no-untyped-def]
    for scenario in c.values():
        r = results(scenario)
        assert r["protocol_deficit"] == 0
        assert r["defaults"] <= r["loans_attacker"]


# --- format, reproductibilite, parametres ----------------------------------------------------


def test_jsonl_roundtrip_and_chronology(tmp_path: Path, d, c) -> None:  # type: ignore[no-untyped-def]
    for scenario in [*d.values(), *c.values()]:
        jsonl, _ = write_scenario(scenario, tmp_path)
        events = load_jsonl(jsonl)
        assert events == scenario.events
        times = [event_time(e) for e in events]
        assert times == sorted(times)


def test_burns_and_beacons_are_emitted_after_alert(d) -> None:  # type: ignore[no-untyped-def]
    scenario = d["otc"]
    t0 = PARAMS.t0
    burns = [e for e in scenario.events if isinstance(e, GhostTokenBurnEvent)]
    beacons = [e for e in scenario.events if isinstance(e, RiskBeaconUpdate)]
    assert burns and beacons
    assert all(b.burned_at == t0 + timedelta(minutes=PARAMS.confirm_after_minutes) for b in burns)
    assert min(b.published_at for b in beacons) == t0 + timedelta(minutes=PARAMS.detect_after_minutes)


def test_same_seed_same_results() -> None:
    first = generate_scenario_d(ContagionParams(seed=11))["otc"]
    second = generate_scenario_d(ContagionParams(seed=11))["otc"]
    assert first.events == second.events
    assert first.manifest == second.manifest


def test_params_validation() -> None:
    with pytest.raises(ValueError):
        ContagionParams(detect_after_minutes=5, confirm_after_minutes=4)
    with pytest.raises(ValueError):
        ContagionParams(confirm_after_minutes=100, extended_window_minutes=60)
    with pytest.raises(ValueError):
        ContagionParams(ltv=1.5)
