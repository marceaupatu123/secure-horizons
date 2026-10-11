"""Tests de la mise en tableau des scenarios (#47), sans Streamlit."""

from __future__ import annotations

from dashboard.scenarios import SIMULATION_LABEL, MeasuredMetric, list_specs, run_scenario
from dashboard.scenarios.models import REAL_LABEL
from dashboard.scenarios.view import (
    CHECK_COLUMNS,
    METRIC_COLUMNS,
    NOT_MEASURED_LABEL,
    SCENARIO_COLUMNS,
    checks_to_frame,
    common_metric_keys,
    metrics_to_frame,
    scenarios_to_frame,
    side_by_side_frame,
    simulation_banner,
)


def test_scenarios_frame_columns_and_status() -> None:
    frame = scenarios_to_frame(list_specs(), frozenset({"C"}))
    assert list(frame.columns) == SCENARIO_COLUMNS
    assert list(frame["Scénario"]) == ["A", "B", "C", "D", "N1", "N2", "N3"]
    row_c = frame[frame["Scénario"] == "C"].iloc[0]
    assert row_c["Statut"] == "désactivé"
    assert row_c["Optionnel"] == "oui"
    labels = dict(zip(frame["Scénario"], frame["Implémentation"], strict=True))
    for scenario_id in ("C", "D"):
        assert labels[scenario_id].startswith(f"{SIMULATION_LABEL}, à remplacer par #")
    for scenario_id in ("N1", "N2"):
        assert labels[scenario_id].startswith(REAL_LABEL)
        assert SIMULATION_LABEL not in labels[scenario_id]
    for scenario_id in ("B", "N3"):
        assert labels[scenario_id].startswith(REAL_LABEL)
        assert f"{SIMULATION_LABEL}, à remplacer par #8" in labels[scenario_id]
    # A : simule par defaut, backend reel optionnel (anvil) annonce dans le libelle.
    assert labels["A"].startswith(f"{SIMULATION_LABEL}, à remplacer par #4, #5")
    assert "SH_DEMO_CONTRACTS_BACKEND=anvil" in labels["A"]


def test_metrics_frame_formats_values() -> None:
    variant = run_scenario("A").variant("vulnerable")
    variant = variant.model_copy(update={"metrics": [
        MeasuredMetric(key="x", label="X", value=None, unit="s"),
        MeasuredMetric(key="y", label="Y", value=1234567, unit="base units"),
        MeasuredMetric(key="z", label="Z", value=5.6181, unit="×"),
    ]})
    frame = metrics_to_frame(variant)
    assert list(frame.columns) == METRIC_COLUMNS
    assert list(frame["Valeur"]) == [NOT_MEASURED_LABEL, "1 234 567", "5.62"]
    assert set(frame["Source"]) == {SIMULATION_LABEL}


def test_checks_frame_is_text() -> None:
    result = run_scenario("A")
    frames = [checks_to_frame(v) for v in result.variants]
    assert all(list(f.columns) == CHECK_COLUMNS for f in frames)
    assert {r for f in frames for r in f["Résultat"]} <= {"OK", "KO"}
    failed = result.variants[0].model_copy(update={"checks": [
        result.variants[0].checks[0].model_copy(update={"passed": False})]})
    assert list(checks_to_frame(failed)["Résultat"]) == ["KO"]


def test_banner_mentions_simulation_and_replacement() -> None:
    banner = simulation_banner(run_scenario("B", seed=7))
    assert SIMULATION_LABEL in banner
    assert "#" in banner
    assert "seed 7" in banner


def test_side_by_side_for_a() -> None:
    result = run_scenario("A")
    keys = common_metric_keys(result)
    assert "protocol_loss" in keys
    frame = side_by_side_frame(result, keys)
    assert list(frame.columns) == ["Grandeur mesurée"] + [v.label for v in result.variants]
    assert len(frame) == len(keys)
