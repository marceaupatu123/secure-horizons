"""Tests de l'etude #85 (contamination posee apres coup)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from data.late_marking import ChainParams, main, run, simulate_chain, to_markdown


def test_prospective_recovers_nothing_on_a_propagated_chain() -> None:
    result = simulate_chain(ChainParams(detect_after_minutes=3))
    c = result["strategies"]["c_prospectif"]
    amount = result["params"]["stolen_base_units"]

    assert c["recovered"] == 0
    assert c["escaped_converted"] == amount


def test_lineage_recovers_all_when_alert_precedes_maturity() -> None:
    result = simulate_chain(ChainParams(window_minutes=10, detect_after_minutes=3))
    amount = result["params"]["stolen_base_units"]

    assert result["timeline"]["alert_before_maturity"] is True
    for strategy in ("a_lignage_origine", "b_retroactif"):
        assert result["strategies"][strategy]["recovered"] == amount


def test_lineage_recovers_nothing_once_matured() -> None:
    # Detection apres l'echeance : la valeur est deja convertie, hors d'atteinte pour toutes.
    result = simulate_chain(ChainParams(window_minutes=10, detect_after_minutes=12))
    amount = result["params"]["stolen_base_units"]

    assert result["timeline"]["alert_before_maturity"] is False
    for strategy in result["strategies"].values():
        assert strategy["recovered"] == 0
        assert strategy["escaped_converted"] == amount


def test_each_strategy_conserves_the_total() -> None:
    result = simulate_chain(ChainParams())
    amount = result["params"]["stolen_base_units"]
    for s in result["strategies"].values():
        assert s["recovered"] + s["escaped_converted"] == amount


def test_a_and_b_cover_the_same_amount() -> None:
    result = simulate_chain(ChainParams(detect_after_minutes=5))
    a = result["strategies"]["a_lignage_origine"]
    b = result["strategies"]["b_retroactif"]
    assert a["recovered"] == b["recovered"]


def test_sweep_crosses_over_at_the_window() -> None:
    rows = run(ChainParams(window_minutes=10))["detection_speed_sweep"]
    before = [r for r in rows if r["alert_before_maturity"]]
    after = [r for r in rows if not r["alert_before_maturity"]]

    assert before and after
    assert all(r["a_recovered_fraction"] == 1.0 for r in before)
    assert all(r["a_recovered_fraction"] == 0.0 for r in after)
    assert all(r["c_recovered_fraction"] == 0.0 for r in rows)


def test_params_validation() -> None:
    with pytest.raises(ValueError):
        ChainParams(hops=0)
    with pytest.raises(ValueError):
        ChainParams(detect_after_minutes=0)


def test_cli_writes_reports(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    main(["--hops", "5", "--window", "10", "--out-dir", str(tmp_path)])

    data = json.loads((tmp_path / "late_marking.json").read_text())
    assert data["reference_case"]["params"]["hops"] == 5
    assert (tmp_path / "late_marking.md").read_text() == to_markdown(data)
    assert "contamination posee apres coup" in capsys.readouterr().out
