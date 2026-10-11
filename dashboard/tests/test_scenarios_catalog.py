"""Catalogue des 7 scenarios (#47) : reproductibilite et attendus mesures.

Depuis #70, B, N1, N2 et N3 tournent sur le vrai code (#11/#12, #17, #24) ; A sur les
vrais contrats seulement avec le backend anvil (opt-in, absent en CI) ; C et D restent
simules (#7, #8, #25 non livres).
"""

import pytest

from dashboard.scenarios import (
    SCENARIO_ORDER,
    SIMULATION_LABEL,
    ScenarioResult,
    ScenarioStatus,
    run_scenario,
)
from dashboard.scenarios.models import REAL_LABEL
from dashboard.view_model import PerimeterState, derive_perimeter_states
from shared.models import ResponseActionStatus, ResponseActionType

# Scenarios entierement branches (aucune brique simulee) / partiellement / simules.
FULLY_REAL = {"N1", "N2"}
PARTLY_REAL = {"B", "N3"}  # le Ghost (#8) reste simule
SIMULATED = {"A", "C", "D"}  # A : simulation par defaut, anvil en opt-in


def _texts(result: ScenarioResult) -> list[str]:
    texts = [result.message]
    for variant in result.variants:
        texts.append(variant.label)
        texts += [m.label for m in variant.metrics]
        texts += [c.label + c.expected for c in variant.checks]
        texts += [e.message for e in variant.dataset.audit_log]
        texts += [a.reason for a in variant.dataset.alerts]
    return texts


@pytest.mark.parametrize("scenario_id", SCENARIO_ORDER)
def test_same_seed_same_json(scenario_id: str) -> None:
    first = run_scenario(scenario_id, seed=20)
    second = run_scenario(scenario_id, seed=20)
    assert first.model_dump_json() == second.model_dump_json()
    assert first.status == ScenarioStatus.COMPLETED
    assert first.variants
    sources = {m.source for variant in first.variants for m in variant.metrics}
    if scenario_id in FULLY_REAL:
        assert first.simulated is False and first.replace_by == []
        assert all(s.startswith(REAL_LABEL) for s in sources)
    elif scenario_id in PARTLY_REAL:
        assert first.simulated is True and first.replace_by == [8]
        assert any(s.startswith(REAL_LABEL) for s in sources)
        assert SIMULATION_LABEL in sources
    else:
        assert scenario_id in SIMULATED
        assert first.simulated is True
        assert sources == {SIMULATION_LABEL}
    assert not any("prouv" in text.lower() for text in _texts(first))


def test_other_seed_changes_b() -> None:
    assert run_scenario("B", seed=20).model_dump_json() != run_scenario("B", seed=21).model_dump_json()


def test_n1_no_alert_no_freeze() -> None:
    result = run_scenario("N1")
    assert result.metric("main", "alert_count").value == 0
    assert result.metric("main", "freeze_count").value == 0
    assert result.metric("main", "false_positive_count").value == 0


def test_n2_growth_without_alert() -> None:
    result = run_scenario("N2")
    assert result.metric("main", "alert_count").value == 0
    growth = result.metric("main", "volume_growth_measured").value
    assert growth is not None and growth > 1


def test_n3_returns_to_normal_without_destroy() -> None:
    result = run_scenario("N3")
    variant = result.variant("main")
    assert all(c.passed for c in variant.checks)
    states = derive_perimeter_states(variant.dataset.alerts, variant.dataset.actions,
                                     variant.end_time)
    assert PerimeterState.DELAYED not in states.values()
    assert not any(a.action_type == ResponseActionType.DESTROY for a in variant.dataset.actions)
    assert any(a.action_type == ResponseActionType.DELAY
               and a.status == ResponseActionStatus.EXPIRED for a in variant.dataset.actions)


def test_a_vulnerable_drained_protected_bounded() -> None:
    result = run_scenario("A")
    vulnerable = result.metric("vulnerable", "protocol_loss").value
    assert vulnerable is not None and vulnerable > 0
    assert result.metric("protected", "protocol_loss").value == 0
    assert result.variant("vulnerable").dataset.alerts == []


def test_b_detected_under_cap() -> None:
    result = run_scenario("B")
    assert result.metric("main", "detection_delay_seconds").value is not None
    assert result.metric("main", "contract_rejections").value == 0
    assert all(c.passed for c in result.variant("main").checks)


def test_c_beacon_reduces_bad_debt() -> None:
    result = run_scenario("C")
    with_beacon = result.metric("with_beacon", "bad_debt").value
    without_beacon = result.metric("without_beacon", "bad_debt").value
    assert with_beacon is not None and without_beacon is not None
    assert with_beacon < without_beacon


def test_d_protocol_loss_zero_speculators_pay() -> None:
    result = run_scenario("D")
    speculator_loss = result.metric("main", "speculator_loss").value
    assert result.metric("main", "protocol_loss").value == 0
    assert speculator_loss is not None and speculator_loss > 0
