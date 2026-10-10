"""CLI `python -m dashboard.demo` (#47)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dashboard.demo import main
from dashboard.scenarios import SCENARIO_ORDER

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_list_shows_all_scenarios(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    for scenario_id in SCENARIO_ORDER:
        assert f"{scenario_id} | " in out
    assert "optionnel" in out
    assert "simulation hors chaîne, à remplacer par #" in out


def test_run_json_is_reproducible(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "N1", "--seed", "20", "--json"]) == 0
    first = capsys.readouterr().out
    assert json.loads(first)["status"] == "completed"
    assert main(["run", "N1", "--seed", "20", "--json"]) == 0
    assert capsys.readouterr().out == first


def test_run_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "A", "--seed", "20"]) == 0
    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "simulation hors chaîne" in out
    assert "prouv" not in out.lower()


def test_run_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "C", "--disable", "C"]) == 0
    assert "désactivé" in capsys.readouterr().out


def test_unknown_id_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "Z"]) == 2
    assert "inconnu" in capsys.readouterr().err


def test_module_entry_point() -> None:
    completed = subprocess.run([sys.executable, "-m", "dashboard.demo", "list"], cwd=REPO_ROOT,
                               capture_output=True, timeout=120, check=False)
    assert completed.returncode == 0
