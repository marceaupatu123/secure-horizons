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
REAL_LABEL = "implémentation réelle"


def _refs(numbers: list[int] | tuple[int, ...]) -> str:
    return ", ".join(f"#{n}" for n in numbers)


def simulation_banner(replace_by: list[int] | tuple[int, ...]) -> str:
    """Bandeau texte : « simulation hors chaîne, à remplacer par #4, #5 »."""
    refs = _refs(replace_by)
    return f"{SIMULATION_LABEL}, à remplacer par {refs}" if refs else SIMULATION_LABEL


def real_source(refs: list[int] | tuple[int, ...]) -> str:
    """Source d'une grandeur calculee par le vrai code : « implémentation réelle (#11, #12) »."""
    return f"{REAL_LABEL} ({_refs(refs)})" if refs else REAL_LABEL


def implementation_banner(real: list[int] | tuple[int, ...],
                          replace_by: list[int] | tuple[int, ...]) -> str:
    """« implémentation réelle : #11, #12 ; simulation hors chaîne, à remplacer par #8 ».

    Le bandeau « simulation hors chaîne » n'apparait que s'il reste une brique simulee.
    """
    parts = [f"{REAL_LABEL} : {_refs(real)}"] if real else []
    if replace_by or not real:
        parts.append(simulation_banner(replace_by))
    return " ; ".join(parts)


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
    """Description d'un scenario enregistre ; `runner` est la seule partie a remplacer.

    `replace_by` : briques encore simulees (par defaut). `implemented_by` : briques
    toujours branchees sur le vrai code. `opt_in_by` : briques branchees sur le vrai
    code seulement si un backend optionnel est active (`opt_in_hint`), avec repli
    automatique sur la simulation sinon.
    """

    id: str
    title: str
    description: str
    expected: str
    optional: bool
    depends_on: tuple[int, ...]
    replace_by: tuple[int, ...]
    runner: Callable[[int, SimulationParams], ScenarioResult]
    implemented_by: tuple[int, ...] = ()
    opt_in_by: tuple[int, ...] = ()
    opt_in_hint: str = ""

    def implementation_label(self) -> str:
        """Etat de branchement du scenario (catalogue), en texte."""
        label = implementation_banner(self.implemented_by, self.replace_by)
        if self.opt_in_by:
            label += (f" (backend réel optionnel pour {_refs(self.opt_in_by)} : "
                      f"{self.opt_in_hint})")
        return label

    def result_banner(self, result: ScenarioResult) -> str:
        """Bandeau d'un resultat : briques reelles effectivement utilisees + reste simule."""
        remaining = set(result.replace_by)
        real = [n for n in sorted({*self.implemented_by, *self.opt_in_by}) if n not in remaining]
        return implementation_banner(real, result.replace_by)
