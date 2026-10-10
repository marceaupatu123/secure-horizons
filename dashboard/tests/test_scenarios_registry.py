"""Registre des scenarios de demo (#47) : ordre, desactivation, indisponibilite."""

from collections.abc import Iterator

import pytest

from dashboard.scenarios import (
    SCENARIO_ORDER,
    ScenarioSpec,
    ScenarioStatus,
    get_spec,
    list_specs,
    run_scenario,
)
from dashboard.scenarios import registry
from dashboard.scenarios.config import SimulationParams
from dashboard.scenarios.models import ScenarioResult

FAKE_ID = "ZZ_TEST"


def _not_ready(seed: int, params: SimulationParams) -> ScenarioResult:
    raise NotImplementedError


@pytest.fixture
def fake_spec() -> Iterator[ScenarioSpec]:
    spec = registry.register(ScenarioSpec(
        id=FAKE_ID, title="Factice", description="d", expected="e", optional=False,
        depends_on=(11, 12), replace_by=(11,), runner=_not_ready,
    ))
    yield spec
    registry._REGISTRY.pop(FAKE_ID, None)


def test_seven_scenarios_in_order() -> None:
    assert [s.id for s in list_specs()] == list(SCENARIO_ORDER)
    assert SCENARIO_ORDER == ("A", "B", "C", "D", "N1", "N2", "N3")


def test_c_and_d_are_optional() -> None:
    assert {s.id for s in list_specs() if s.optional} == {"C", "D"}


def test_disabled_gives_disabled_without_variant() -> None:
    result = run_scenario("C", disabled=frozenset({"C"}))
    assert result.status == ScenarioStatus.DISABLED
    assert result.variants == []
    assert "désactivé" in result.message


def test_not_implemented_runner_gives_unavailable(fake_spec: ScenarioSpec) -> None:
    result = run_scenario(FAKE_ID)
    assert result.status == ScenarioStatus.UNAVAILABLE
    assert result.variants == []
    assert "dépend de #" in result.message
    assert result.message == "non disponible (dépend de #11, #12)"


def test_unknown_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get_spec("Z")
    with pytest.raises(KeyError):
        run_scenario("Z")


def test_duplicate_register_raises(fake_spec: ScenarioSpec) -> None:
    with pytest.raises(ValueError):
        registry.register(fake_spec)
