"""Catalogue des 7 scenarios de demo (#47), branches sur le vrai code amont (#70).

Chaque runner est deterministe pour une seed donnee (`random.Random(seed)` local,
horloge simulee) et ne renvoie que des grandeurs MESUREES sur l'etat final du rejeu
(comptages, pas des mesures de performance, cf. docs/CLAIMS.md).

- B, N1, N2, N3 : trafic #24, surveillants #11/#12 et reponse #17 reels
  (`real_pipeline.py`) ; le Ghost (#8, non livre) reste simule pour B et N3.
- A : contrats Foundry #4/#5 reels sur anvil si `SH_DEMO_CONTRACTS_BACKEND=anvil`
  (`real_contracts.py`), repli automatique sur la simulation sinon.
- C, D : simulation hors chaîne, à remplacer par #7 / #8 / #25 (non livres).

`replace_by` porte les briques encore simulees ; `implemented_by` / `opt_in_by`
celles branchees sur le vrai code.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial

from dashboard.demo_data import (
    DEMO_CHAIN_ID,
    DEMO_EXTENDED_WINDOW,
    DEMO_NORMAL_WINDOW,
    DEMO_REFERENCE_TIME,
    _Builder,
    _fake_address,
)
from dashboard.scenarios import real_contracts
from dashboard.scenarios.config import SimulationParams
from dashboard.scenarios.models import (
    SIMULATION_LABEL,
    MeasuredMetric,
    ScenarioCheck,
    ScenarioResult,
    ScenarioSpec,
    ScenarioStatus,
    ScenarioVariant,
    real_source,
)
from dashboard.scenarios.real_pipeline import (
    DETECTION_REFS,
    GENERATOR_RATE,
    RESPONSE_REFS,
    TRAFFIC_REFS,
    alert_addresses,
    daily_volumes,
    delayed_supply_share,
    generation_params,
    respond,
    run_detectors,
)
from dashboard.scenarios.real_report import (
    incident_report_markdown,
    related_actions,
    related_audit,
)
from dashboard.scenarios.registry import register
from dashboard.scenarios.sim_contracts import (
    ConstantProductPool,
    GhostLedger,
    LendingMarket,
    ProtectedMinter,
    VulnerableMinter,
)
from dashboard.scenarios.sim_detector import detect
from dashboard.scenarios.sim_response import (
    apply_delay,
    build_dataset,
    confirm_destroy,
    expire_delay,
)
from dashboard.scenarios.sim_traffic import (
    attacker_transfers,
    consolidation_burst,
    legit_addresses,
    legit_traffic,
)
from dashboard.view_model import PerimeterState, derive_perimeter_states
from data.generate import event_time, generate_normal, generate_scenario_b
from shared.models import (
    Alert,
    MintEvent,
    MintRequest,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    TransferEvent,
)

# Verite terrain de la simulation : les mints de l'attaquant sont integralement frauduleux.
ATTACK_SUSPECT_RATIO = 1.0
LEGIT_RATIO = 0.0

_REAL_PIPELINE = (11, 12, 17, 24)
DEPENDS_ON: dict[str, tuple[int, ...]] = {
    "A": (4, 5), "B": _REAL_PIPELINE, "C": (7, 25), "D": (8, 25),
    "N1": _REAL_PIPELINE, "N2": _REAL_PIPELINE, "N3": _REAL_PIPELINE,
}
# Briques encore simulees (bandeau « simulation hors chaîne, à remplacer par #… »).
REPLACE_BY: dict[str, tuple[int, ...]] = {
    "A": (4, 5), "B": (8,), "C": (7, 25), "D": (8, 25),
    "N1": (), "N2": (), "N3": (8,),
}
# Briques toujours branchees sur le vrai code.
IMPLEMENTED_BY: dict[str, tuple[int, ...]] = {
    "B": _REAL_PIPELINE, "N1": _REAL_PIPELINE, "N2": _REAL_PIPELINE, "N3": _REAL_PIPELINE,
}
# Briques branchees sur le vrai code seulement via un backend optionnel (repli simulation).
OPT_IN_BY: dict[str, tuple[int, ...]] = {"A": (4, 5)}
_MAIN = "main"
_DETECTION_SOURCE = real_source(DETECTION_REFS)
_RESPONSE_SOURCE = real_source(RESPONSE_REFS)
_TRAFFIC_SOURCE = real_source(TRAFFIC_REFS)


# --- Helpers communs ---------------------------------------------------------


def _metric(key: str, label: str, value: int | float | None, unit: str,
            source: str = SIMULATION_LABEL) -> MeasuredMetric:
    return MeasuredMetric(key=key, label=label, value=value, unit=unit, source=source)


def _result(scenario_id: str, seed: int, variants: list[ScenarioVariant],
            replace_by: tuple[int, ...] | None = None,
            message: str | None = None) -> ScenarioResult:
    remaining = REPLACE_BY[scenario_id] if replace_by is None else replace_by
    return ScenarioResult(
        scenario_id=scenario_id,
        seed=seed,
        status=ScenarioStatus.COMPLETED,
        message=message or f"Rejoué avec la seed {seed} : grandeurs mesurées sur l'état final "
                           f"({SIMULATION_LABEL}).",
        simulated=bool(remaining),
        replace_by=list(remaining),
        variants=variants,
    )


def _bucket(params: SimulationParams) -> timedelta:
    return timedelta(minutes=params.bucket_minutes)


def _delayed_share_metric(events: list, actions: list[ResponseAction], initial_supply: int,
                          label: str) -> MeasuredMetric:
    """Pic de la part de l'offre en fenetre allongee, en % (friction locale, #70)."""
    share = delayed_supply_share(events, actions, initial_supply)
    return _metric("delayed_supply_share", label, None if share is None else 100 * share,
                   "% de l'offre", _RESPONSE_SOURCE)


def _log_traffic(builder: _Builder, at: datetime, legit: int, attack: int = 0) -> None:
    builder.log(at, "simulation", "simulation_started",
                f"Trafic simulé ({SIMULATION_LABEL}) : {legit} transferts légitimes, "
                f"{attack} mints attaquant.",
                {"legit_transfers": legit, "attack_transfers": attack})


@dataclass
class _Response:
    """Trace de la reponse simulee (delay / destroy / expiration)."""

    delays: list[ResponseAction] = field(default_factory=list)
    destroyed_at: dict[str, datetime] = field(default_factory=dict)
    redeemed: dict[str, int] = field(default_factory=dict)
    end_time: datetime = DEMO_REFERENCE_TIME


def _respond(builder: _Builder, ledger: GhostLedger, alerts: list[Alert], confirmed: set[str],
             params: SimulationParams, traffic_end: datetime,
             linked: dict[str, list[str]] | None = None) -> _Response:
    """Machine a etats §3.5 : delay a l'alerte, puis destroy (multisig) si l'audit
    humain confirme le sujet, sinon expiration automatique du retard.

    `linked` : perimetres contamines par lignage (ex. pool ayant recu le Ghost suspect).
    """
    human_delay = timedelta(minutes=params.human_confirmation_delay_minutes)
    events: list[tuple[datetime, int, str, Alert, str]] = []
    for alert in sorted(alerts, key=lambda a: a.created_at):
        subject = alert.subject_address
        for perimeter in [subject, *(linked or {}).get(subject, [])]:
            events.append((alert.created_at, len(events), "delay", alert, perimeter))
            if subject in confirmed:
                events.append((alert.created_at + human_delay, len(events), "destroy", alert,
                               perimeter))
            else:
                events.append((alert.created_at + DEMO_EXTENDED_WINDOW, len(events), "expire",
                               alert, perimeter))
    response = _Response()
    delays: dict[tuple[str, str], ResponseAction] = {}
    for at, _, kind, alert, perimeter in sorted(events, key=lambda e: (e[0], e[1])):
        if kind == "delay":
            ledger.convert_after_window(at)
            action = apply_delay(builder, alert, at, ledger.balance(perimeter, at), perimeter)
            if action.expires_at is not None:
                ledger.hold(perimeter, action.expires_at)
            delays[(alert.alert_id, perimeter)] = action
            response.delays.append(action)
        elif kind == "destroy":
            ledger.convert_after_window(at)
            balance = ledger.balance(perimeter, at)
            ratio = ledger.ratio(perimeter, at)
            if confirm_destroy(builder, alert, at, balance, ratio, perimeter) is not None:
                ledger.burn(perimeter, ratio, at)
                response.destroyed_at.setdefault(perimeter, at)
        else:
            ratio = ledger.ratio(perimeter, at)
            before = ledger.converted.get(perimeter, 0)
            ledger.convert_after_window(at)
            amount = ledger.converted.get(perimeter, 0) - before
            expire_delay(builder, delays[(alert.alert_id, perimeter)], amount, ratio)
            response.redeemed[perimeter] = response.redeemed.get(perimeter, 0) + amount
    times = [e[0] for e in events] + [a.expires_at for a in response.delays if a.expires_at]
    response.end_time = max([traffic_end, *(t + _bucket(params) for t in times)])
    ledger.convert_after_window(response.end_time)
    return response


def _count_actions(actions: list[ResponseAction], types: set[ResponseActionType]) -> int:
    """Actions des `types` donnes effectivement appliquees (y compris expirees depuis)."""
    applied = {ResponseActionStatus.APPLIED, ResponseActionStatus.EXPIRED}
    return sum(1 for a in actions if a.action_type in types and a.status in applied)


@dataclass
class _AttackRun:
    legit: list[str]
    attackers: list[str]
    attack_start: datetime
    traffic_end: datetime
    attack: list[TransferEvent]
    alerts: list[Alert]
    ledger: GhostLedger


def _simulate_attack(rng: random.Random, builder: _Builder,
                     params: SimulationParams) -> _AttackRun:
    """Warmup legitime puis mints attaquant sous plafond ; detection simulee."""
    start = builder.t0
    legit = legit_addresses(rng, params.legit_address_count)
    attackers = legit_addresses(rng, params.attacker_address_count)
    buckets = params.warmup_buckets + params.attack_buckets
    traffic = legit_traffic(rng, legit, start, buckets, params)
    attack_start = start + params.warmup_buckets * _bucket(params)
    attack = attacker_transfers(rng, attackers, attack_start, params)
    _log_traffic(builder, start, len(traffic), len(attack))
    ledger = GhostLedger(DEMO_NORMAL_WINDOW)
    for transfer in attack:
        ledger.credit(transfer.recipient, transfer.amount, ATTACK_SUSPECT_RATIO,
                      transfer.observed_at)
    for attacker in attackers:
        received = [t for t in attack if t.recipient == attacker]
        if received:
            builder.ghost_mint(attacker, sum(t.amount for t in received), ATTACK_SUSPECT_RATIO,
                               received[0].observed_at, DEMO_NORMAL_WINDOW)
    alerts = detect(builder, sorted(traffic + attack, key=lambda t: t.observed_at), start, params)
    return _AttackRun(legit, attackers, attack_start, start + buckets * _bucket(params), attack,
                      alerts, ledger)


# --- A : meme attaque rejouee (vulnerable vs protege) ------------------------


@dataclass(frozen=True)
class _MinterOutcome:
    """Etat final d'un minter apres l'attaque (montants dans `unit`)."""

    minted: int
    supply: int
    collateral: int
    loss: int
    deposit: int
    signed_amount: int
    inflated_call_accepted: bool | None = None  # None : non observe (simulation)


_A_VARIANTS = (("vulnerable", "Contrat vulnérable"), ("protected", "Contrat protégé"))


def _a_request(rng: random.Random, params: SimulationParams) -> MintRequest:
    return MintRequest(
        request_id=rng.randint(1, 10_000), requester=_fake_address(rng),
        deposit_token=_fake_address(rng), deposit_amount=params.deposit_amount,
        created_at=DEMO_REFERENCE_TIME, chain_id=DEMO_CHAIN_ID,
        signature="0x" + format(rng.getrandbits(520), "0130x"),
    )


def _a_sim_outcomes(request: MintRequest, params: SimulationParams) -> dict[str, _MinterOutcome]:
    signed_amount = params.deposit_amount * params.signed_amount_multiplier
    outcomes: dict[str, _MinterOutcome] = {}
    vulnerable = VulnerableMinter()
    minted = vulnerable.mint(signed_amount, request.deposit_amount)
    outcomes["vulnerable"] = _MinterOutcome(minted, vulnerable.supply, vulnerable.collateral,
                                            vulnerable.unbacked(), request.deposit_amount,
                                            signed_amount)
    protected = ProtectedMinter()
    minted = protected.process(request)
    outcomes["protected"] = _MinterOutcome(minted, protected.supply, protected.collateral,
                                           protected.unbacked(), request.deposit_amount,
                                           signed_amount)
    return outcomes


def _a_variants(seed: int, rng: random.Random, request: MintRequest,
                outcomes: dict[str, _MinterOutcome], source: str, unit: str,
                where: str) -> list[ScenarioVariant]:
    """Variantes A (meme demande, meme montant signe) a partir des etats finaux."""
    requester = request.requester
    variants: list[ScenarioVariant] = []
    for name, label in _A_VARIANTS:
        outcome = outcomes[name]
        builder = _Builder(rng, DEMO_REFERENCE_TIME)
        at = builder.at(1)
        builder.log(request.created_at, "contract", "mint_request_registered",
                    f"Demande de mint et dépôt enregistrés ({where}).",
                    {"request_id": request.request_id, "deposit_amount": outcome.deposit},
                    subject_address=requester)
        builder.log(at, "attacker", "mint_authorization_signed",
                    "Autorisation signée (clé volée) avec un montant anormal.",
                    {"request_id": request.request_id, "signed_amount": outcome.signed_amount},
                    subject_address=requester)
        message = ("Mint accepté : le contrat crédite le montant signé."
                   if name == "vulnerable" else
                   "Mint traité : montant dérivé du dépôt on-chain, montant signé ignoré.")
        builder.log(at, "contract", "mint_processed", message,
                    {"request_id": request.request_id, "signed_amount": outcome.signed_amount,
                     "minted_amount": outcome.minted, "deposit_amount": outcome.deposit},
                    subject_address=requester)
        # Aucun surveillant dans ce scenario : rien n'est marque suspect (ratio 0).
        builder.ghost_mint(requester, outcome.minted, LEGIT_RATIO, at, DEMO_NORMAL_WINDOW)
        checks = [ScenarioCheck(label="vulnérable vidé", expected="perte protocole > 0",
                                passed=outcome.loss > 0)
                  if name == "vulnerable" else
                  ScenarioCheck(label="protégé borné", expected="perte protocole = 0",
                                passed=outcome.loss == 0)]
        if name == "protected" and outcome.inflated_call_accepted is not None:
            checks.append(ScenarioCheck(
                label="appel avec montant et destinataire refusé",
                expected="completeSwap(id, destinataire, montant) rejeté on-chain",
                passed=not outcome.inflated_call_accepted))
        variants.append(ScenarioVariant(
            name=name, label=label,
            metrics=[
                _metric("protocol_loss", "Perte protocole (offre non adossée)", outcome.loss,
                        unit, source),
                _metric("minted", "Montant émis", outcome.supply, unit, source),
                _metric("collateral", "Dépôt adossé", outcome.collateral, unit, source),
            ],
            checks=checks, dataset=build_dataset(builder, seed), end_time=at,
        ))
    return variants


def _run_a_sim(seed: int, params: SimulationParams) -> ScenarioResult:
    rng = random.Random(seed)
    request = _a_request(rng, params)
    outcomes = _a_sim_outcomes(request, params)
    return _result("A", seed, _a_variants(seed, rng, request, outcomes, SIMULATION_LABEL,
                                          "base units", "simulés"))


def _run_a_anvil(seed: int, params: SimulationParams,
                 chain_factory: Callable[[], real_contracts.AnvilChain]) -> ScenarioResult:
    """Rejoue l'attaque sur les vrais contrats #4/#5 deployes sur une chaine anvil locale."""
    rng = random.Random(seed)
    request = _a_request(rng, params)
    with chain_factory() as chain:
        readings = real_contracts.replay_scenario_a(chain, params.deposit_amount,
                                                    params.signed_amount_multiplier)
    outcomes = {
        name: _MinterOutcome(
            minted=r.minted, supply=r.minted, collateral=r.collateral, loss=r.unbacked,
            deposit=params.deposit_amount * real_contracts.DECIMALS_SCALE,
            signed_amount=r.signed_amount, inflated_call_accepted=r.inflated_call_accepted,
        )
        for name, r in readings.items()
    }
    variants = _a_variants(seed, rng, request, outcomes, real_source(OPT_IN_BY["A"]),
                           "base units (stable, 18 déc.)", "on-chain, anvil local")
    return _result("A", seed, variants, replace_by=(),
                   message=f"Rejoué avec la seed {seed} sur une chaîne anvil locale : contrats "
                           "Foundry #4/#5 réels, offre et collatéral lus on-chain (comptages, "
                           "pas des mesures du contrat déployé).")


def run_a(seed: int, params: SimulationParams,
          chain_factory: Callable[[], real_contracts.AnvilChain] | None = None) -> ScenarioResult:
    """Meme MintRequest et meme montant signe rejoues sur les deux minters.

    `SH_DEMO_CONTRACTS_BACKEND=anvil` : vrais contrats #4/#5 sur anvil ; repli automatique
    sur la simulation (bandeau conserve) si Foundry est absent ou si le rejeu echoue.
    """
    backend = real_contracts.selected_backend()
    if backend != real_contracts.BACKEND_ANVIL:
        return _run_a_sim(seed, params)
    reason = real_contracts.unavailable_reason() if chain_factory is None else None
    if reason is None:
        try:
            return _run_a_anvil(seed, params, chain_factory or real_contracts.AnvilChain)
        except real_contracts.ContractsBackendError as exc:
            reason = str(exc)
    fallback = _run_a_sim(seed, params)
    return fallback.model_copy(update={
        "message": f"Backend anvil demandé mais indisponible ({reason}) : repli sur la "
                   f"{SIMULATION_LABEL}. " + fallback.message,
    })


# --- B : attaquant sous les plafonds -----------------------------------------


def _log_generated(builder: _Builder, at: datetime, transfers: int, mints: int,
                   attack_events: int = 0) -> None:
    builder.log(at, "simulation", "simulation_started",
                f"Trafic du générateur data/ (#24) : {transfers} transferts, {mints} mints, "
                f"dont {attack_events} événements d'attaque (vérité terrain du manifeste).",
                {"transfers": transfers, "mints": mints, "attack_events": attack_events})


def _real_message(seed: int, simulated: str | None) -> str:
    rest = (f" ; {simulated} : {SIMULATION_LABEL}" if simulated
            else " ; aucune brique simulée")
    return (f"Rejoué avec la seed {seed} : trafic #24, surveillants #11/#12 et réponse #17 "
            f"réels{rest}. Comptages sur trafic synthétique, pas des mesures de performance.")


def run_b(seed: int, params: SimulationParams) -> ScenarioResult:
    """Detournement 1:1 (#24) : aucun mint hors I1, le contrat seul ne voit rien ; les
    vrais surveillants #11/#12 et la vraie reponse #17 tournent sur le trafic genere."""
    rng = random.Random(seed)
    builder = _Builder(rng, DEMO_REFERENCE_TIME)
    gen = generation_params(seed, params)
    scenario = generate_scenario_b(gen)
    attack = scenario.manifest["attack"]
    attack_txs = set(attack["tx_hashes"])
    attack_addresses = {a.lower() for a in (attack["attacker"], *attack["fresh_addresses"],
                                            attack["exit_point"])}
    deposits = {e.request_id: e.deposit_amount for e in scenario.events
                if isinstance(e, MintRequest)}
    mints = [e for e in scenario.events if isinstance(e, MintEvent)]
    transfers = [e for e in scenario.events if isinstance(e, TransferEvent)]
    attack_mints = [e for e in mints if e.request_id in attack["request_ids"]]
    _log_generated(builder, gen.start, len(transfers), len(mints),
                   sum(1 for e in (*mints, *transfers) if e.tx_hash in attack_txs))

    # Ghost (#8, simule) : seuls les lots de l'attaque sont suivis (ratio 1, verite terrain).
    ledger = GhostLedger(DEMO_NORMAL_WINDOW)

    def credit(event: MintEvent, at: datetime) -> None:
        ledger.credit(event.recipient, event.amount, ATTACK_SUSPECT_RATIO, at)
        builder.ghost_mint(event.recipient, event.amount, ATTACK_SUSPECT_RATIO, at,
                           DEMO_NORMAL_WINDOW)

    def move(event: TransferEvent, at: datetime) -> None:
        ledger.transfer(event.sender, event.recipient, event.amount, at, keep_window=True)

    moves = [(e.observed_at, partial(credit, e)) for e in attack_mints]
    moves += [(e.observed_at, partial(move, e)) for e in transfers
              if e.tx_hash in attack_txs and e.is_ghost]

    detection = run_detectors(builder, scenario.events, scenario.manifest, params)
    response = respond(builder, ledger, detection.alerts, attack_addresses, params, gen.end,
                       moves)
    t0 = min(e.observed_at for e in attack_mints)
    attack_alerts = [a for a in detection.alerts
                     if a.created_at >= t0 and alert_addresses(a) & attack_addresses]
    first = min((a.created_at for a in attack_alerts), default=None)
    delay_seconds = None if first is None else (first - t0).total_seconds()
    # Pas de plafond fixe par operation (OPEN_ANSWERS §0) : le seul controle de montant
    # on-chain est I1 (mint = depot x taux) ; un mint d'attaque a 1:1 passe.
    rejections = sum(1 for e in attack_mints
                     if e.amount != deposits[e.request_id] * GENERATOR_RATE)
    false_positives = sum(1 for a in detection.alerts if not alert_addresses(a) & attack_addresses)
    destroyed = sum(amount for address, amount in ledger.burned.items()
                    if address.lower() in attack_addresses)
    actions = response.actions
    extended = bool(attack_alerts) and all(
        any(d.action_type == ResponseActionType.DELAY and d.perimeter_address is not None
            and d.perimeter_address.lower() == a.subject_address.lower()
            and d.expires_at is not None
            and d.expires_at - d.created_at == DEMO_EXTENDED_WINDOW for d in actions)
        for a in attack_alerts
    )
    # Rapport DORA (#15) sur la premiere alerte d'attaque confirmee par le multisig (#113).
    destroyed_addresses = {address.lower() for address in response.destroyed_at}
    confirmed_alert = next((a for a in attack_alerts
                            if alert_addresses(a) & destroyed_addresses), None)
    report = None
    if confirmed_alert is not None:
        scope = alert_addresses(confirmed_alert)
        linked = related_actions(scope, actions)
        report = incident_report_markdown(
            confirmed_alert, linked,
            related_audit(scope, linked, response.orchestrator.audit_log),
            generated_at=response.end_time or gen.end)
    variant = ScenarioVariant(
        name=_MAIN, label="Détournement 1:1 puis sortie concentrée (trafic #24)",
        metrics=[
            _metric("contract_rejections", "Rejets par le contrat seul (mints d'attaque hors I1)",
                    rejections, "mints", _TRAFFIC_SOURCE),
            _metric("alert_count", "Alertes", len(detection.alerts), "alertes",
                    _DETECTION_SOURCE),
            _metric("detection_delay_seconds", "Délai de détection (depuis le mint d'attaque)",
                    delay_seconds, "s", _DETECTION_SOURCE),
            _metric("false_positive_count", "Faux positifs", false_positives, "alertes",
                    _DETECTION_SOURCE),
            _metric("suspect_ghost_destroyed", "Ghost suspect détruit", destroyed, "base units"),
            _metric("protocol_loss", "Perte protocole (Ghost suspect converti)",
                    ledger.total_converted_suspect(), "base units"),
            _delayed_share_metric(scenario.events, actions,
                                  int(scenario.manifest["initial_supply"]),
                                  "Part de l'offre en fenêtre allongée (pic, friction locale)"),
        ],
        checks=[
            ScenarioCheck(label="détecté par les surveillants",
                          expected="au moins une alerte sur une adresse de l'attaque",
                          passed=first is not None),
            ScenarioCheck(label="contrat seul ne rejette rien",
                          expected="rejets par le contrat seul = 0", passed=rejections == 0),
            ScenarioCheck(label="fenêtre allongée",
                          expected="retard appliqué sur chaque adresse de l'attaque alertée",
                          passed=extended),
            ScenarioCheck(label="rapport d'incident DORA",
                          expected="rapport #15 produit pour l'alerte confirmée par le multisig",
                          passed=report is not None),
        ],
        dataset=build_dataset(builder, seed), end_time=response.end_time or gen.end,
        incident_report=report,
    )
    return _result("B", seed, [variant], message=_real_message(seed, "Ghost (#8)"))


# --- C : gel et pare-feu de contagion (optionnel) ----------------------------


def run_c(seed: int, params: SimulationParams) -> ScenarioResult:
    """Memes emprunts sur un faux marche de pret, sans / avec lecture de la balise."""
    rng = random.Random(seed)
    builder = _Builder(rng, DEMO_REFERENCE_TIME)
    run = _simulate_attack(rng, builder, params)
    response = _respond(builder, run.ledger, run.alerts, set(run.attackers), params,
                        run.traffic_end)
    beacons = sorted(builder.beacons, key=lambda b: b.published_at)

    def published_ratio(address: str, at: datetime) -> float:
        ratio = 0.0
        for beacon in beacons:
            if beacon.address == address and beacon.published_at <= at:
                ratio = beacon.contamination_ratio
        return ratio

    # Emprunts attaquant repartis entre sa premiere reception et la destruction.
    loans: list[tuple[datetime, str, int]] = []
    count = len(run.attackers)
    for index in range(params.attacker_loan_count):
        attacker = run.attackers[index % count]
        received = [t for t in run.attack if t.recipient == attacker]
        if not received:
            continue
        per_attacker = len(range(index % count, params.attacker_loan_count, count))
        begin = received[0].observed_at
        end = response.destroyed_at.get(attacker, response.end_time)
        at = begin + (end - begin) * ((index // count + 0.5) / per_attacker)
        collateral = sum(t.amount for t in received if t.observed_at <= at) // per_attacker
        if collateral > 0:
            loans.append((at, attacker, collateral))
    span = max(response.destroyed_at.values(), default=response.end_time) - run.attack_start
    for index in range(params.legit_loan_count):
        at = run.attack_start + span * ((index + 0.5) / params.legit_loan_count)
        collateral = rng.randint(params.legit_amount_min, params.legit_amount_max)
        loans.append((at, run.legit[index % len(run.legit)], collateral))
    loans.sort(key=lambda loan: loan[0])

    dataset = build_dataset(builder, seed)
    legit = set(run.legit)
    bad_debts: dict[str, int] = {}
    variants: list[ScenarioVariant] = []
    for name, label, reads in (("without_beacon", "Sans lecture de la balise", False),
                               ("with_beacon", "Avec lecture de la balise", True)):
        market = LendingMarket(reads, params.lending_ltv, params.beacon_ratio_threshold)
        for at, address, collateral in loans:
            market.deposit_and_borrow(address, collateral, published_ratio(address, at))
        bad_debts[name] = market.bad_debt(response.destroyed_at)
        checks = []
        if reads:
            checks.append(ScenarioCheck(
                label="moins de créances douteuses avec la balise",
                expected="créances douteuses avec balise < sans balise",
                passed=bad_debts["with_beacon"] < bad_debts["without_beacon"]))
        variants.append(ScenarioVariant(
            name=name, label=label,
            metrics=[
                _metric("bad_debt", "Créances douteuses (garantie détruite)", bad_debts[name],
                        "base units"),
                _metric("loans_accepted", "Emprunts acceptés", market.accepted, "emprunts"),
                _metric("legit_loans_refused", "Emprunts légitimes refusés",
                        sum(1 for a in market.refused if a in legit), "emprunts"),
            ],
            checks=checks, dataset=dataset, end_time=response.end_time,
        ))
    return _result("C", seed, variants)


# --- D : marche secondaire du Token Ghost (optionnel) ------------------------


def run_d(seed: int, params: SimulationParams) -> ScenarioResult:
    """L'attaquant revend son Ghost a un pool ; le lot suspect est detruit."""
    rng = random.Random(seed)
    builder = _Builder(rng, DEMO_REFERENCE_TIME)
    run = _simulate_attack(rng, builder, params)
    pool_address = _fake_address(rng)
    pool = ConstantProductPool(params.pool_ghost_reserve, params.pool_stable_reserve)
    per_attacker = params.attacker_ghost_sold // len(run.attackers)
    sold_total = 0
    stable_total = 0
    for attacker in run.attackers:
        received = [t for t in run.attack if t.recipient == attacker]
        if not received:
            continue
        at = received[-1].observed_at
        moved = run.ledger.transfer(attacker, pool_address, per_attacker, at)
        if moved == 0:
            continue
        stable_out = pool.sell_ghost(moved)
        sold_total += moved
        stable_total += stable_out
        builder.ghost_mint(pool_address, moved, ATTACK_SUSPECT_RATIO, at, DEMO_NORMAL_WINDOW)
        builder.log(at, "simulation", "ghost_sold_to_pool",
                    "L'attaquant revend du Ghost aux spéculateurs du pool.",
                    {"ghost_amount": moved, "stable_out": stable_out},
                    subject_address=attacker)
    response = _respond(builder, run.ledger, run.alerts, set(run.attackers), params,
                        run.traffic_end, linked={a: [pool_address] for a in run.attackers})
    pool_burned = run.ledger.burned.get(pool_address, 0)
    pool.burn_ghost(pool_burned)
    speculator_loss = (stable_total * min(pool_burned, sold_total) // sold_total
                       if sold_total else 0)
    protocol_loss = run.ledger.total_converted_suspect()
    variant = ScenarioVariant(
        name=_MAIN, label="Revente du Ghost suspect à un pool",
        metrics=[
            _metric("protocol_loss", "Perte protocole (vrai token émis contre du Ghost suspect)",
                    protocol_loss, "base units"),
            _metric("speculator_loss", "Perte côté spéculateurs (stable versé pour du Ghost "
                    "détruit)", speculator_loss, "base units"),
            _metric("ghost_destroyed", "Ghost détruit", sum(run.ledger.burned.values()),
                    "base units"),
        ],
        checks=[
            ScenarioCheck(label="perte protocole nulle",
                          expected="perte protocole = 0 (à vérifier)", passed=protocol_loss == 0),
            ScenarioCheck(label="risque porté par les spéculateurs",
                          expected="perte côté spéculateurs > 0", passed=speculator_loss > 0),
        ],
        dataset=build_dataset(builder, seed), end_time=response.end_time,
    )
    return _result("D", seed, [variant])


# --- N1 / N2 / N3 : scenarios de controle ------------------------------------


def _legit_only(seed: int, params: SimulationParams, scenario_id: str,
                **generation: float) -> ScenarioResult:
    """Trafic legitime seul du generateur #24 rejoue dans les vrais #11/#12 puis #17."""
    rng = random.Random(seed)
    builder = _Builder(rng, DEMO_REFERENCE_TIME)
    gen = generation_params(seed, params, **generation)
    scenario = generate_normal(gen)
    mints = sum(1 for e in scenario.events if isinstance(e, MintEvent))
    _log_generated(builder, gen.start,
                   sum(1 for e in scenario.events if isinstance(e, TransferEvent)), mints)
    detection = run_detectors(builder, scenario.events, scenario.manifest, params)
    alerts = detection.alerts
    response = respond(builder, GhostLedger(DEMO_NORMAL_WINDOW), alerts, set(), params, gen.end)
    freezes = _count_actions(response.actions,
                             {ResponseActionType.DELAY, ResponseActionType.DESTROY})
    no_alert = ScenarioCheck(label="zéro alerte", expected="aucune alerte sur du trafic légitime",
                             passed=not alerts)
    if scenario_id == "N1":
        metrics = [
            _metric("alert_count", "Alertes", len(alerts), "alertes", _DETECTION_SOURCE),
            _metric("freeze_count", "Retards / destructions appliqués", freezes, "actions",
                    _RESPONSE_SOURCE),
            _metric("false_positive_count", "Faux positifs", len(alerts), "alertes",
                    _DETECTION_SOURCE),
        ]
        checks = [no_alert, ScenarioCheck(label="zéro gel", expected="aucun retard ni destruction",
                                          passed=freezes == 0)]
        label = "Trafic légitime seul (générateur #24)"
    else:
        days = daily_volumes(detection.slots, gen.start)
        growth_measured = days[-1] / days[0] if len(days) > 1 and days[0] else None
        metrics = [
            _metric("volume_growth_measured", "Croissance du volume (dernier / premier jour)",
                    growth_measured, "×", _TRAFFIC_SOURCE),
            _metric("alert_count", "Alertes", len(alerts), "alertes", _DETECTION_SOURCE),
        ]
        checks = [ScenarioCheck(label="pas de déclenchement",
                                expected="aucune alerte malgré la croissance", passed=not alerts)]
        label = "Croissance légitime forte (générateur #24)"
    variant = ScenarioVariant(name=_MAIN, label=label, metrics=metrics, checks=checks,
                              dataset=build_dataset(builder, seed),
                              end_time=response.end_time or gen.end)
    return _result(scenario_id, seed, [variant], message=_real_message(seed, None))


def run_n1(seed: int, params: SimulationParams) -> ScenarioResult:
    """Trafic legitime seul : on compte les faux positifs."""
    return _legit_only(seed, params, "N1")


def run_n2(seed: int, params: SimulationParams) -> ScenarioResult:
    """Croissance legitime forte et large : volume eleve SANS dispersion effondree.

    `growth` du generateur = +(growth_factor - 1) sur la periode (x growth_factor a la fin).
    """
    return _legit_only(seed, params, "N2", growth=max(0.0, params.growth_factor - 1.0))


def run_n3(seed: int, params: SimulationParams) -> ScenarioResult:
    """Burst legitime concentre : retard declenche, aucune confirmation, retour seul.

    Le burst (consolidation vers une adresse ancienne, depuis des adresses anciennes) est
    injecte par le dashboard (`sim_traffic.consolidation_burst`) dans le trafic normal #24,
    le dernier jour a midi, avec des montants tires du trafic legitime genere.
    """
    rng = random.Random(seed)
    builder = _Builder(rng, DEMO_REFERENCE_TIME)
    gen = generation_params(seed, params)
    scenario = generate_normal(gen)
    legit = list(scenario.manifest["known_addresses"])
    transfers = [e for e in scenario.events if isinstance(e, TransferEvent)]
    sink = rng.choice(legit)  # adresse ancienne (population initiale du generateur)
    burst_start = gen.start + timedelta(days=params.real_traffic_days - 1, hours=12)
    burst = consolidation_burst(rng, legit, sink, burst_start, params,
                                amounts=[t.amount for t in transfers])
    events = sorted([*scenario.events, *burst], key=event_time)
    _log_generated(builder, gen.start, len(transfers) + len(burst),
                   sum(1 for e in scenario.events if isinstance(e, MintEvent)))
    builder.log(burst_start, "simulation", "consolidation_burst",
                f"Burst légitime injecté par le dashboard : {len(burst)} transferts vers une "
                "adresse ancienne.", {"transfers": len(burst)}, subject_address=sink)
    ledger = GhostLedger(DEMO_NORMAL_WINDOW)
    builder.ghost_mint(sink, sum(t.amount for t in burst), LEGIT_RATIO, burst_start,
                       DEMO_NORMAL_WINDOW)

    def credit(event: TransferEvent, at: datetime) -> None:
        ledger.credit(event.recipient, event.amount, LEGIT_RATIO, at)

    detection = run_detectors(builder, events, scenario.manifest, params)
    alerts = detection.alerts
    response = respond(builder, ledger, alerts, set(), params, gen.end,
                       [(t.observed_at, partial(credit, t)) for t in burst])
    actions = response.actions
    end_time = response.end_time or gen.end
    states = derive_perimeter_states(builder.alerts, actions, end_time)
    delayed = sum(1 for s in states.values() if s == PerimeterState.DELAYED)
    destroys = sum(1 for a in actions if a.action_type == ResponseActionType.DESTROY)
    delays = _count_actions(actions, {ResponseActionType.DELAY})
    variant = ScenarioVariant(
        name=_MAIN, label="Fausse alerte auto-expirante (trafic #24 + burst)",
        metrics=[
            _metric("false_positive_count", "Faux positifs", len(alerts), "alertes",
                    _DETECTION_SOURCE),
            _metric("delayed_perimeters_at_end", "Périmètres retardés à la fin", delayed,
                    "périmètres", _RESPONSE_SOURCE),
            _metric("ghost_redeemed", "Ghost converti 1:1 après expiration",
                    sum(response.redeemed.values()), "base units"),
            _metric("destroy_count", "Destructions", destroys, "actions", _RESPONSE_SOURCE),
            _delayed_share_metric(events, actions, int(scenario.manifest["initial_supply"]),
                                  "Part de l'offre inutilement retardée (pic, borne basse)"),
        ],
        checks=[
            ScenarioCheck(label="fenêtre allongée déclenchée",
                          expected="au moins un retard appliqué", passed=delays > 0),
            ScenarioCheck(label="fenêtre revenue à la normale",
                          expected="aucun périmètre retardé à la fin", passed=delayed == 0),
            ScenarioCheck(label="aucun gel définitif", expected="0 destruction",
                          passed=destroys == 0),
        ],
        dataset=build_dataset(builder, seed), end_time=end_time,
    )
    return _result("N3", seed, [variant],
                   message=_real_message(seed, "Ghost (#8) et burst injecté par le dashboard"))


# --- Enregistrement ------------------------------------------------------------


def _spec(scenario_id: str, title: str, description: str, expected: str, optional: bool,
          runner: Callable[[int, SimulationParams], ScenarioResult]) -> ScenarioSpec:
    return ScenarioSpec(id=scenario_id, title=title, description=description, expected=expected,
                        optional=optional, depends_on=DEPENDS_ON[scenario_id],
                        replace_by=REPLACE_BY[scenario_id], runner=runner,
                        implemented_by=IMPLEMENTED_BY.get(scenario_id, ()),
                        opt_in_by=OPT_IN_BY.get(scenario_id, ()),
                        opt_in_hint=real_contracts.OPT_IN_HINT if scenario_id in OPT_IN_BY else "")


SPECS: tuple[ScenarioSpec, ...] = (
    _spec("A", "Même attaque rejouée (vulnérable vs protégé)",
          "Une autorisation signée demandant un montant anormal, rejouée sur le contrat "
          "vulnérable puis sur le contrat protégé (montant dérivé on-chain du dépôt).",
          "Le vulnérable se fait vider, le protégé borne la perte.", False, run_a),
    _spec("B", "Attaquant sous les plafonds",
          "L'attaquant reste sous les seuils on-chain pour échapper au contrat seul (mint 1:1 "
          "détourné puis sortie concentrée, générateur #24) ; les surveillants doivent le "
          "repérer.",
          "Détection + alerte + allongement de fenêtre Ghost.", False, run_b),
    _spec("C", "Gel et pare-feu de contagion",
          "Un gel est publié sur la balise de risque ; on compare les créances douteuses d'un "
          "faux marché de prêt avec et sans lecture de la balise.",
          "Moins de pertes en aval quand la balise est lue.", True, run_c),
    _spec("D", "Marché secondaire du Token Ghost",
          "L'attaquant revend ses Tokens Ghost à des spéculateurs sur un pool simulé ; l'alerte "
          "est confirmée, le lot suspect est détruit.",
          "Pertes côté protocole ≈ zéro (à vérifier) vs pertes côté spéculateurs.", True, run_d),
    _spec("N1", "Trafic légitime seul",
          "Aucune attaque : uniquement du trafic légitime large.",
          "Zéro alerte, zéro gel.", False, run_n1),
    _spec("N2", "Croissance légitime forte",
          "Pic de volume large (beaucoup d'adresses anciennes), ratios normalisés stables.",
          "Pas de déclenchement (volume élevé sans dispersion effondrée).", False, run_n2),
    _spec("N3", "Fausse alerte auto-expirante",
          "Burst légitime concentré : allongement de fenêtre déclenché, aucune confirmation "
          "humaine.",
          "La fenêtre revient seule à la normale, aucun gel définitif.", False, run_n3),
)

for _registered in SPECS:
    register(_registered)
