"""Calibration des valeurs de l'issue #3 sur le trafic synthetique (donnees FICTIVES).

Rejoue les jeux de `data.generate` dans les surveillants de `detection` (#11, #12) et mesure,
selon le protocole de la §5 (`docs/OPEN_ANSWERS.md`) :

1. **Fenetre Ghost W** : part de l'offre immobilisee en Ghost sur le trafic normal (friction,
   §0bis conséquence 1) pour plusieurs W.
2. **Seuil de declenchement** du surveillant de transferts (z robustes volume et Herfindahl) :
   balayage, avec pour chaque couple le taux de faux positifs sur le trafic normal et, pour
   plusieurs tailles d'attaque (scenario B, en part de l'offre au moment de l'attaque), la
   detection **avant conversion** et la marge. Le balayage est repete pour plusieurs **profils
   de trafic legitime** (taille des transferts), dont le resultat depend fortement.
3. **Surveillant de mint** : alertes sur le trafic normal et les scenarios A et B.
4. **Budget de quarantaine et facteur d'allongement** : en rejouant l'alerte B dans la reponse
   graduee (`response/`), la part de l'offre placee sous retard et la question de savoir si le
   plafond `max_monitor_delay_minutes` suffit a tenir jusqu'a la fenetre Ghost `W` (§9).

Le script **mesure**, il ne choisit pas : le point retenu sur la courbe est une decision
d'equipe (§5 Q2). Tous les resultats sont des mesures sur simulation, avec des parametres de
generation eux-memes a calibrer (`docs/CLAIMS.md`).

Lancement : `python -m data.calibrate` (ou `make calibrate`).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

from data.late_marking import run as late_marking_run, to_markdown as late_marking_md
from data.generate import (
    DEFAULT_OUT_DIR,
    GeneratedScenario,
    UNIT,
    GenerationParams,
    generate_normal,
    generate_scenario_a,
    generate_scenario_b,
    event_time,
)
from detection.detector import RuleBasedMonitor
from detection.inputs import MintContext
from detection.params import TransferRuleParams
from response.orchestrator import (
    PerimeterState,
    ResponseOrchestrator,
    ResponsePolicy,
    _key,
)
from shared.models import Alert, MintEvent, MintRequest, TransferEvent

# Guardians FICTIFS pour la reponse graduee rejouee (mesure du budget de quarantaine).
_QUARANTINE_GUARDIANS = (
    "0x1111111111111111111111111111111111111111",
    "0x2222222222222222222222222222222222222222",
    "0x3333333333333333333333333333333333333333",
)


class _FixedClock:
    """Horloge fixe pour rejouer la reponse de maniere deterministe (tests/mesure)."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


@dataclass(frozen=True)
class CalibrationConfig:
    """Grilles balayees (choix de mesure, pas des valeurs actees).

    Attributes:
        seed: graine des jeux generes.
        days: jours simules ; la baseline compare le meme creneau d'un jour a l'autre et exige
            `min_history_slots` jours d'historique avant d'alerter.
        users: population legitime.
        ghost_windows: fenetres W balayees (minutes).
        reference_window: W utilisee pour la marge avant conversion (§0bis : 10 min).
        volume_z: seuils balayes du z robuste sur volume / offre.
        hhi_z: seuils balayes du z robuste sur le Herfindahl.
        attack_sizes: tailles d'attaque B, en part de l'offre au moment de l'attaque.
        profiles: profils de trafic legitime, nom -> `transfer_fraction` (part du solde
            envoyee par transfert).
    """

    seed: int = 42
    days: int = 8
    users: int = 200
    ghost_windows: tuple[int, ...] = (5, 10, 15, 30)
    reference_window: int = 10
    volume_z: tuple[float, ...] = (2.0, 3.0, 4.0, 6.0)
    hhi_z: tuple[float, ...] = (2.0, 3.0, 4.0)
    attack_sizes: tuple[float, ...] = (0.005, 0.02, 0.05, 0.1)
    profiles: tuple[tuple[str, tuple[float, float]], ...] = (
        ("gros_transferts", (0.05, 0.5)),
        ("petits_transferts", (0.01, 0.1)),
    )

    def __post_init__(self) -> None:
        if self.days < TransferRuleParams().min_history_slots + 1:
            raise ValueError("days trop court : la baseline n'aurait jamais assez d'historique.")
        if not all(0 < size for size in self.attack_sizes):
            raise ValueError("attack_sizes doit etre > 0.")

    def params(self, **overrides: Any) -> GenerationParams:
        """Parametres de generation : attaque a 18 h le dernier jour."""
        values: dict[str, Any] = {
            "seed": self.seed,
            "hours": 24.0 * self.days,
            "users": self.users,
            "ghost_window_minutes": self.reference_window,
            "attack_at_fraction": (self.days - 1 + 0.75) / self.days,
        }
        values.update(overrides)
        return GenerationParams(**values)


@dataclass(frozen=True)
class SlotOutcome:
    """Une tranche cloturee par le surveillant de transferts."""

    slot_end: datetime
    evaluated: bool
    volume_ratio: float
    alert: Alert | None


def replay_transfers(scenario: GeneratedScenario, params: TransferRuleParams) -> list[SlotOutcome]:
    """Rejoue un jeu dans `RuleBasedMonitor.check_transfer`.

    L'offre en circulation suit les mints observes (offre initiale du manifeste + mints).
    """
    manifest = scenario.manifest
    tparams = replace(params, exit_points=frozenset(manifest["exit_points"]))
    supply = manifest["initial_supply"]
    monitor = RuleBasedMonitor(
        transfer_params=tparams,
        circulating_supply=supply,
        known_addresses=manifest["known_addresses"],
    )
    outcomes: list[SlotOutcome] = []
    last = None

    def record(alert: Alert | None) -> None:
        nonlocal last
        stats = monitor.last_slot_stats
        if stats is None or stats is last:
            return
        last = stats
        outcomes.append(
            SlotOutcome(
                slot_end=stats.slot_end,
                evaluated=stats.volume_zscore is not None,
                volume_ratio=stats.volume_ratio,
                alert=alert,
            )
        )

    for event in scenario.events:
        if isinstance(event, MintEvent):
            supply += event.amount
            monitor.update_circulating_supply(supply)
        elif isinstance(event, TransferEvent):
            record(monitor.check_transfer(event))
    end = max(event_time(e) for e in scenario.events)
    record(monitor.close_slot_if_due(end + timedelta(days=1)))
    return outcomes


def _alert_addresses(alert: Alert) -> set[str]:
    return {alert.subject_address.lower(), *(seed.address.lower() for seed in alert.seeds)}


def false_positives(outcomes: Iterable[SlotOutcome]) -> dict[str, Any]:
    """Faux positifs sur le trafic normal (§5 Q2) : tranches evaluees qui alertent."""
    outcomes = list(outcomes)
    evaluated = [o for o in outcomes if o.evaluated]
    alerts = [o for o in evaluated if o.alert is not None]
    return {
        "evaluated_slots": len(evaluated),
        "fp_slots": len(alerts),
        "fp_rate": len(alerts) / len(evaluated) if evaluated else None,
        # Borne haute de la part d'offre concernee : tout le volume de la tranche fautive.
        "fp_max_volume_share": max((o.volume_ratio for o in alerts), default=0.0),
    }


def attack_detection(
    scenario: GeneratedScenario, outcomes: Iterable[SlotOutcome], window_minutes: int
) -> dict[str, Any]:
    """Detection de l'attaque B avant conversion (§5 Q1/Q3).

    Une alerte compte si elle vise une adresse de l'attaque (sujet ou graine). La marge se
    mesure depuis l'entree de la valeur dans le Ghost (mint observe), §0bis-b.
    """
    attack = scenario.manifest["attack"]
    targets = {
        a.lower() for a in (attack["attacker"], *attack["fresh_addresses"], attack["exit_point"])
    }
    mint = next(
        e for e in scenario.events if isinstance(e, MintEvent) and e.request_id in attack["request_ids"]
    )
    t0 = mint.observed_at
    hits = [
        o for o in outcomes if o.alert is not None and o.slot_end >= t0 and _alert_addresses(o.alert) & targets
    ]
    if not hits:
        return {"detected": False, "latency_seconds": None, "margin_seconds": None, "before_conversion": False}
    first = min(hits, key=lambda o: o.slot_end)
    latency = (first.slot_end - t0).total_seconds()
    margin = window_minutes * 60 - latency
    return {
        "detected": True,
        "latency_seconds": latency,
        "margin_seconds": margin,
        "before_conversion": margin > 0,
    }


def ghost_window_friction(config: CalibrationConfig) -> list[dict[str, Any]]:
    """Part de l'offre immobilisee en Ghost sur le trafic normal, pour chaque W."""
    rows = []
    for window in config.ghost_windows:
        manifest = generate_normal(config.params(ghost_window_minutes=window)).manifest
        share = manifest["ghost_share_of_supply"]
        rows.append({"window_minutes": window, "median": share["median"], "p95": share["p95"]})
    return rows


def supply_at(scenario: GeneratedScenario, moment: datetime) -> int:
    """Offre (base units) a `moment` : offre initiale + mints observes avant."""
    minted = sum(e.amount for e in scenario.events if isinstance(e, MintEvent) and e.observed_at < moment)
    return scenario.manifest["initial_supply"] + minted


def trigger_sweep(config: CalibrationConfig, transfer_fraction: tuple[float, float]) -> list[dict[str, Any]]:
    """Balayage des seuils de declenchement : FP sur normal, detection par taille d'attaque."""
    base = config.params(transfer_fraction=transfer_fraction)
    normal = generate_normal(base)
    supply = supply_at(normal, base.attack_at)
    attacks = {
        size: generate_scenario_b(
            replace(base, attack_deposit_tokens=max(1, int(size * supply / UNIT)))
        )
        for size in config.attack_sizes
    }
    rows = []
    for vz in config.volume_z:
        for hz in config.hhi_z:
            params = TransferRuleParams(volume_z_threshold=vz, hhi_z_threshold=hz)
            row: dict[str, Any] = {"volume_z": vz, "hhi_z": hz}
            row.update(false_positives(replay_transfers(normal, params)))
            row["attacks"] = {
                str(size): attack_detection(b, replay_transfers(b, params), config.reference_window)
                for size, b in attacks.items()
            }
            rows.append(row)
    return rows


def mint_monitor(config: CalibrationConfig) -> dict[str, dict[str, int]]:
    """Alertes du surveillant de mint (I1 au taux 1:1) sur normal, A et B."""
    params = config.params()
    scenarios = {"normal": generate_normal(params), "B": generate_scenario_b(params)}
    for variant, scenario in generate_scenario_a(params).items():
        scenarios[f"A_{variant}"] = scenario
    results: dict[str, dict[str, int]] = {}
    for name, scenario in scenarios.items():
        attack = scenario.manifest["attack"] or {}
        attack_ids = set(attack.get("request_ids", []))
        deposits = {e.request_id: e.deposit_amount for e in scenario.events if isinstance(e, MintRequest)}
        monitor = RuleBasedMonitor()
        alerts = {"mints": 0, "alerts_on_attack": 0, "alerts_elsewhere": 0, "attack_mints": 0}
        for event in scenario.events:
            if not isinstance(event, MintEvent):
                continue
            alerts["mints"] += 1
            on_attack = event.request_id in attack_ids
            alerts["attack_mints"] += on_attack
            context = MintContext(deposit_amount=deposits[event.request_id], rate=Fraction(1))
            if monitor.check_mint(event, context) is not None:
                alerts["alerts_on_attack" if on_attack else "alerts_elsewhere"] += 1
        results[name] = alerts
    return results


def quarantine_budget(
    config: CalibrationConfig, transfer_fraction: tuple[float, float]
) -> list[dict[str, Any]]:
    """Budget de quarantaine et facteur d'allongement, en rejouant l'alerte dans `response/`.

    Pour chaque taille d'attaque B (part de l'offre), on rejoue le jeu dans le surveillant de
    transferts au seuil propose (`z volume`/`z HHI` = premieres valeurs 0 FP de la grille), on
    envoie l'alerte produite a `ResponseOrchestrator.handle_alert`, et on mesure :

    - **budget de quarantaine** : part de l'offre placee sous retard par la reponse (somme des
      `suspect_amount` des perimetres retardes / offre au moment de l'attaque). C'est la friction
      *ciblee* du retard, a distinguer de la friction *de fond* du Ghost (`ghost_window_friction`).
    - **facteur d'allongement** : le plafond `max_monitor_delay_minutes` qu'un surveillant atteint
      seul suffit-il a maintenir la conversion suspendue jusqu'a la fenetre Ghost `W` (sinon le
      retard expire avant que le multisig humain ait pu trancher) ? On compare la duree de retard
      obtenue a `W`.

    Le script **mesure**, il ne choisit pas : la part max toleree et le facteur retenu restent une
    decision d'equipe (§9). Donnees FICTIVES.
    """
    window = config.reference_window
    policy = ResponsePolicy(guardians=frozenset(_QUARANTINE_GUARDIANS))
    base = config.params(transfer_fraction=transfer_fraction)
    normal = generate_normal(base)
    supply = supply_at(normal, base.attack_at)
    # Seuil propose (support de decision #3) : z volume le plus eleve de la grille (zone 0 FP),
    # z HHI median. Indices robustes a toute taille de grille.
    params = TransferRuleParams(
        volume_z_threshold=config.volume_z[-1],
        hhi_z_threshold=config.hhi_z[len(config.hhi_z) // 2],
    )
    rows: list[dict[str, Any]] = []
    for size in config.attack_sizes:
        scenario = generate_scenario_b(
            replace(base, attack_deposit_tokens=max(1, int(size * supply / UNIT)))
        )
        attack = scenario.manifest["attack"]
        targets = {
            a.lower()
            for a in (attack["attacker"], *attack["fresh_addresses"], attack["exit_point"])
        }
        outcomes = replay_transfers(scenario, params)
        hits = [
            o
            for o in outcomes
            if o.alert is not None and _alert_addresses(o.alert) & targets
        ]
        if not hits:
            rows.append({"attack_size": size, "detected": False})
            continue
        alert = min(hits, key=lambda o: o.slot_end).alert
        clock = _FixedClock(alert.created_at)
        orchestrator = ResponseOrchestrator(policy, clock=clock)
        orchestrator.handle_alert(alert)
        # Perimetres effectivement retardes (sujet + graines) : part de l'offre sous retard.
        delayed = {_key(alert.subject_address), *(_key(s.address) for s in alert.seeds)}
        delayed_amount = sum(
            amount
            for addr, amount in (
                (alert.subject_address, alert.suspect_amount),
                *((s.address, s.suspect_amount) for s in alert.seeds),
            )
            if _key(addr) in delayed
            and orchestrator.perimeter_state(addr) is PerimeterState.DELAYED
        )
        delay = orchestrator.active_delay(alert.subject_address)
        delay_minutes = (
            (delay.expires_at - alert.created_at).total_seconds() / 60.0
            if delay is not None and delay.expires_at is not None
            else 0.0
        )
        rows.append(
            {
                "attack_size": size,
                "detected": True,
                "budget_share": delayed_amount / supply if supply else None,
                "delay_minutes": delay_minutes,
                "cap_minutes": policy.max_monitor_delay_minutes,
                "window_minutes": window,
                # Le retard tient-il au moins jusqu'a la fin de la fenetre Ghost ?
                "holds_until_window": delay_minutes >= window,
            }
        )
    return rows


def run(config: CalibrationConfig) -> dict[str, Any]:
    """Toutes les mesures, serialisables en JSON."""
    return {
        "fictive_data": True,
        "note": "mesures sur simulation ; le choix du point de fonctionnement reste a l'equipe",
        "config": json.loads(json.dumps(vars(config))),
        "ghost_window_friction": ghost_window_friction(config),
        "trigger_sweep": {name: trigger_sweep(config, fraction) for name, fraction in config.profiles},
        "quarantine_budget": {
            name: quarantine_budget(config, fraction) for name, fraction in config.profiles
        },
        "mint_monitor": mint_monitor(config),
        "late_marking": late_marking_run(),
    }


def _fmt_attack(result: dict[str, Any]) -> str:
    if not result["detected"]:
        return "non"
    mark = "" if result["before_conversion"] else " (trop tard)"
    return f"{result['margin_seconds'] / 60:+.1f} min{mark}"


def to_markdown(results: dict[str, Any]) -> str:
    """Tableaux lisibles pour l'issue #3 et le README."""
    lines = ["Fenetre Ghost W : part de l'offre en Ghost (trafic normal)", "",
             "| W (min) | mediane | p95 |", "|---|---|---|"]
    for row in results["ghost_window_friction"]:
        lines.append(f"| {row['window_minutes']} | {row['median']:.1%} | {row['p95']:.1%} |")
    window = results["config"]["reference_window"]
    for profile, rows in results["trigger_sweep"].items():
        sizes = list(rows[0]["attacks"])
        lines += ["", f"Seuils de declenchement, profil `{profile}` : faux positifs (normal) et "
                  f"marge avant conversion (scenario B, W = {window} min, taille = part de l'offre)", "",
                  "| z volume | z HHI | FP / tranches | " + " | ".join(f"B {float(s):.1%}" for s in sizes) + " |",
                  "|---|---|---|" + "---|" * len(sizes)]
        for row in rows:
            attacks = " | ".join(_fmt_attack(row["attacks"][s]) for s in sizes)
            lines.append(
                f"| {row['volume_z']:g} | {row['hhi_z']:g} | {row['fp_slots']}/{row['evaluated_slots']} | {attacks} |"
            )
    if "quarantine_budget" in results:
        for profile, rows in results["quarantine_budget"].items():
            lines += [
                "",
                f"Budget de quarantaine et facteur d'allongement, profil `{profile}` : "
                f"alerte B rejouee dans `response/` (W = {window} min, donnees fictives)",
                "",
                "| taille attaque | detectee | part de l'offre sous retard | retard obtenu | "
                "plafond surveillant | tient jusqu'a W ? |",
                "|---|---|---|---|---|---|",
            ]
            for row in rows:
                if not row.get("detected"):
                    lines.append(
                        f"| {row['attack_size']:.1%} | non | — | — | — | — |"
                    )
                    continue
                lines.append(
                    f"| {row['attack_size']:.1%} | oui | {row['budget_share']:.2%} | "
                    f"{row['delay_minutes']:.0f} min | {row['cap_minutes']} min | "
                    f"{'oui' if row['holds_until_window'] else 'non'} |"
                )
    lines += ["", "Surveillant de mint (I1, taux 1:1)", "",
              "| jeu | mints | mints d'attaque | alertes sur l'attaque | autres alertes |", "|---|---|---|---|---|"]
    for name, r in results["mint_monitor"].items():
        lines.append(f"| {name} | {r['mints']} | {r['attack_mints']} | {r['alerts_on_attack']} | {r['alerts_elsewhere']} |")
    if "late_marking" in results:
        lines += ["", late_marking_md(results["late_marking"]).rstrip()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, config: CalibrationConfig | None = None) -> None:
    """Point d'entree : `python -m data.calibrate`.

    Args:
        argv: arguments CLI.
        config: grilles a utiliser (defaut : `CalibrationConfig` avec `--seed` / `--days`).
    """
    parser = argparse.ArgumentParser(description="Calibre les valeurs de #3 (donnees FICTIVES).")
    parser.add_argument("--seed", type=int, default=CalibrationConfig.seed)
    parser.add_argument("--days", type=int, default=CalibrationConfig.days)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    results = run(config or CalibrationConfig(seed=args.seed, days=args.days))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "calibration.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    report = to_markdown(results)
    (args.out_dir / "calibration.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
