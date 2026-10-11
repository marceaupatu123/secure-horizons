"""Etude chiffree de #85 : contamination posee APRES COUP (donnees FICTIVES).

Question (issue #85, decision §10bis) : le ratio de contamination (§9) se transmet **au moment**
de chaque transfert. Si le voleur n'est marque suspect qu'**apres** avoir fait circuler son M',
son ratio valait 0 pendant les ventes et le soupcon n'a pas suivi la chaine. Que recupere-t-on
alors chez le N-ieme detenteur ?

Ce module **mesure** la fraude recuperee pour les trois pistes de #85, sur l'exemple de reference
« chaine des 40 » de §10bis (un voleur revend du M' pur de main en main). Il ne tranche pas : le
choix entre les pistes est une decision d'equipe (#85 bloque #84 et touche #8). Les chiffres sont
des mesures sur simulation.

Pistes comparees (#85) :

- **(c) prospectif seul** : contamination par ratio telle quelle (§9). On ne marque le voleur
  qu'a l'alerte ; ce qu'il a deja transfere portait un ratio 0, donc rien ne suit la chaine. On
  ne recupere que ce qu'il detient encore + ses Ghost de paiement. C'est le modele du registre
  `data.ghost_ledger` et des scenarios C/D.
- **(a) lignage d'origine par tranche** : chaque tranche Ghost garde l'identifiant de son entree
  dans le Ghost (ici : le mint frauduleux). Une alerte vise une **origine**, pas une adresse :
  toute tranche encore non convertie issue de cette origine est atteinte, ou qu'elle soit dans la
  chaine.
- **(b) recalcul retroactif hors chaine** : le surveillant rejoue les evenements et recalcule les
  ratios **comme si** le voleur avait ete marque au mint. Resultat identique a (a) sur le solde
  encore en Ghost (meme couverture), mais sans etiquette on-chain : la difference (a) vs (b) est
  operationnelle (stockage par tranche vs preuve hors chaine), pas quantitative sur la couverture.
  On la mesure quand meme pour l'exposer.

Dans les trois cas, le vrai M deja converti avant la destruction est **hors d'atteinte** (§9 :
irreversible et voulu). C'est le levier mesure : plus la detection tarde, plus de M' pur est
converti et echappe a (a)/(b) comme a (c).

Lancement : `python -m data.late_marking` (ou via `data.calibrate` qui l'inclut).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from data.generate import DEFAULT_START, UNIT

ORIGIN_FRAUD = "fraude"
"""Identifiant d'origine du Ghost issu du mint frauduleux (piste a)."""


@dataclass(frozen=True)
class ChainParams:
    """Parametres de l'exemple « chaine des 40 » (a calibrer, pas des mesures).

    Attributes:
        start: debut de la simulation (UTC).
        window_minutes: fenetre Ghost normale W (§0bis).
        slot_minutes: largeur d'une tranche d'echeance (§0bis-b).
        hops: longueur de la chaine de reventes (40 dans l'exemple de §10bis).
        stolen_tokens: M' frauduleux mis en circulation par le voleur.
        hop_interval_seconds: delai entre deux reventes successives.
        detect_after_minutes: delai entre le mint frauduleux (t0) et l'alerte.
    """

    start: datetime = DEFAULT_START
    window_minutes: int = 10
    slot_minutes: int = 1
    hops: int = 40
    stolen_tokens: int = 10
    hop_interval_seconds: float = 20.0
    detect_after_minutes: float = 3.0

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError("start doit etre un datetime UTC timezone-aware.")
        for name in ("window_minutes", "slot_minutes", "hops", "stolen_tokens"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} doit etre >= 1.")
        if self.hop_interval_seconds <= 0 or self.detect_after_minutes <= 0:
            raise ValueError("les delais doivent etre > 0.")

    @property
    def amount(self) -> int:
        """Montant frauduleux en base units."""
        return self.stolen_tokens * UNIT


@dataclass
class _Holder:
    """Un maillon de la chaine : ce qu'il detient encore et quand il convertit."""

    index: int
    held: int = 0  # M' pur encore detenu (base units)
    received_at: datetime | None = None  # entree de la valeur dans le Ghost (echeance = +W)
    converted_at: datetime | None = None  # None tant que non converti


@dataclass
class ChainOutcome:
    """Resultat d'une piste sur la chaine.

    Attributes:
        strategy: identifiant de la piste (a / b / c).
        recovered: M' frauduleux atteint par la destruction (base units).
        escaped_converted: M' deja converti en vrai M avant la destruction (hors d'atteinte).
        escaped_prospective_gap: M' encore en Ghost mais rate faute de lignage (piste c).
        thief_kept: ce que le voleur conserve (ici 0 : il n'a que du Ghost, cf. §10bis).
    """

    strategy: str
    recovered: int
    escaped_converted: int
    escaped_prospective_gap: int
    thief_kept: int

    @property
    def total(self) -> int:
        return self.recovered + self.escaped_converted + self.escaped_prospective_gap


def _maturity(p: ChainParams, received_at: datetime) -> datetime:
    """Echeance d'une valeur entree dans le Ghost a `received_at` (arrondie au creneau, §0bis-b)."""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    slot = timedelta(minutes=p.slot_minutes)
    window = timedelta(minutes=p.window_minutes)
    slots = math.ceil((received_at + window - epoch) / slot)
    return epoch + slots * slot


def simulate_chain(p: ChainParams | None = None) -> dict[str, Any]:
    """Rejoue la chaine des N et chiffre les trois pistes de #85.

    Modele : le voleur (maillon 0) recoit `amount` de M' au mint (`t0`), puis le revend
    entierement au maillon 1 ; chaque maillon revend tout au suivant, un cran plus tard. Le M'
    garde son echeance d'origine (§10bis : revendre avant echeance donne du M' pur, meme
    echeance). A son echeance, un maillon convertit en vrai M **s'il n'est pas encore marque**.
    L'alerte tombe a `t0 + detect_after` et marque l'origine `fraude`.

    Returns:
        Un dict serialisable : parametres, instant de chaque evenement, et un `ChainOutcome` par
        piste.
    """
    p = p or ChainParams()
    t0 = p.start
    maturity = _maturity(p, t0)  # meme echeance pour toute la chaine (§10bis)
    alert_at = t0 + timedelta(minutes=p.detect_after_minutes)

    # Instant ou chaque maillon detient le M' (il le recoit du precedent).
    holders = [
        _Holder(index=i, received_at=t0 + timedelta(seconds=i * p.hop_interval_seconds))
        for i in range(p.hops + 1)
    ]

    # Le M' circule : a l'instant `alert_at`, il est chez le dernier maillon dont la reception
    # precede l'alerte et qui n'a pas encore convertit. Avant l'echeance, personne ne convertit
    # (fenetre non ecoulee) ; a l'echeance, le detenteur courant convertit si non marque.
    received_before_alert = [h for h in holders if h.received_at <= alert_at]
    current_holder = received_before_alert[-1]
    # La valeur peut avoir continue a circuler apres l'alerte jusqu'a l'echeance.
    final_holder = max(
        (h for h in holders if h.received_at <= maturity),
        key=lambda h: h.index,
    )

    # Conversion : seulement a l'echeance, et seulement si le detenteur courant n'est pas marque.
    # (c) marque uniquement le voleur -> ratio 0 chez les suivants -> le detenteur a l'echeance
    #     convertit librement : toute la valeur echappe (sauf si le voleur la detient encore).
    # (a)/(b) marquent l'origine -> la tranche reste suspecte partout -> conversion bloquee
    #     tant que l'echeance n'est pas passee ET l'alerte pas encore tombee.
    converted_at_maturity = maturity if final_holder.received_at <= maturity else None

    amount = p.amount

    # --- (c) prospectif seul : seul le voleur est marque -------------------------------------
    # Le voleur ne detient plus rien (il a tout revendu). Donc rien n'est atteint, et la valeur
    # est convertie a l'echeance par le detenteur final.
    prospective = ChainOutcome(
        strategy="c_prospectif",
        recovered=0,
        escaped_converted=amount,
        escaped_prospective_gap=0,
        thief_kept=0,
    )

    # --- (a) lignage d'origine par tranche ----------------------------------------------------
    # L'alerte vise l'origine `fraude`. Toute tranche issue de cette origine est suspecte, ou
    # qu'elle soit. Si l'alerte tombe AVANT l'echeance, la conversion est bloquee et tout est
    # recupere. Si l'alerte tombe APRES l'echeance, la valeur a deja ete convertie : hors
    # d'atteinte.
    alert_before_maturity = alert_at <= maturity
    lineage = ChainOutcome(
        strategy="a_lignage_origine",
        recovered=amount if alert_before_maturity else 0,
        escaped_converted=0 if alert_before_maturity else amount,
        escaped_prospective_gap=0,
        thief_kept=0,
    )

    # --- (b) recalcul retroactif hors chaine --------------------------------------------------
    # Meme couverture que (a) sur le solde encore en Ghost : la difference est operationnelle
    # (preuve hors chaine vs etiquette on-chain), pas sur le montant recupere.
    retroactive = ChainOutcome(
        strategy="b_retroactif",
        recovered=lineage.recovered,
        escaped_converted=lineage.escaped_converted,
        escaped_prospective_gap=0,
        thief_kept=0,
    )

    return {
        "fictive_data": True,
        "question": "#85 contamination posee apres coup",
        "params": {
            "window_minutes": p.window_minutes,
            "slot_minutes": p.slot_minutes,
            "hops": p.hops,
            "stolen_base_units": amount,
            "hop_interval_seconds": p.hop_interval_seconds,
            "detect_after_minutes": p.detect_after_minutes,
        },
        "timeline": {
            "t0": t0.isoformat(),
            "alert_at": alert_at.isoformat(),
            "maturity": maturity.isoformat(),
            "alert_before_maturity": alert_before_maturity,
            "holder_at_alert_index": current_holder.index,
            "final_holder_index": final_holder.index,
            "converted_at_maturity": converted_at_maturity.isoformat()
            if converted_at_maturity
            else None,
        },
        "strategies": {o.strategy: _outcome_json(o, amount) for o in (prospective, lineage, retroactive)},
        "note": "mesure sur simulation ; le choix de la piste reste une decision d'equipe (#85)",
    }


def _outcome_json(o: ChainOutcome, amount: int) -> dict[str, Any]:
    return {
        "recovered": o.recovered,
        "escaped_converted": o.escaped_converted,
        "escaped_prospective_gap": o.escaped_prospective_gap,
        "recovered_fraction": o.recovered / amount if amount else 0.0,
    }


def detection_speed_sweep(
    p: ChainParams | None = None,
    delays_minutes: tuple[float, ...] = (1.0, 3.0, 5.0, 8.0, 10.0, 12.0),
) -> list[dict[str, Any]]:
    """Fraction recuperee par piste selon le delai de detection (lignage utile si alerte < echeance).

    Montre le vrai levier : avec lignage (a/b), tout est recupere tant que l'alerte precede
    l'echeance (W = 10 min), rien au-dela ; (c) ne recupere jamais rien sur une chaine deja
    propagee.
    """
    base = p or ChainParams()
    rows = []
    for delay in delays_minutes:
        result = simulate_chain(replace(base, detect_after_minutes=delay))
        rows.append(
            {
                "detect_after_minutes": delay,
                "alert_before_maturity": result["timeline"]["alert_before_maturity"],
                "a_recovered_fraction": result["strategies"]["a_lignage_origine"]["recovered_fraction"],
                "c_recovered_fraction": result["strategies"]["c_prospectif"]["recovered_fraction"],
            }
        )
    return rows


def run(p: ChainParams | None = None) -> dict[str, Any]:
    """Etude complete : cas de reference + balayage du delai de detection."""
    p = p or ChainParams()
    return {
        "reference_case": simulate_chain(p),
        "detection_speed_sweep": detection_speed_sweep(p),
    }


def to_markdown(results: dict[str, Any]) -> str:
    """Tableaux lisibles pour #85."""
    ref = results["reference_case"]
    amount = ref["params"]["stolen_base_units"]
    lines = [
        "#85 — contamination posee apres coup (chaine des "
        f"{ref['params']['hops']}, W = {ref['params']['window_minutes']} min, "
        f"detection a {ref['params']['detect_after_minutes']} min)",
        "",
        "| Piste | M' recupere | converti (hors d'atteinte) | % recupere |",
        "|---|---|---|---|",
    ]
    labels = {
        "a_lignage_origine": "(a) lignage d'origine",
        "b_retroactif": "(b) recalcul retroactif",
        "c_prospectif": "(c) prospectif seul",
    }
    for key, label in labels.items():
        s = ref["strategies"][key]
        lines.append(
            f"| {label} | {s['recovered'] / amount:.0%} du vol | "
            f"{s['escaped_converted'] / amount:.0%} | {s['recovered_fraction']:.0%} |"
        )
    lines += [
        "",
        "Fraction recuperee selon le delai de detection (lignage a/b vs prospectif c) :",
        "",
        "| detection (min) | alerte avant echeance ? | (a)/(b) recupere | (c) recupere |",
        "|---|---|---|---|",
    ]
    for row in results["detection_speed_sweep"]:
        lines.append(
            f"| {row['detect_after_minutes']:g} | "
            f"{'oui' if row['alert_before_maturity'] else 'non'} | "
            f"{row['a_recovered_fraction']:.0%} | {row['c_recovered_fraction']:.0%} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    """Point d'entree : `python -m data.late_marking`."""
    parser = argparse.ArgumentParser(description="Mesure #85 (contamination apres coup, FICTIF).")
    parser.add_argument("--hops", type=int, default=ChainParams.hops)
    parser.add_argument("--window", type=int, default=ChainParams.window_minutes)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    results = run(ChainParams(hops=args.hops, window_minutes=args.window))
    report = to_markdown(results)
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "late_marking.json").write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )
        (args.out_dir / "late_marking.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
