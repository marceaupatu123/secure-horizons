"""Mise en tableau des scenarios de demo (#47) : transformations pures, sans Streamlit.

La page `dashboard/pages/1_Scenarios_de_demo.py` ne fait que rendre ces tableaux.
Tout resultat est en TEXTE (`OK` / `KO`, `activé` / `désactivé`) : la couleur
n'est jamais le seul porteur d'information.
"""

from __future__ import annotations

import pandas as pd

from dashboard.scenarios.models import (
    SIMULATION_LABEL,
    MeasuredMetric,
    ScenarioResult,
    ScenarioSpec,
    ScenarioVariant,
)
from dashboard.scenarios.models import simulation_banner as _replace_banner
from dashboard.view_model import MISSING_LABEL, format_base_units

NOT_MEASURED_LABEL = "non mesuré"
CHECK_PASSED_LABEL = "OK"
CHECK_FAILED_LABEL = "KO"

SCENARIO_COLUMNS = ["Scénario", "Titre", "Optionnel", "Statut", "Dépend de", "Implémentation"]
METRIC_COLUMNS = ["Grandeur mesurée", "Valeur", "Unité", "Source"]
CHECK_COLUMNS = ["Attendu", "Résultat"]


def _refs(numbers: tuple[int, ...] | list[int]) -> str:
    return ", ".join(f"#{n}" for n in numbers) or MISSING_LABEL


def format_value(metric: MeasuredMetric) -> str:
    """Valeur seule : int -> base units groupes, float -> 2 decimales, None -> non mesure."""
    if metric.value is None:
        return NOT_MEASURED_LABEL
    if isinstance(metric.value, int):
        return format_base_units(metric.value)
    return f"{metric.value:.2f}"


def _value_with_unit(metric: MeasuredMetric) -> str:
    value = format_value(metric)
    return value if metric.value is None else f"{value} {metric.unit}"


def scenarios_to_frame(specs: list[ScenarioSpec], disabled: frozenset[str]) -> pd.DataFrame:
    """Catalogue des scenarios : optionnel, active/desactive, dependances, implementation."""
    rows = [
        [
            spec.id,
            spec.title,
            "oui" if spec.optional else "non",
            "désactivé" if spec.id in disabled else "activé",
            _refs(spec.depends_on),
            _replace_banner(spec.replace_by),
        ]
        for spec in specs
    ]
    return pd.DataFrame(rows, columns=SCENARIO_COLUMNS)


def metrics_to_frame(variant: ScenarioVariant) -> pd.DataFrame:
    """Grandeurs mesurees d'une variante (valeur formatee, unite, source)."""
    rows = [[m.label, format_value(m), m.unit, m.source] for m in variant.metrics]
    return pd.DataFrame(rows, columns=METRIC_COLUMNS)


def checks_to_frame(variant: ScenarioVariant) -> pd.DataFrame:
    """Attendus confrontes a la mesure, resultat en texte `OK` / `KO`."""
    rows = [
        [f"{c.label} ({c.expected})", CHECK_PASSED_LABEL if c.passed else CHECK_FAILED_LABEL]
        for c in variant.checks
    ]
    return pd.DataFrame(rows, columns=CHECK_COLUMNS)


def simulation_banner(result: ScenarioResult) -> str:
    """`simulation hors chaîne, à remplacer par #4, #5, #24 (seed 20)`."""
    return f"{_replace_banner(result.replace_by)} (seed {result.seed})"


def common_metric_keys(result: ScenarioResult) -> list[str]:
    """Cles de metriques presentes dans toutes les variantes (ordre de la premiere)."""
    if not result.variants:
        return []
    others = [{m.key for m in v.metrics} for v in result.variants[1:]]
    return [m.key for m in result.variants[0].metrics if all(m.key in keys for keys in others)]


def side_by_side_frame(result: ScenarioResult, keys: list[str]) -> pd.DataFrame:
    """Une ligne par grandeur `keys`, une colonne par variante (ex. A vulnérable / protégé)."""
    columns = ["Grandeur mesurée"] + [v.label for v in result.variants]
    rows = []
    for key in keys:
        metrics = [result.metric(v.name, key) for v in result.variants]
        rows.append([metrics[0].label] + [_value_with_unit(m) for m in metrics])
    return pd.DataFrame(rows, columns=columns)


__all__ = [
    "CHECK_COLUMNS",
    "METRIC_COLUMNS",
    "NOT_MEASURED_LABEL",
    "SCENARIO_COLUMNS",
    "SIMULATION_LABEL",
    "checks_to_frame",
    "common_metric_keys",
    "format_value",
    "metrics_to_frame",
    "scenarios_to_frame",
    "side_by_side_frame",
    "simulation_banner",
]
