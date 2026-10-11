"""Branchement monitor -> detection (issue #86) : `python -m detection`.

Alimente `RuleBasedMonitor` (`detection/detector.py`) et emet chaque `Alert`
en JSON (une ligne par alerte, sur la sortie standard ; les journaux vont sur
la sortie d'erreur). Aucune integration avec `response/` ici.

Deux modes :

- LIVE (defaut) : flux `ChainListener.stream_event_batches` du monitor sur
  Fuji (mints + transferts du token `MONITOR_TOKEN_ADDRESS`). Sans token ni RPC
  (aucun contrat deploye, `contracts/DEPLOYMENTS.md`), message et sortie
  propre (code 0).
- REPLAY (`--replay FICHIER.jsonl`) : rejoue un JSONL synthetique produit par
  `data/generate.py` (une ligne = un modele de `shared.models`). Seules les
  lignes `MintEvent` et `TransferEvent` sont consommees ; les autres
  (`MintRequest`, evenements Ghost, balise) sont comptees et ignorees.

Horloge : les tranches de transferts sont cloturees A L'HEURE, meme sans
transfert : en LIVE a chaque poll (`close_slot_if_due(now)`), en REPLAY a
l'horodatage de chaque evenement (mint compris), puis une derniere fois apres
le dernier evenement pour cloturer la tranche ouverte.

Offre en circulation (normalisation du volume, OPEN_ANSWERS §9) — choix
PROVISOIRES, a valider par l'equipe :

- LIVE : `totalSupply()` du token, relu a chaque poll (offre TOTALE, pas une
  offre « en circulation » qui exclurait tresorerie / reserves : aucune
  definition n'est actee).
- REPLAY : `--initial-supply` (defaut 0) + somme des `MintEvent` deja rejoues.
  Le generateur donne aux utilisateurs des soldes pre-existants SANS
  evenement : ils ne sont pas dans le fichier, d'ou le parametre. Tant que
  l'offre vaut 0, les tranches sont sautees (WARNING du detecteur).

Mints : `check_mint` est appele sur chaque `MintEvent`, avec le `MintContext`
fourni par `mint_context` (aucun par defaut : GAP, ni depot ni taux dans les
evenements, voir `detection/inputs.py`). Sans contexte, aucune regle de mint
n'est verifiee ; un WARNING le signale une fois.

Adresses connues : seuls les transferts rendent une adresse « connue » (le
detecteur ne voit pas les mints) : le destinataire d'un mint reste « neuf »
jusqu'a son premier transfert (definition PROVISOIRE, OPEN_QUESTIONS §2).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from detection.detector import RuleBasedMonitor
from detection.inputs import MintContext
from detection.params import (
    ENV_DETECTION_PROFILE,
    PROFILE_DEMO,
    TRANSFER_PROFILES,
    resolve_profile,
    transfer_params_for_profile,
)
from monitor.config import (
    ENV_RPC_URL,
    ENV_TOKEN_ADDRESS,
    MonitorConfig,
    load_monitor_config,
)
from monitor.listener import ChainListener
from monitor.protected import AdminObservation
from detection.provenance import (
    admin_event_from_observation,
    correlator_context_provider,
)
from shared.models import Alert, MintEvent, TransferEvent

logger = logging.getLogger(__name__)

# PROVISOIRE — a valider par l'equipe. Offre initiale du REPLAY, base units :
# 0 = l'offre ne compte que les mints presents dans le fichier (voir docstring).
DEFAULT_REPLAY_INITIAL_SUPPLY = 0

ObservedEvent = MintEvent | TransferEvent
MintContextProvider = Callable[[MintEvent], MintContext | None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DetectionPipeline:
    """Relie un flux d'evenements au surveillant et emet ses alertes.

    Args:
        monitor: surveillant a alimenter.
        emit: recoit chaque `Alert` produite (ex. ecriture JSON).
        mint_context: fournit le `MintContext` d'un mint (None = aucun : les
            regles de mint ne sont pas verifiees, GAP).
    """

    def __init__(
        self,
        monitor: RuleBasedMonitor,
        emit: Callable[[Alert], None],
        mint_context: MintContextProvider | None = None,
    ) -> None:
        self.monitor = monitor
        self._emit = emit
        self._mint_context = mint_context
        self._warned_no_mint_context = False
        self.alert_count = 0

    def _publish(self, alert: Alert | None) -> list[Alert]:
        if alert is None:
            return []
        self.alert_count += 1
        self._emit(alert)
        return [alert]

    def update_circulating_supply(self, supply: int) -> None:
        """Transmet l'offre (base units) au surveillant ; ignoree si <= 0
        (offre inconnue : les tranches seront sautees avec un WARNING)."""
        if supply <= 0:
            logger.debug("offre %d <= 0 ignoree (offre toujours inconnue)", supply)
            return
        self.monitor.update_circulating_supply(supply)

    def tick(self, now: datetime) -> list[Alert]:
        """Cloture la tranche de transferts ouverte si `now` a passe sa fin.

        Args:
            now: heure courante (UTC) ; en replay, horodatage d'evenement.

        Returns:
            L'alerte emise le cas echeant (liste vide sinon).
        """
        return self._publish(self.monitor.close_slot_if_due(now))

    def set_mint_context_provider(self, provider: MintContextProvider) -> None:
        """Branche un fournisseur de `MintContext` (ex. mode contrat protege #104)."""
        self._mint_context = provider

    def process_admin(self, observation: AdminObservation) -> list[Alert]:
        """Evalue un evenement d'administration DES sa lecture (#104).

        Args:
            observation: evenement decode par le monitor.

        Returns:
            L'alerte emise si l'evenement n'a pas ete annonce (liste vide sinon).
        """
        return self._publish(
            self.monitor.check_admin_event(
                admin_event_from_observation(observation), observation.detail
            )
        )

    def process(self, event: ObservedEvent) -> list[Alert]:
        """Traite un evenement : cloture d'abord la tranche echue a
        `event.observed_at`, puis `check_transfer` ou `check_mint`.

        Args:
            event: mint ou transfert observe.

        Returns:
            Les alertes emises (0, 1 ou 2), dans l'ordre d'emission.
        """
        alerts = self.tick(event.observed_at)
        if isinstance(event, TransferEvent):
            alerts += self._publish(self.monitor.check_transfer(event))
            return alerts
        context = self._mint_context(event) if self._mint_context else None
        if context is None and not self._warned_no_mint_context:
            logger.warning(
                "aucun MintContext : regles de mint (I1, I5, I6, admin, oracle) "
                "NON verifiees (GAP, voir detection/inputs.py)"
            )
            self._warned_no_mint_context = True
        alerts += self._publish(self.monitor.check_mint(event, context))
        return alerts


@dataclass(frozen=True)
class ReplaySummary:
    """Bilan d'un replay (journalise en fin de run).

    Attributes:
        mints: `MintEvent` rejoues.
        transfers: `TransferEvent` rejoues.
        ignored: lignes d'un autre modele (MintRequest, Ghost, balise...).
        alerts: alertes emises.
        final_supply: offre en fin de replay, base units.
    """

    mints: int
    transfers: int
    ignored: int
    alerts: int
    final_supply: int


def parse_replay_line(line: str) -> ObservedEvent | None:
    """Lit une ligne JSONL : `TransferEvent`, `MintEvent` ou None (autre modele).

    Les modeles partages etant stricts (`extra="forbid"`), une ligne ne valide
    qu'un seul d'entre eux.

    Raises:
        ValueError: si la ligne n'est pas un objet JSON.
    """
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide : {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("objet JSON attendu")
    model: type[TransferEvent] | type[MintEvent]
    for model in (TransferEvent, MintEvent):
        try:
            return model.model_validate(payload)
        except ValidationError:
            continue
    return None


def run_replay(
    lines: Iterable[str],
    pipeline: DetectionPipeline,
    initial_supply: int = DEFAULT_REPLAY_INITIAL_SUPPLY,
) -> ReplaySummary:
    """Rejoue un JSONL synthetique dans le pipeline, dans l'ordre du fichier.

    Args:
        lines: lignes du fichier (`data/generate.py`).
        pipeline: pipeline a alimenter.
        initial_supply: offre avant le premier evenement, base units
            (PROVISOIRE, voir docstring du module).

    Returns:
        Le bilan du replay.

    Raises:
        ValueError: si une ligne n'est pas un objet JSON, ou si
            `initial_supply` < 0.
    """
    if initial_supply < 0:
        raise ValueError("initial_supply doit etre >= 0")
    supply = initial_supply
    pipeline.update_circulating_supply(supply)
    mints = transfers = ignored = 0
    last_time: datetime | None = None
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = parse_replay_line(line)
        except ValueError as exc:
            raise ValueError(f"ligne {number} : {exc}") from exc
        if event is None:
            ignored += 1
            continue
        if isinstance(event, MintEvent):
            mints += 1
            # Cloturer AVANT de compter ce mint dans l'offre : la tranche echue
            # est evaluee avec l'offre de son epoque.
            pipeline.tick(event.observed_at)
            supply += event.amount
            pipeline.update_circulating_supply(supply)
        else:
            transfers += 1
        pipeline.process(event)
        last_time = event.observed_at
    if last_time is not None:
        slot = timedelta(seconds=pipeline.monitor.transfer_params.slot_seconds)
        pipeline.tick(last_time + slot)
    return ReplaySummary(
        mints=mints,
        transfers=transfers,
        ignored=ignored,
        alerts=pipeline.alert_count,
        final_supply=supply,
    )


def missing_live_settings(config: MonitorConfig) -> list[str]:
    """Variables d'environnement manquantes pour le mode LIVE."""
    return [
        name
        for name, value in (
            (ENV_RPC_URL, config.rpc_url),
            (ENV_TOKEN_ADDRESS, config.token_address),
        )
        if not value
    ]


def run_live(
    pipeline: DetectionPipeline,
    config: MonitorConfig,
    listener: ChainListener | None = None,
    *,
    max_polls: int | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> int:
    """Ecoute le token sur Fuji et alimente le pipeline a chaque poll.

    A chaque poll : relecture de `totalSupply()`, traitement des evenements
    nouveaux, puis cloture de la tranche echue a `now()` (meme sans transfert).

    Args:
        pipeline: pipeline a alimenter.
        config: reglages du monitor.
        listener: ecouteur (defaut : `ChainListener(config)`, faux en test).
        max_polls: nombre de polls avant arret (None = infini).
        now: horloge UTC (injectable en test).

    Returns:
        0 (sortie propre, y compris quand le token ou le RPC manque).
    """
    if listener is None:
        missing = missing_live_settings(config)
        if missing:
            logger.warning(
                "detection : %s non renseignee(s). Rien a ecouter (aucun contrat "
                "deploye, voir contracts/DEPLOYMENTS.md). Pour rejouer des donnees "
                "synthetiques : python -m detection --replay FICHIER.jsonl --profile %s",
                ", ".join(missing),
                PROFILE_DEMO,
            )
            return 0
        listener = ChainListener(config)
    correlator = getattr(listener, "correlator", None)
    if correlator is not None:
        # Mode contrat protege (#104) : chaque mint arrive avec sa demande.
        pipeline.set_mint_context_provider(correlator_context_provider(correlator))
        logger.info(
            "detection : mode contrat protege, minter %s", config.minter_address
        )
    logger.info("detection : ecoute du token %s ...", config.token_address)
    for batch in listener.stream_event_batches(max_polls=max_polls):
        pipeline.update_circulating_supply(listener.read_total_supply())
        for event in batch:
            if isinstance(event, AdminObservation):
                pipeline.process_admin(event)
            else:
                pipeline.process(event)
        pipeline.tick(now())
    return 0


def json_line_emitter(sink: TextIO) -> Callable[[Alert], None]:
    """Emetteur d'alertes : une ligne JSON par `Alert`, videe aussitot.

    JSON echappe en ASCII (`\\u00a7` pour « § ») : la ligne reste valide quel
    que soit l'encodage de la console (cp1252 sous Windows).
    """

    def emit(alert: Alert) -> None:
        sink.write(json.dumps(alert.model_dump(mode="json")) + "\n")
        sink.flush()

    return emit


def build_parser() -> argparse.ArgumentParser:
    """Parseur de la CLI `python -m detection`."""
    parser = argparse.ArgumentParser(
        prog="python -m detection",
        description=(
            "Alimente les surveillants a regles (mints + transferts) et emet les "
            "Alert en JSON lines. Defaut : ecoute LIVE (monitor, Fuji)."
        ),
    )
    parser.add_argument(
        "--replay",
        type=Path,
        metavar="FICHIER.jsonl",
        help="rejoue un JSONL synthetique de data/generate.py au lieu d'ecouter Fuji",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(TRANSFER_PROFILES),
        default=None,
        help=(
            f"profil de chauffe de la baseline (defaut : ${ENV_DETECTION_PROFILE} "
            f"sinon default). '{PROFILE_DEMO}' = DEMO, ne pas utiliser en production"
        ),
    )
    parser.add_argument(
        "--exit-point",
        action="append",
        default=[],
        metavar="ADRESSE",
        help="adresse etiquetee exchange / bridge (repetable ; PROVISOIRE)",
    )
    parser.add_argument(
        "--initial-supply",
        type=int,
        default=DEFAULT_REPLAY_INITIAL_SUPPLY,
        metavar="BASE_UNITS",
        help="REPLAY : offre avant le premier evenement, base units (PROVISOIRE, defaut 0)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="niveau des journaux (sortie d'erreur)",
    )
    return parser


def build_pipeline(
    profile: str,
    exit_points: Sequence[str],
    emit: Callable[[Alert], None],
) -> DetectionPipeline:
    """Pipeline avec un `RuleBasedMonitor` regle selon `profile`."""
    monitor = RuleBasedMonitor(
        transfer_params=transfer_params_for_profile(profile, exit_points)
    )
    return DetectionPipeline(monitor, emit)


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    """Point d'entree executable.

    Args:
        argv: arguments (defaut : `sys.argv[1:]`).
        out: flux des alertes JSON (defaut : sortie standard).

    Returns:
        Code de sortie (0 = succes).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        profile = resolve_profile(args.profile)
        pipeline = build_pipeline(
            profile, args.exit_point, json_line_emitter(out or sys.stdout)
        )
    except ValueError as exc:
        parser.error(str(exc))
    if profile == PROFILE_DEMO:
        logger.warning(
            "profil DEMO actif - ne pas utiliser en production, PROVISOIRE "
            "(chauffe courte de la baseline, detection/params.py)"
        )
    if args.replay is None:
        return run_live(pipeline, load_monitor_config())
    started = time.monotonic()
    with args.replay.open(encoding="utf-8") as source:
        summary = run_replay(source, pipeline, args.initial_supply)
    logger.info(
        "replay %s (profil %s) : %d mints, %d transferts, %d lignes ignorees, "
        "%d alertes, offre finale %d base units (%.1f s)",
        args.replay,
        profile,
        summary.mints,
        summary.transfers,
        summary.ignored,
        summary.alerts,
        summary.final_supply,
        time.monotonic() - started,
    )
    return 0
