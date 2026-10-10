"""Modeles de resultat du moteur de scenarios de demo (#47).

Chaque chiffre porte est un `MeasuredMetric` calcule sur l'etat final d'une
simulation (jamais une valeur en dur, cf. docs/CLAIMS.md). `value=None` signifie
« non mesure ». Les `checks` comparent l'attendu qualitatif de l'issue #47 a ce
qui a ete mesure : ils constatent, ils ne garantissent rien.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from dashboard.demo_data import DemoDataset

if TYPE_CHECKING:
    from dashboard.scenarios.config import SimulationParams

SIMULATION_LABEL = "simulation hors chaîne"


def simulation_banner(replace_by: list[int] | tuple[int, ...]) -> str:
    """Bandeau texte : « simulation hors chaîne, à remplacer par #4, #5 »."""
    refs = ", ".join(f"#{n}" for n in replace_by)
    return f"{SIMULATION_LABEL}, à remplacer par {refs}" if refs else SIMULATION_LABEL


class ScenarioStatus(str, Enum):
    """Issue d'un lancement de scenario."""

    COMPLETED = "completed"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


STATUS_LABELS: dict[ScenarioStatus, str] = {
    ScenarioStatus.COMPLETED: "terminé",
    ScenarioStatus.DISABLED: "désactivé",
    ScenarioStatus.UNAVAILABLE: "non disponible",
}


class MeasuredMetric(BaseModel):
    """Grandeur mesuree sur l'etat final (montants : int en base units)."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: int | float | None
    unit: str
    source: str = SIMULATION_LABEL


class ScenarioCheck(BaseModel):
    """Attendu qualitatif de l'issue confronte a la mesure."""

    model_config = ConfigDict(extra="forbid")

    label: str
    expected: str
    passed: bool


class ScenarioVariant(BaseModel):
    """Une issue rejouee (ex. contrat vulnerable / protege) et son jeu de donnees."""

    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    metrics: list[MeasuredMetric]
    checks: list[ScenarioCheck]
    dataset: DemoDataset
    end_time: datetime


class ScenarioResult(BaseModel):
    """Resultat complet d'un lancement de scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    seed: int
    status: ScenarioStatus
    message: str
    simulated: bool
    replace_by: list[int]
    variants: list[ScenarioVariant]

    def variant(self, variant_name: str) -> ScenarioVariant:
        """Renvoie la variante `variant_name` (KeyError si absente)."""
        for variant in self.variants:
            if variant.name == variant_name:
                return variant
        raise KeyError(variant_name)

    def metric(self, variant_name: str, key: str) -> MeasuredMetric:
        """Renvoie la metrique `key` de la variante `variant_name` (KeyError si absente)."""
        for metric in self.variant(variant_name).metrics:
            if metric.key == key:
                return metric
        raise KeyError(key)


@dataclass(frozen=True)
class ScenarioSpec:
    """Description d'un scenario enregistre ; `runner` est la seule partie a remplacer."""

    id: str
    title: str
    description: str
    expected: str
    optional: bool
    depends_on: tuple[int, ...]
    replace_by: tuple[int, ...]
    runner: Callable[[int, SimulationParams], ScenarioResult]
