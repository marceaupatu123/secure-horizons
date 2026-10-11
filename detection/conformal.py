"""Surveillant ML + prediction conforme sur les tranches de transferts (#13, OPTIONNEL).

Piste de recherche (vague 5). N'est PAS branche au pipeline ni au module de
reponse : OPEN_ANSWERS §1 a ecarte la prediction conforme pour la demo au profit
de seuils simples mesures. Ce module sert a MESURER si elle apporte quelque
chose (`python -m detection.conformal_eval`).

Principe (prediction conforme « split », detection d'anomalie) :

1. On decrit chaque tranche cloturee par un petit vecteur de caracteristiques
   tirees de `TransferSlotStats` (ratios normalises uniquement, §9).
2. Un modele non supervise (`IsolationForest`, scikit-learn) est entraine sur
   une partie du trafic NORMAL ; son score d'anomalie sert de score de
   non-conformite.
3. Sur une partie DISJOINTE du trafic normal (calibration), on garde les
   scores. Pour une nouvelle tranche de score `s`, la p-valeur conforme est
   `p = (1 + #{scores de calibration >= s}) / (n + 1)`.
4. Alerte si `p <= alpha`.

Garantie (et sa limite, a dire telle quelle) : si la tranche testee est
ECHANGEABLE avec les tranches de calibration (en gros : tiree de la meme
distribution), la probabilite qu'une tranche normale soit signalee est
`<= alpha`, quel que soit le modele. La garantie tombe des que le trafic de
test ne ressemble plus au trafic de calibration (croissance, saisonnalite non
couverte, changement d'usage). Elle est MARGINALE (par tranche, en moyenne),
pas une borne sur le nombre de faux positifs d'une journee donnee, et elle ne
dit RIEN sur la detection des attaques. Ce n'est pas une preuve de securite
(`docs/CLAIMS.md`).

Tous les choix ci-dessous (caracteristiques, modele, partage 50/50, graine)
sont PROVISOIRES, choisis par l'assistant (2026-10-11), voir
docs/OPEN_QUESTIONS.md §13.
"""

from __future__ import annotations

import bisect
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest

from detection.transfers import TransferSlotStats

# Ordre des caracteristiques (documentation + tests).
FEATURE_NAMES: tuple[str, ...] = (
    "volume_ratio",
    "herfindahl",
    "new_sender_share",
    "exit_share",
    "log1p_max_fan_out",
)

# PROVISOIRE — part du trafic normal utilisee pour entrainer le modele ; le
# reste sert a la calibration conforme.
DEFAULT_TRAIN_FRACTION = 0.5
# PROVISOIRE — nombre d'arbres de l'IsolationForest.
DEFAULT_N_ESTIMATORS = 200
DEFAULT_SEED = 0


def slot_features(stats: TransferSlotStats) -> list[float]:
    """Vecteur de caracteristiques d'une tranche (ratios, jamais d'absolu).

    Args:
        stats: mesures d'une tranche cloturee.

    Returns:
        Les valeurs dans l'ordre de `FEATURE_NAMES`.
    """
    return [
        stats.volume_ratio,
        stats.herfindahl,
        stats.new_sender_share,
        stats.exit_share,
        math.log1p(stats.max_fan_out),
    ]


@dataclass(frozen=True)
class ConformalVerdict:
    """Resultat pour une tranche.

    Attributes:
        score: score de non-conformite (plus haut = plus anormal).
        p_value: p-valeur conforme dans `]0, 1]`.
        alpha: niveau utilise.
        anomalous: `p_value <= alpha`.
    """

    score: float
    p_value: float
    alpha: float
    anomalous: bool


class ConformalSlotMonitor:
    """IsolationForest + calibration conforme sur des tranches normales."""

    def __init__(
        self,
        alpha: float = 0.01,
        *,
        train_fraction: float = DEFAULT_TRAIN_FRACTION,
        n_estimators: int = DEFAULT_N_ESTIMATORS,
        seed: int = DEFAULT_SEED,
    ) -> None:
        """Prepare le surveillant (non entraine).

        Args:
            alpha: taux de faux positifs vise par tranche (PROVISOIRE).
            train_fraction: part des tranches normales pour l'entrainement.
            n_estimators: arbres de l'IsolationForest.
            seed: graine (partage + modele) pour des mesures reproductibles.

        Raises:
            ValueError: si un parametre est hors bornes.
        """
        if not 0 < alpha < 1:
            raise ValueError("alpha doit etre dans ]0, 1[")
        if not 0 < train_fraction < 1:
            raise ValueError("train_fraction doit etre dans ]0, 1[")
        self.alpha = alpha
        self._train_fraction = train_fraction
        self._n_estimators = n_estimators
        self._seed = seed
        self._model: IsolationForest | None = None
        self._calibration: list[float] = []

    @property
    def calibration_size(self) -> int:
        """Nombre de tranches de calibration."""
        return len(self._calibration)

    @property
    def min_reachable_p_value(self) -> float:
        """Plus petite p-valeur atteignable : `1 / (n + 1)`.

        Si elle depasse `alpha`, le surveillant ne peut JAMAIS alerter : il
        faut au moins `ceil(1/alpha) - 1` tranches de calibration.
        """
        return 1 / (self.calibration_size + 1)

    def fit(self, normal_slots: Sequence[TransferSlotStats]) -> ConformalSlotMonitor:
        """Entraine le modele et calibre sur du trafic NORMAL uniquement.

        Le partage entrainement / calibration est aleatoire (graine fixe) pour
        que les deux parties couvrent les memes creneaux horaires.

        Args:
            normal_slots: tranches de trafic legitime (aucune attaque).

        Returns:
            `self`, pour chainer.

        Raises:
            ValueError: s'il y a trop peu de tranches pour pouvoir alerter au
                niveau `alpha`.
        """
        indices = list(range(len(normal_slots)))
        random.Random(self._seed).shuffle(indices)
        cut = int(len(indices) * self._train_fraction)
        train = [normal_slots[i] for i in indices[:cut]]
        calib = [normal_slots[i] for i in indices[cut:]]
        needed = math.ceil(1 / self.alpha) - 1
        if len(calib) < needed or not train:
            raise ValueError(
                f"{len(calib)} tranches de calibration : il en faut au moins {needed} "
                f"pour pouvoir alerter a alpha={self.alpha}"
            )
        self._model = IsolationForest(
            n_estimators=self._n_estimators, random_state=self._seed
        ).fit(self._matrix(train))
        self._calibration = sorted(self._scores(calib))
        return self

    def score(self, stats: TransferSlotStats) -> float:
        """Score de non-conformite d'une tranche (plus haut = plus anormal)."""
        return self._scores([stats])[0]

    def p_value(self, score: float) -> float:
        """p-valeur conforme d'un score : `(1 + #{calib >= score}) / (n + 1)`."""
        if not self._calibration:
            raise RuntimeError("surveillant non calibre : appeler fit() d'abord")
        at_least = len(self._calibration) - bisect.bisect_left(self._calibration, score)
        return (1 + at_least) / (len(self._calibration) + 1)

    def check(self, stats: TransferSlotStats) -> ConformalVerdict:
        """Evalue une tranche cloturee.

        Args:
            stats: mesures de la tranche.

        Returns:
            Le verdict (signal d'appoint : n'emet aucune `Alert` et ne
            declenche aucune action).
        """
        s = self.score(stats)
        p = self.p_value(s)
        return ConformalVerdict(score=s, p_value=p, alpha=self.alpha, anomalous=p <= self.alpha)

    @staticmethod
    def _matrix(slots: Sequence[TransferSlotStats]) -> np.ndarray:
        return np.array([slot_features(s) for s in slots], dtype=float)

    def _scores(self, slots: Sequence[TransferSlotStats]) -> list[float]:
        if self._model is None:
            raise RuntimeError("surveillant non entraine : appeler fit() d'abord")
        # score_samples : plus bas = plus anormal ; on inverse le signe.
        return [-float(v) for v in self._model.score_samples(self._matrix(slots))]
