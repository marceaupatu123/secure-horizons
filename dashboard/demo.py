"""CLI des scenarios de demo (#47) : `python -m dashboard.demo list|run <id>`.

Point d'entree unique pour lister et rejouer (seed fixe) les scenarios A, B, C,
D, N1, N2, N3. Chaque scenario indique les briques branchees sur le vrai code
et celles encore en simulation hors chaîne, à remplacer par #n. Seules des
grandeurs mesurees (comptages, pas des mesures de performance) sont affichees.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Permet aussi `python dashboard/demo.py` depuis n'importe ou.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dashboard.demo_data import DEMO_SEED  # noqa: E402
from dashboard.scenarios import (  # noqa: E402
    STATUS_LABELS,
    MeasuredMetric,
    ScenarioResult,
    get_spec,
    list_specs,
    run_scenario,
)
from dashboard.view_model import MISSING_LABEL, format_base_units  # noqa: E402

NOT_MEASURED_LABEL = "non mesuré"


def format_metric_value(metric: MeasuredMetric) -> str:
    """`9 000 base units`, `5.618 ×` ou `non mesuré`."""
    if metric.value is None:
        return NOT_MEASURED_LABEL
    if isinstance(metric.value, int):
        return f"{format_base_units(metric.value)} {metric.unit}"
    return f"{metric.value:.3f} {metric.unit}"


def _refs(numbers: tuple[int, ...]) -> str:
    return ", ".join(f"#{n}" for n in numbers) or MISSING_LABEL


def _print_list(disabled: frozenset[str]) -> None:
    for spec in list_specs():
        print(" | ".join([
            spec.id,
            spec.title,
            "optionnel" if spec.optional else MISSING_LABEL,
            "désactivé" if spec.id in disabled else "activé",
            f"dépend de {_refs(spec.depends_on)}",
            spec.implementation_label(),
        ]))


def format_result(result: ScenarioResult) -> str:
    """Rendu texte lisible d'un resultat."""
    spec = get_spec(result.scenario_id)
    lines = [
        f"Scénario {spec.id} : {spec.title}",
        f"Statut : {STATUS_LABELS[result.status]}",
        f"Message : {result.message}",
        f"Seed : {result.seed}",
        f"Attendu : {spec.expected}",
    ]
    if result.variants:
        lines.append(f"Bandeau : {spec.result_banner(result)}")
    for variant in result.variants:
        lines.append(f"== {variant.label} ({variant.name}) ==")
        lines += [f"  {m.label} : {format_metric_value(m)}" for m in variant.metrics]
        lines += [
            f"  [{'OK' if c.passed else 'KO'}] {c.label} (attendu : {c.expected})"
            for c in variant.checks
        ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dashboard.demo",
        description="Scénarios de démo #47 (vrai code amont + simulation hors chaîne).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    list_cmd = sub.add_parser("list", help="Liste les scénarios.")
    list_cmd.add_argument("--disable", nargs="+", action="extend", default=[], metavar="ID",
                          help="Scénarios à marquer désactivés (ex. C D).")
    run_cmd = sub.add_parser("run", help="Lance un scénario.")
    run_cmd.add_argument("scenario_id", metavar="id")
    run_cmd.add_argument("--seed", type=int, default=DEMO_SEED)
    run_cmd.add_argument("--json", action="store_true", help="Sortie JSON du résultat.")
    run_cmd.add_argument("--report", action="store_true",
                         help="Affiche aussi le rapport d'incident DORA (#15) s'il existe.")
    run_cmd.add_argument("--disable", nargs="+", action="extend", default=[], metavar="ID",
                         help="Scénarios désactivés (ex. C D).")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entree CLI ; renvoie le code de sortie (2 si id inconnu)."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    # Le rejeu de plusieurs jours de trafic fait loguer au surveillant #12 un WARNING par tranche
    # de chauffe (« historique insuffisant ») : utile en production, du bruit pour la demo.
    logging.getLogger("detection").setLevel(logging.ERROR)
    args = _parser().parse_args(argv)
    known = {spec.id for spec in list_specs()}
    unknown = sorted((set(args.disable) | {getattr(args, "scenario_id", None)}) - known - {None})
    if unknown:
        print(f"Scénario inconnu : {', '.join(unknown)} (connus : {', '.join(sorted(known))})",
              file=sys.stderr)
        return 2
    disabled = frozenset(args.disable)
    if args.command == "list":
        _print_list(disabled)
        return 0
    result = run_scenario(args.scenario_id, seed=args.seed, disabled=disabled)
    print(result.model_dump_json(indent=2) if args.json else format_result(result))
    if args.report and not args.json:
        reports = [v.incident_report for v in result.variants if v.incident_report]
        print("\n".join(["", *reports]) if reports
              else "\nAucun rapport d'incident : aucune alerte confirmée dans ce scénario.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
