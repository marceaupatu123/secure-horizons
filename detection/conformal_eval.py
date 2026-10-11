"""Mesure du surveillant conforme (#13) sur le trafic synthetique (donnees FICTIVES).

Lancement : `python -m detection.conformal_eval [--seed N] [--days D]`.

Protocole (choix de mesure PROVISOIRES, docs/OPEN_QUESTIONS.md §13) :

- trafic normal de `data.generate` sur D jours ; les D-1 premiers jours servent
  a entrainer + calibrer `ConformalSlotMonitor` ;
- dernier jour du trafic normal (jamais vu) : taux de faux positifs MESURE,
  a comparer au `alpha` vise ;
- scenario B (meme trafic + attaque le dernier jour, plusieurs tailles) :
  l'attaque est detectee si une tranche qui chevauche `[mint, mint + W]` est
  signalee (W = fenetre Ghost de reference, 10 min).

Le script mesure, il ne choisit rien. Resultats valables pour CE generateur et
CES parametres seulement (`docs/CLAIMS.md`).
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from data.calibrate import CalibrationConfig, supply_at
from data.generate import (
    UNIT,
    GeneratedScenario,
    event_time,
    generate_normal,
    generate_scenario_b,
)
from detection.conformal import ConformalSlotMonitor
from detection.detector import RuleBasedMonitor
from detection.params import TransferRuleParams
from detection.transfers import TransferSlotStats
from shared.models import MintEvent, TransferEvent

ALPHAS: tuple[float, ...] = (0.01, 0.05)


@dataclass(frozen=True)
class EvalConfig:
    """Reglages de la mesure (pas des valeurs actees)."""

    seed: int = 42
    days: int = 8
    alphas: tuple[float, ...] = ALPHAS
    attack_sizes: tuple[float, ...] = CalibrationConfig.attack_sizes
    profiles: tuple[tuple[str, tuple[float, float]], ...] = CalibrationConfig.profiles


def collect_slot_stats(scenario: GeneratedScenario) -> list[TransferSlotStats]:
    """Rejoue un jeu dans `RuleBasedMonitor` et garde les mesures de chaque tranche.

    Les z robustes ne servent pas ici : seules les caracteristiques de la
    tranche (`slot_features`) sont utilisees.
    """
    manifest = scenario.manifest
    supply = manifest["initial_supply"]
    monitor = RuleBasedMonitor(
        transfer_params=TransferRuleParams(exit_points=frozenset(manifest["exit_points"])),
        circulating_supply=supply,
        known_addresses=manifest["known_addresses"],
    )
    collected: list[TransferSlotStats] = []

    def record() -> None:
        stats = monitor.last_slot_stats
        if stats is not None and (not collected or stats is not collected[-1]):
            collected.append(stats)

    for event in scenario.events:
        if isinstance(event, MintEvent):
            supply += event.amount
            monitor.update_circulating_supply(supply)
        elif isinstance(event, TransferEvent):
            monitor.check_transfer(event)
            record()
    end = max(event_time(e) for e in scenario.events)
    monitor.close_slot_if_due(end + timedelta(days=1))
    record()
    return collected


def _split_last_day(
    slots: list[TransferSlotStats], start: datetime, days: int
) -> tuple[list[TransferSlotStats], list[TransferSlotStats]]:
    cutoff = start + timedelta(days=days - 1)
    return [s for s in slots if s.slot_end <= cutoff], [s for s in slots if s.slot_start >= cutoff]


def _attack_mint_time(scenario: GeneratedScenario) -> datetime:
    request_ids = scenario.manifest["attack"]["request_ids"]
    return next(
        e.observed_at
        for e in scenario.events
        if isinstance(e, MintEvent) and e.request_id in request_ids
    )


def evaluate_profile(
    config: EvalConfig, transfer_fraction: tuple[float, float]
) -> dict[str, Any]:
    """Mesure FP (normal, jour retenu) et detection de B pour un profil de trafic."""
    calib_config = CalibrationConfig(seed=config.seed, days=config.days)
    base = calib_config.params(transfer_fraction=transfer_fraction)
    window = timedelta(minutes=calib_config.reference_window)
    normal = generate_normal(base)
    fit_slots, test_slots = _split_last_day(collect_slot_stats(normal), base.start, config.days)
    supply = supply_at(normal, base.attack_at)
    attacks: dict[float, tuple[datetime, list[TransferSlotStats]]] = {}
    for size in config.attack_sizes:
        scenario = generate_scenario_b(
            replace(base, attack_deposit_tokens=max(1, int(size * supply / UNIT)))
        )
        _, last_day = _split_last_day(collect_slot_stats(scenario), base.start, config.days)
        attacks[size] = (_attack_mint_time(scenario), last_day)

    rows = []
    for alpha in config.alphas:
        monitor = ConformalSlotMonitor(alpha=alpha, seed=config.seed).fit(fit_slots)
        flagged = sum(monitor.check(s).anomalous for s in test_slots)
        row: dict[str, Any] = {
            "alpha": alpha,
            "calibration_slots": monitor.calibration_size,
            "test_slots": len(test_slots),
            "fp_slots": flagged,
            "fp_rate": flagged / len(test_slots) if test_slots else None,
            "attacks": {},
        }
        for size, (t0, slots) in attacks.items():
            in_window = [s for s in slots if s.slot_end > t0 and s.slot_start <= t0 + window]
            hits = [s for s in in_window if monitor.check(s).anomalous]
            others = [s for s in slots if s not in in_window]
            row["attacks"][str(size)] = {
                "detected": bool(hits),
                "min_p_value": min((monitor.check(s).p_value for s in in_window), default=None),
                "other_flagged": sum(monitor.check(s).anomalous for s in others),
            }
        rows.append(row)
    return {"rows": rows}


def run(config: EvalConfig) -> dict[str, Any]:
    """Mesure complete, un bloc par profil de trafic."""
    return {name: evaluate_profile(config, fraction) for name, fraction in config.profiles}


def to_markdown(results: dict[str, Any]) -> str:
    """Rapport lisible (tableaux markdown)."""
    lines = ["Surveillant conforme (IsolationForest + split conformal), donnees FICTIVES", ""]
    for profile, block in results.items():
        sizes = list(block["rows"][0]["attacks"]) if block["rows"] else []
        lines.append(f"Profil `{profile}` : FP mesure (dernier jour normal) vs alpha vise ; "
                     "detection de B dans [mint, mint + W]")
        lines.append("")
        lines.append("| alpha | calib | FP mesure | " + " | ".join(f"B {float(s):.1%}" for s in sizes) + " |")
        lines.append("|---|---|---|" + "---|" * len(sizes))
        for row in block["rows"]:
            cells = []
            for size in sizes:
                a = row["attacks"][size]
                p = a["min_p_value"]
                cells.append(("oui" if a["detected"] else "non") + (f" (p={p:.3f})" if p is not None else ""))
            lines.append(
                f"| {row['alpha']} | {row['calibration_slots']} | "
                f"{row['fp_slots']}/{row['test_slots']} ({row['fp_rate']:.1%}) | " + " | ".join(cells) + " |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Point d'entree : affiche le rapport (et le JSON avec --json)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=EvalConfig.seed)
    parser.add_argument("--days", type=int, default=EvalConfig.days)
    parser.add_argument("--json", action="store_true", help="sortie JSON brute")
    args = parser.parse_args(argv)
    # Le rejeu loggue une ligne par tranche non evaluee par les regles : bruit ici.
    logging.getLogger("detection.detector").setLevel(logging.ERROR)
    results = run(EvalConfig(seed=args.seed, days=args.days))
    print(json.dumps(results, indent=2) if args.json else to_markdown(results))


if __name__ == "__main__":
    main()
