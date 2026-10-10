"""Surveillant simulé : simulation hors chaîne, à remplacer par #11/#12 (detection).

Discriminant acte
OPEN_ANSWERS §9 : « volume eleve ET dispersion effondree ». Par tranche de
temps : ratio volume/offre et dispersion (destinataires distincts / transferts) ;
baseline robuste mediane + MAD glissante. Les seuils viennent de
`SimulationParams` (a calibrer, docs/OPEN_QUESTIONS.md §6).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict

from dashboard.demo_data import _Builder
from dashboard.scenarios.config import SimulationParams
from dashboard.scenarios.models import SIMULATION_LABEL
from shared.models import Alert, AlertKind, AlertSeed, AlertSeverity, TransferEvent

MONITOR_NAME = "sim_baseline"
MAD_SCALE = 1.4826  # rend la MAD comparable a un ecart-type sous hypothese gaussienne


class BucketStat(BaseModel):
    """Statistiques d'une tranche de temps."""

    model_config = ConfigDict(extra="forbid")

    index: int
    start: datetime
    end: datetime
    transfer_count: int
    volume: int
    volume_ratio: float
    dispersion: float
    dominant_recipient: str | None
    dominant_volume: int


def bucket_stats(
    transfers: list[TransferEvent], start: datetime, bucket_minutes: int, supply: int
) -> list[BucketStat]:
    """Decoupe `transfers` en tranches de `bucket_minutes` depuis `start`.

    Une tranche vide a une dispersion de 1.0 (aucune concentration observable).
    """
    width = timedelta(minutes=bucket_minutes)
    grouped: dict[int, list[TransferEvent]] = defaultdict(list)
    for transfer in transfers:
        grouped[int((transfer.observed_at - start) / width)].append(transfer)
    count = max(grouped) + 1 if grouped else 0
    stats: list[BucketStat] = []
    for index in range(count):
        items = grouped.get(index, [])
        volume = sum(t.amount for t in items)
        by_recipient: dict[str, int] = defaultdict(int)
        for t in items:
            by_recipient[t.recipient] += t.amount
        dominant = max(by_recipient, key=lambda a: (by_recipient[a], a)) if by_recipient else None
        stats.append(
            BucketStat(
                index=index,
                start=start + index * width,
                end=start + (index + 1) * width,
                transfer_count=len(items),
                volume=volume,
                volume_ratio=volume / supply,
                dispersion=len(by_recipient) / len(items) if items else 1.0,
                dominant_recipient=dominant,
                dominant_volume=by_recipient[dominant] if dominant else 0,
            )
        )
    return stats


def robust_zscore(value: float, history: list[float], mad_floor: float) -> float:
    """(value - mediane) / (1.4826 x max(MAD, mad_floor)) ; ValueError si historique vide."""
    if not history:
        raise ValueError("historique vide")
    median = statistics.median(history)
    mad = statistics.median(abs(h - median) for h in history)
    return (value - median) / (MAD_SCALE * max(mad, mad_floor))


def detect(
    builder: _Builder, transfers: list[TransferEvent], start: datetime, params: SimulationParams
) -> list[Alert]:
    """Alerte en fin de tranche (apres warmup) si z > seuil ET dispersion < seuil.

    Au plus une alerte par adresse sujet ; une tranche declenchante n'entre pas
    dans la baseline glissante.
    """
    history: list[float] = []
    alerted: set[str] = set()
    alerts: list[Alert] = []
    for stat in bucket_stats(transfers, start, params.bucket_minutes, params.supply):
        if stat.index < params.warmup_buckets:
            history.append(stat.volume_ratio)
            continue
        zscore = robust_zscore(stat.volume_ratio, history[-params.baseline_buckets:],
                               params.mad_floor)
        triggered = (zscore > params.volume_zscore_threshold
                     and stat.dispersion < params.dispersion_threshold)
        if not triggered:
            history.append(stat.volume_ratio)
            continue
        subject = stat.dominant_recipient
        if subject is None or subject in alerted:
            continue
        alerted.add(subject)
        ratio = stat.dominant_volume / stat.volume
        alerts.append(
            builder.alert(
                AlertKind.TRANSFER, AlertSeverity.CRITICAL, stat.end, MONITOR_NAME, subject,
                ratio, stat.dominant_volume,
                f"Volume élevé (z={zscore:.1f}) ET dispersion effondrée "
                f"({stat.dispersion:.3f}) sur la tranche ({SIMULATION_LABEL}).",
                dispersion=stat.dispersion, zscore=zscore,
                seeds=[AlertSeed(address=subject, suspect_amount=stat.dominant_volume,
                                 contamination_ratio=ratio)],
            )
        )
    return alerts
