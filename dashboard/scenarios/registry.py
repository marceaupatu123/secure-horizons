"""Registre branchable des scenarios de demo (#47).

Brancher plus tard la vraie implementation (#4/#5/#7/#8/#11/#12/#17/#24/#25)
= remplacer le `runner` du `ScenarioSpec`, rien d'autre. Un runner qui leve
`NotImplementedError` (module amont encore squelette) donne un resultat
`UNAVAILABLE` sans aucune metrique fabriquee.
"""

from __future__ import annotations

from dashboard.demo_data import DEMO_SEED
from dashboard.scenarios.config import DEFAULT_PARAMS, SimulationParams
from dashboard.scenarios.models import ScenarioResult, ScenarioSpec, ScenarioStatus

SCENARIO_ORDER: tuple[str, ...] = ("A", "B", "C", "D", "N1", "N2", "N3")

_REGISTRY: dict[str, ScenarioSpec] = {}


def register(spec: ScenarioSpec) -> ScenarioSpec:
    """Enregistre `spec` ; ValueError si l'id est deja pris."""
    if spec.id in _REGISTRY:
        raise ValueError(f"scénario déjà enregistré : {spec.id}")
    _REGISTRY[spec.id] = spec
    return spec


def get_spec(scenario_id: str) -> ScenarioSpec:
    """Renvoie le scenario `scenario_id` (KeyError si inconnu)."""
    return _REGISTRY[scenario_id]


def list_specs() -> list[ScenarioSpec]:
    """Scenarios dans l'ordre SCENARIO_ORDER, puis les autres par ordre d'enregistrement."""
    ordered = [_REGISTRY[i] for i in SCENARIO_ORDER if i in _REGISTRY]
    ordered += [spec for i, spec in _REGISTRY.items() if i not in SCENARIO_ORDER]
    return ordered


def run_scenario(
    scenario_id: str,
    seed: int = DEMO_SEED,
    params: SimulationParams = DEFAULT_PARAMS,
    disabled: frozenset[str] = frozenset(),
) -> ScenarioResult:
    """Lance un scenario ; DISABLED / UNAVAILABLE ne portent aucune metrique."""
    spec = get_spec(scenario_id)
    if scenario_id in disabled:
        message = "désactivé (scénario optionnel)" if spec.optional else "désactivé"
        return _empty(spec, seed, ScenarioStatus.DISABLED, message)
    try:
        return spec.runner(seed, params)
    except NotImplementedError:
        deps = ", ".join(f"#{n}" for n in spec.depends_on)
        return _empty(spec, seed, ScenarioStatus.UNAVAILABLE, f"non disponible (dépend de {deps})")


def _empty(spec: ScenarioSpec, seed: int, status: ScenarioStatus, message: str) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=spec.id,
        seed=seed,
        status=status,
        message=message,
        simulated=False,
        replace_by=list(spec.replace_by),
        variants=[],
    )
