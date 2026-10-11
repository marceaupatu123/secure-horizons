"""Tests du surveillant ML + prediction conforme (#13). Donnees fictives, aucun reseau."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from detection.conformal import FEATURE_NAMES, ConformalSlotMonitor, slot_features
from detection.conformal_eval import to_markdown
from detection.transfers import TransferSlotStats

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _stats(
    volume_ratio: float,
    herfindahl: float,
    new_sender_share: float = 0.0,
    exit_share: float = 0.0,
    max_fan_out: int = 1,
    index: int = 0,
) -> TransferSlotStats:
    start = T0 + timedelta(minutes=5 * index)
    return TransferSlotStats(
        slot_start=start,
        slot_end=start + timedelta(minutes=5),
        transfer_count=10,
        volume=1,
        gross_volume=1,
        circulating_supply=1,
        volume_ratio=volume_ratio,
        herfindahl=herfindahl,
        effective_recipients=1 / herfindahl,
        distinct_recipients=10,
        new_sender_share=new_sender_share,
        exit_share=exit_share,
        max_fan_out=max_fan_out,
        history_size=0,
        volume_zscore=None,
        herfindahl_zscore=None,
    )


def _normal(rng: random.Random, n: int, offset: int = 0) -> list[TransferSlotStats]:
    """Tranches « normales » tirees d'une meme loi (donc echangeables)."""
    return [
        _stats(
            volume_ratio=rng.lognormvariate(-7, 0.3),
            herfindahl=rng.uniform(0.05, 0.12),
            new_sender_share=rng.uniform(0, 0.05),
            exit_share=rng.uniform(0, 0.1),
            max_fan_out=rng.randint(1, 3),
            index=offset + i,
        )
        for i in range(n)
    ]


def test_features_follow_documented_order() -> None:
    s = _stats(0.01, 0.2, 0.3, 0.4, max_fan_out=0)
    assert len(slot_features(s)) == len(FEATURE_NAMES)
    assert slot_features(s)[:4] == [0.01, 0.2, 0.3, 0.4]
    assert slot_features(s)[4] == 0.0  # log1p(0)


def test_empirical_false_positive_rate_close_to_alpha() -> None:
    rng = random.Random(1)
    monitor = ConformalSlotMonitor(alpha=0.05, n_estimators=50).fit(_normal(rng, 800))
    test = _normal(rng, 2000, offset=800)
    rate = sum(monitor.check(s).anomalous for s in test) / len(test)
    # Garantie conforme : <= alpha en esperance ; marge d'echantillonnage.
    assert rate <= 0.05 + 0.02


def test_obvious_attack_slot_is_flagged() -> None:
    rng = random.Random(2)
    monitor = ConformalSlotMonitor(alpha=0.01, n_estimators=50).fit(_normal(rng, 600))
    attack = _stats(0.05, 0.9, new_sender_share=0.9, exit_share=0.9, max_fan_out=4)
    verdict = monitor.check(attack)
    assert verdict.anomalous
    assert verdict.p_value == pytest.approx(monitor.min_reachable_p_value)


def test_p_value_formula() -> None:
    monitor = ConformalSlotMonitor(alpha=0.5)
    monitor._calibration = [1.0, 2.0, 3.0]  # scores tries
    assert monitor.p_value(10.0) == 1 / 4
    assert monitor.p_value(2.0) == 3 / 4
    assert monitor.p_value(0.0) == 1.0


def test_too_small_calibration_is_refused() -> None:
    rng = random.Random(3)
    with pytest.raises(ValueError, match="calibration"):
        ConformalSlotMonitor(alpha=0.01, n_estimators=10).fit(_normal(rng, 100))


def test_unfitted_monitor_raises() -> None:
    with pytest.raises(RuntimeError):
        ConformalSlotMonitor().check(_stats(0.001, 0.1))


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1])
def test_invalid_alpha(alpha: float) -> None:
    with pytest.raises(ValueError):
        ConformalSlotMonitor(alpha=alpha)


def test_markdown_report_renders() -> None:
    results = {
        "p": {
            "rows": [
                {
                    "alpha": 0.01,
                    "calibration_slots": 100,
                    "test_slots": 10,
                    "fp_slots": 1,
                    "fp_rate": 0.1,
                    "attacks": {"0.02": {"detected": True, "min_p_value": 0.0099, "other_flagged": 0}},
                }
            ]
        }
    }
    report = to_markdown(results)
    assert "B 2.0%" in report and "oui (p=0.010)" in report and "1/10 (10.0%)" in report
