"""Adaptateurs minces vers les vraies implementations amont (#70) : #24 -> #11/#12 -> #17.

Utilises par B, N1, N2, N3 (`catalog.py`). Rien n'est reimplemente ici :

- trafic : `data.generate` (#24). Parametres du generateur laisses a leurs valeurs par
  defaut, sauf seed, duree (`real_traffic_days`), population (`legit_address_count`),
  tranche (`bucket_minutes`) et part du solde envoyee (`real_transfer_fraction_*`, defaut
  = celui du generateur) ;
- surveillants : `detection.detector.RuleBasedMonitor` (#11 `check_mint`, #12
  `check_transfer`) avec les parametres de `detection/params.py`. Seuls la longueur de
  tranche (`bucket_minutes`) et les points de sortie (manifeste #24) sont passes, comme
  `data.calibrate` ;
- reponse : `response.orchestrator.ResponseOrchestrator` (#17), horloge simulee et
  identifiants deterministes injectes (API prevue par l'orchestrateur).

Determinisme : les surveillants horodatent leurs alertes a l'heure murale avec un uuid4.
L'adaptateur les re-horodate a l'instant SIMULE ou elles sont emises (cloture de la
tranche, ou mint observe) et leur donne un identifiant tire de la seed. Aucun autre champ
n'est modifie.

Ce qui reste SIMULE : le Ghost (#8, non livre) via `GhostLedger` et les effets
`ghost_on_*` de `sim_response` (quarantaine, balise, conversion, destruction), et l'audit
humain (qui confirme une destruction) : c'est la verite terrain du jeu genere.
Les grandeurs produites sont des comptages sur trafic synthetique, pas des mesures de
performance (docs/CLAIMS.md).
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any

from dashboard.demo_data import DEMO_EXTENDED_WINDOW, DEMO_NORMAL_WINDOW, _Builder, _fake_address, _fake_id
from dashboard.scenarios.config import SimulationParams
from dashboard.scenarios.sim_contracts import GhostLedger
from dashboard.scenarios.sim_response import ghost_on_burn, ghost_on_delay, ghost_on_expire
from data.generate import Event, GenerationParams, event_time
from detection.detector import RuleBasedMonitor
from detection.inputs import MintContext
from detection.params import TransferRuleParams
from detection.transfers import TransferSlotStats
from response.orchestrator import DEFAULT_PERIMETER_QUORUM, ResponseOrchestrator, ResponsePolicy
from shared.models import (
    Alert,
    MintEvent,
    MintRequest,
    ReleaseDecision,
    ReleaseVerdict,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    TransferEvent,
)

TRAFFIC_REFS: tuple[int, ...] = (24,)
DETECTION_REFS: tuple[int, ...] = (11, 12, 24)
RESPONSE_REFS: tuple[int, ...] = (17,)
GUARDIAN_COUNT = 3
# Taux du generateur #24 : mint 1:1 du depot (meme token fictif a 6 decimales), cf. data.calibrate.
GENERATOR_RATE = Fraction(1)


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def generation_params(seed: int, params: SimulationParams, **overrides: Any) -> GenerationParams:
    """Parametres du generateur #24 ; l'attaque (B) tombe a 18 h le dernier jour, comme
    `data.calibrate` (historique suffisant pour la baseline du meme creneau)."""
    days = params.real_traffic_days
    values: dict[str, Any] = {
        "seed": seed,
        "hours": 24.0 * days,
        "users": params.legit_address_count,
        "slot_minutes": params.bucket_minutes,
        "ghost_window_minutes": _minutes(DEMO_NORMAL_WINDOW),
        "transfer_fraction": (params.real_transfer_fraction_min,
                              params.real_transfer_fraction_max),
        "attack_at_fraction": (days - 1 + 0.75) / days,
    }
    values.update(overrides)
    return GenerationParams(**values)


# --- Surveillants #11 / #12 -----------------------------------------------------


@dataclass
class DetectionRun:
    """Alertes (re-horodatees) et mesures des tranches cloturees."""

    alerts: list[Alert] = field(default_factory=list)
    slots: list[TransferSlotStats] = field(default_factory=list)


def _record(builder: _Builder, alert: Alert, at: datetime) -> Alert:
    stamped = alert.model_copy(update={"alert_id": _fake_id(builder.rng, "alert"),
                                       "created_at": at})
    return builder.add_alert(stamped)


def run_detectors(builder: _Builder, events: Sequence[Event], manifest: dict[str, Any],
                  params: SimulationParams) -> DetectionRun:
    """Rejoue `events` (ordre chronologique) dans le vrai `RuleBasedMonitor`.

    Mints : I1 au taux du generateur (`MintContext(depot, taux=1)`), depot retrouve par
    `request_id` dans le jeu genere (identifiants uniques du generateur). Transferts :
    offre en circulation = offre initiale du manifeste + mints observes.
    """
    tparams = TransferRuleParams(slot_seconds=params.bucket_minutes * 60,
                                 exit_points=frozenset(manifest["exit_points"]))
    supply = int(manifest["initial_supply"])
    monitor = RuleBasedMonitor(transfer_params=tparams, circulating_supply=supply,
                               known_addresses=manifest["known_addresses"])
    run = DetectionRun()
    deposits: dict[int, int] = {}
    last: TransferSlotStats | None = None

    def slot_closed(alert: Alert | None) -> None:
        nonlocal last
        stats = monitor.last_slot_stats
        if stats is None or stats is last:
            return
        last = stats
        run.slots.append(stats)
        if alert is not None:
            run.alerts.append(_record(builder, alert, stats.slot_end))

    for event in events:
        if isinstance(event, MintRequest):
            deposits[event.request_id] = event.deposit_amount
        elif isinstance(event, MintEvent):
            supply += event.amount
            monitor.update_circulating_supply(supply)
            deposit = deposits.get(event.request_id)
            context = (MintContext(deposit_amount=deposit, rate=GENERATOR_RATE)
                       if deposit is not None else None)
            alert = monitor.check_mint(event, context)
            if alert is not None:
                run.alerts.append(_record(builder, alert, event.observed_at))
        elif isinstance(event, TransferEvent):
            slot_closed(monitor.check_transfer(event))
    if events:
        end = event_time(events[-1]) + timedelta(seconds=tparams.slot_seconds)
        slot_closed(monitor.close_slot_if_due(end))
    run.alerts.sort(key=lambda a: a.created_at)
    return run


def alert_addresses(alert: Alert) -> set[str]:
    """Sujet et graines d'une alerte (minuscules)."""
    return {alert.subject_address.lower(), *(seed.address.lower() for seed in alert.seeds)}


def daily_volumes(slots: Iterable[TransferSlotStats], start: datetime) -> list[int]:
    """Volume transfere par jour simule (tranches cloturees par le surveillant #12)."""
    per_day: dict[int, int] = {}
    for stats in slots:
        day = int((stats.slot_start - start) / timedelta(days=1))
        per_day[day] = per_day.get(day, 0) + stats.volume
    return [per_day.get(day, 0) for day in range(max(per_day) + 1)] if per_day else []


# --- Reponse #17 ------------------------------------------------------------------


GhostMove = tuple[datetime, Callable[[datetime], None]]


@dataclass
class RealResponse:
    """Trace de la reponse rejouee dans le vrai orchestrateur."""

    orchestrator: ResponseOrchestrator
    destroyed_at: dict[str, datetime] = field(default_factory=dict)
    redeemed: dict[str, int] = field(default_factory=dict)
    end_time: datetime | None = None

    @property
    def actions(self) -> list[ResponseAction]:
        """Etat final des actions de l'orchestrateur."""
        return list(self.orchestrator.actions)


def respond(builder: _Builder, ledger: GhostLedger, alerts: Sequence[Alert],
            confirmed: set[str], params: SimulationParams, traffic_end: datetime,
            ghost_moves: Sequence[GhostMove] = ()) -> RealResponse:
    """Rejoue alertes et mouvements Ghost dans l'ordre du temps simule.

    - alerte -> `handle_alert` (retard du sujet et des graines, decidable seul) ;
    - perimetre retarde ET dans `confirmed` (audit humain simule = verite terrain du jeu)
      -> `apply_release(confirm_destroy)` multisig 2/3 apres
      `human_confirmation_delay_minutes`, fraction detruite = ratio du Ghost non converti ;
    - sinon le retard expire seul (`expire_due`) et le Ghost est converti 1:1.

    Le Ghost (#8) reste simule (`ledger`, effets `ghost_on_*`). En fin de rejeu, les
    actions et le journal d'audit de l'orchestrateur sont recopies dans `builder`.
    """
    clock = {"now": traffic_end}
    guardians = [_fake_address(builder.rng) for _ in range(GUARDIAN_COUNT)]
    window = _minutes(DEMO_EXTENDED_WINDOW)
    orchestrator = ResponseOrchestrator(
        ResponsePolicy(guardians=frozenset(guardians), delay_minutes=window,
                       max_monitor_delay_minutes=window),
        clock=lambda: clock["now"],
        id_factory=lambda prefix: _fake_id(builder.rng, prefix),
    )
    response = RealResponse(orchestrator)
    human_delay = timedelta(minutes=params.human_confirmation_delay_minutes)
    confirmed_keys = {address.lower() for address in confirmed}
    seq = itertools.count()
    queue: list[tuple[datetime, int, str, Any]] = []
    for at, move in ghost_moves:
        heapq.heappush(queue, (at, next(seq), "move", move))
    for alert in alerts:
        heapq.heappush(queue, (alert.created_at, next(seq), "alert", alert))
    times: list[datetime] = []

    def tick(at: datetime) -> None:
        """Avance l'horloge : expirations (retour a la normale) puis conversions Ghost."""
        clock["now"] = at
        expired = [a for a in orchestrator.expire_due()
                   if a.action_type == ResponseActionType.DELAY and a.perimeter_address]
        before = dict(ledger.converted)
        ratios = {a.action_id: ledger.ratio(a.perimeter_address or "", at) for a in expired}
        ledger.convert_after_window(at)
        for action in expired:
            address = action.perimeter_address or ""
            amount = ledger.converted.get(address, 0) - before.get(address, 0)
            ghost_on_expire(builder, address, at, action.created_at, amount,
                            ratios[action.action_id])
            response.redeemed[address] = response.redeemed.get(address, 0) + amount

    while queue:
        at, _, kind, payload = heapq.heappop(queue)
        times.append(at)
        tick(at)
        if kind == "move":
            payload(at)
        elif kind == "alert":
            # Retards nouveaux ou prolonges par cette alerte (l'orchestrateur prolonge
            # l'action existante d'un perimetre deja retarde).
            known = {a.action_id: a.expires_at for a in orchestrator.actions}
            orchestrator.handle_alert(payload)
            for action in orchestrator.actions:
                changed = (action.action_id not in known
                           or known[action.action_id] != action.expires_at)
                if (action.action_type != ResponseActionType.DELAY or not changed
                        or action.status != ResponseActionStatus.APPLIED
                        or action.expires_at is None or action.perimeter_address is None):
                    continue
                address = action.perimeter_address
                ledger.hold(address, action.expires_at)
                ghost_on_delay(builder, address, at, action.expires_at,
                               ledger.balance(address, at), action.contamination_ratio or 0.0,
                               action.suspect_amount or 0)
                heapq.heappush(queue, (action.expires_at, next(seq), "expire", None))
                if address.lower() in confirmed_keys:
                    heapq.heappush(queue, (at + human_delay, next(seq), "destroy", address))
        elif kind == "destroy":
            _destroy(builder, ledger, orchestrator, response, guardians, payload, at)
        # "expire" : deja traite par tick().
    bucket = timedelta(minutes=params.bucket_minutes)
    response.end_time = max([traffic_end, *(t + bucket for t in times)])
    tick(response.end_time)
    builder.actions = response.actions
    builder.audit.extend(orchestrator.audit_log)
    return response


def _destroy(builder: _Builder, ledger: GhostLedger, orchestrator: ResponseOrchestrator,
             response: RealResponse, guardians: list[str], address: str, at: datetime) -> None:
    if address in response.destroyed_at:
        return
    balance = ledger.balance(address, at)
    ratio = ledger.ratio(address, at)
    if int(ratio * balance) <= 0:
        return  # rien a detruire : le retard expirera seul
    decision = ReleaseDecision(
        decision_id=_fake_id(builder.rng, "decision"), verdict=ReleaseVerdict.CONFIRM_DESTROY,
        decided_at=at, perimeter_address=address,
        signers=guardians[:DEFAULT_PERIMETER_QUORUM], threshold=DEFAULT_PERIMETER_QUORUM,
        burn_ratio=ratio,
        rationale="Audit humain simulé (vérité terrain du jeu #24) : drainage confirmé, "
                  "destruction de la fraction suspecte.",
    )
    builder.decisions.append(decision)
    action = orchestrator.apply_release(decision)
    if action.action_type != ResponseActionType.DESTROY or \
            action.status != ResponseActionStatus.APPLIED:
        return
    ledger.burn(address, ratio, at)
    ghost_on_burn(builder, address, at, balance, ratio, decision.decision_id)
    response.destroyed_at[address] = at
