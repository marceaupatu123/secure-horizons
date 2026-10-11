"""Tests de la calibration #3 (petites grilles, proprietes, pas de chiffres figes)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.calibrate import (
    CalibrationConfig,
    attack_detection,
    false_positives,
    main,
    mint_monitor,
    quarantine_budget,
    replay_transfers,
    run,
    to_markdown,
)
from data.generate import _Ledger, generate_normal, generate_scenario_b
from detection.params import TransferRuleParams

SMALL = CalibrationConfig(
    days=6,
    users=40,
    ghost_windows=(5, 30),
    volume_z=(3.0,),
    hhi_z=(3.0,),
    attack_sizes=(0.5,),
    profiles=(("petits_transferts", (0.01, 0.1)),),
)


def test_days_must_leave_room_for_baseline() -> None:
    with pytest.raises(ValueError):
        CalibrationConfig(days=TransferRuleParams().min_history_slots)


def test_baseline_is_only_evaluated_after_history() -> None:
    normal = generate_normal(SMALL.params(transfer_fraction=(0.01, 0.1)))
    outcomes = replay_transfers(normal, TransferRuleParams())
    first_evaluated = min(o.slot_end for o in outcomes if o.evaluated)

    assert first_evaluated - normal.events[0].observed_at >= timedelta(days=5)
    assert false_positives(outcomes)["evaluated_slots"] > 0


def test_large_attack_is_detected_before_conversion() -> None:
    params = SMALL.params(transfer_fraction=(0.01, 0.1), attack_deposit_tokens=500_000)
    b = generate_scenario_b(params)
    result = attack_detection(b, replay_transfers(b, TransferRuleParams()), window_minutes=10)

    assert result["detected"] and result["before_conversion"]
    assert 0 < result["latency_seconds"] < 10 * 60


def test_mint_monitor_sees_inflated_mint_but_not_hijack() -> None:
    results = mint_monitor(SMALL)

    assert results["A_vulnerable"]["alerts_on_attack"] == results["A_vulnerable"]["attack_mints"] == 2
    assert results["A_protected"]["alerts_on_attack"] == 0
    assert results["normal"]["alerts_elsewhere"] == 0
    # I3 (destinataire = deposant) n'est pas verifie par le surveillant de mint (#11).
    assert results["B"]["alerts_on_attack"] == 0


def test_longer_window_locks_more_supply() -> None:
    rows = run(SMALL)["ghost_window_friction"]
    by_window = {r["window_minutes"]: r["median"] for r in rows}

    assert 0 < by_window[5] < by_window[30] < 1


def test_generator_ghost_transfer_keeps_maturity() -> None:
    """§0bis-b : un Ghost transfere garde son echeance d'origine."""
    t = datetime(2026, 10, 10, tzinfo=timezone.utc)
    ledger = _Ledger(timedelta(minutes=10))
    ledger.credit_ghost("a", 100, t)
    lots = ledger.debit("a", 60, from_ghost=True)
    ledger.credit_ghost("b", 60, t + timedelta(minutes=8), lots)

    assert ledger.ghost["b"] == [(60, t + timedelta(minutes=10))]
    assert ledger.balances("b", t + timedelta(minutes=10)) == (60, 0)


def test_cli_writes_json_and_markdown(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    main(["--out-dir", str(tmp_path)], config=SMALL)

    data = json.loads((tmp_path / "calibration.json").read_text())
    assert set(data["trigger_sweep"]) == {"petits_transferts"}
    assert (tmp_path / "calibration.md").read_text() == to_markdown(data)
    assert "Fenetre Ghost" in capsys.readouterr().out


def test_quarantine_budget_delays_a_detected_attack() -> None:
    """L'alerte B rejouee dans response/ place une part positive de l'offre sous retard,
    et le retard par defaut (60 min) tient jusqu'a la fenetre Ghost (10 min)."""
    rows = quarantine_budget(SMALL, transfer_fraction=(0.01, 0.1))

    assert rows, "au moins une taille d'attaque mesuree"
    detected = [r for r in rows if r["detected"]]
    assert detected, "l'attaque massive de SMALL (50 %) doit etre detectee et retardee"
    for row in detected:
        # Budget : part de l'offre sous retard, bornee (0 < part <= 1).
        assert 0 < row["budget_share"] <= 1
        # Facteur d'allongement : le retard par defaut couvre la fenetre Ghost.
        assert row["delay_minutes"] >= row["window_minutes"]
        assert row["holds_until_window"] is True


def test_quarantine_budget_in_full_run() -> None:
    results = run(SMALL)
    assert set(results["quarantine_budget"]) == {"petits_transferts"}
