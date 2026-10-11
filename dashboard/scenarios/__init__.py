"""Moteur de scenarios de demo (#47, #70).

L'import de `catalog` peuple le registre avec les 7 scenarios A/B/C/D/N1/N2/N3.
Les briques livrees en amont (#11, #12, #17, #24, et #4/#5 via le backend anvil
optionnel) sont branchees sur le vrai code ; le reste est une simulation hors
chaîne, à remplacer par #n (indique par scenario).
"""

from dashboard.scenarios import catalog  # noqa: F401  (enregistre les scenarios)
from dashboard.scenarios.config import DEFAULT_PARAMS, SimulationParams
from dashboard.scenarios.models import (
    REAL_LABEL,
    SIMULATION_LABEL,
    STATUS_LABELS,
    MeasuredMetric,
    ScenarioCheck,
    ScenarioResult,
    ScenarioSpec,
    ScenarioStatus,
    ScenarioVariant,
    simulation_banner,
)
from dashboard.scenarios.registry import SCENARIO_ORDER, get_spec, list_specs, run_scenario

__all__ = [
    "DEFAULT_PARAMS",
    "REAL_LABEL",
    "SCENARIO_ORDER",
    "SIMULATION_LABEL",
    "STATUS_LABELS",
    "MeasuredMetric",
    "ScenarioCheck",
    "ScenarioResult",
    "ScenarioSpec",
    "ScenarioStatus",
    "ScenarioVariant",
    "SimulationParams",
    "get_spec",
    "list_specs",
    "run_scenario",
    "simulation_banner",
]
