"""Catalogue des 7 scenarios de demo (#47) : simulation hors chaîne, à remplacer par #n.

Chaque runner est deterministe pour une seed donnee (`random.Random(seed)` local,
horloge fixe `DEMO_REFERENCE_TIME`) et ne renvoie que des grandeurs MESUREES sur
l'etat final de la simulation. Le numero d'issue qui remplacera chaque brique est
porte par `replace_by`. Brancher la vraie implementation = remplacer le runner.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dashboard.demo_data import (
    DEMO_CHAIN_ID,
    DEMO_EXTENDED_WINDOW,
    DEMO_NORMAL_WINDOW,
    DEMO_REFERENCE_TIME,
    _Builder,
    _fake_address,
)
from dashboard.scenarios.config import SimulationParams
from dashboard.scenarios.models import (
    SIMULATION_LABEL,
    MeasuredMetric,
    ScenarioCheck,
    ScenarioResult,
    ScenarioSpec,
    ScenarioStatus,
    ScenarioVariant,
)
from dashboard.scenarios.registry import register
from dashboard.scenarios.sim_contracts import (
    ConstantProductPool,
    GhostLedger,
    LendingMarket,
    ProtectedMinter,
    VulnerableMinter,
)
from dashboard.scenarios.sim_detector import bucket_stats, detect
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
from shared.models import (
    Alert,
    MintRequest,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    TransferEvent,
)

# Verite terrain de la simulation : les mints de l'attaquant sont integralement frauduleux.
ATTACK_SUSPECT_RATIO = 1.0
LEGIT_RATIO = 0.0

DEPENDS_ON: dict[str, tuple[int, ...]] = {
    "A": (4, 5), "B": (11, 12, 17), "C": (7, 25), "D": (8, 25),
    "N1": (11, 12), "N2": (11, 12), "N3": (11, 12, 17),
}
REPLACE_BY: dict[str, tuple[int, ...]] = {
    "A": (4, 5, 24), "B": (11, 12, 17, 24), "C": (7, 25), "D": (8, 25),
    "N1": (11, 12), "N2": (11, 12), "N3": (11, 12, 17),
}
_MAIN = "main"


# --- Helpers communs ---------------------------------------------------------


def _metric(key: str, label: str, value: int | float | None, unit: str) -> MeasuredMetric:
    return MeasuredMetric(key=key, label=label, value=value, unit=unit, source=SIMULATION_LABEL)


def _result(scenario_id: str, seed: int, variants: list[ScenarioVariant]) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=scenario_id,
        seed=seed,
        status=ScenarioStatus.COMPLETED,
        message=f"Rejoué avec la seed {seed} : grandeurs mesurées sur l'état final "
                f"({SIMULATION_LABEL}).",
        simulated=True,
        replace_by=list(REPLACE_BY[scenario_id]),
        variants=variants,
    )


def _bucket(params: SimulationParams) -> timedelta:
    return timedelta(minutes=params.bucket_minutes)


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


def run_a(seed: int, params: SimulationParams) -> ScenarioResult:
    """Meme MintRequest et meme montant signe rejoues sur les deux minters."""
    rng = random.Random(seed)
    requester = _fake_address(rng)
    request = MintRequest(
        request_id=rng.randint(1, 10_000), requester=requester,
        deposit_token=_fake_address(rng), deposit_amount=params.deposit_amount,
        created_at=DEMO_REFERENCE_TIME, chain_id=DEMO_CHAIN_ID,
        signature="0x" + format(rng.getrandbits(520), "0130x"),
    )
    signed_amount = params.deposit_amount * params.signed_amount_multiplier
    variants: list[ScenarioVariant] = []
    for name, label in (("vulnerable", "Contrat vulnérable"), ("protected", "Contrat protégé")):
        builder = _Builder(rng, DEMO_REFERENCE_TIME)
        at = builder.at(1)
        builder.log(request.created_at, "contract", "mint_request_registered",
                    "Demande de mint et dépôt enregistrés on-chain.",
                    {"request_id": request.request_id, "deposit_amount": request.deposit_amount},
                    subject_address=requester)
        builder.log(at, "attacker", "mint_authorization_signed",
                    "Autorisation signée (clé volée) avec un montant anormal.",
                    {"request_id": request.request_id, "signed_amount": signed_amount},
                    subject_address=requester)
        if name == "vulnerable":
            minter: VulnerableMinter | ProtectedMinter = VulnerableMinter()
            minted = minter.mint(signed_amount, request.deposit_amount)
            message = "Mint accepté : le contrat crédite le montant signé."
        else:
            minter = ProtectedMinter()
            minted = minter.process(request)
            message = "Mint traité : montant dérivé du dépôt on-chain, montant signé ignoré."
        builder.log(at, "contract", "mint_processed", message,
                    {"request_id": request.request_id, "signed_amount": signed_amount,
                     "minted_amount": minted, "deposit_amount": request.deposit_amount},
                    subject_address=requester)
        # Aucun surveillant dans ce scenario : rien n'est marque suspect (ratio 0).
        builder.ghost_mint(requester, minted, LEGIT_RATIO, at, DEMO_NORMAL_WINDOW)
        loss = minter.unbacked()
        check = (ScenarioCheck(label="vulnérable vidé", expected="perte protocole > 0",
                               passed=loss > 0)
                 if name == "vulnerable" else
                 ScenarioCheck(label="protégé borné", expected="perte protocole = 0",
                               passed=loss == 0))
        variants.append(ScenarioVariant(
            name=name, label=label,
            metrics=[
                _metric("protocol_loss", "Perte protocole (offre non adossée)", loss,
                        "base units"),
                _metric("minted", "Montant émis", minter.supply, "base units"),
                _metric("collateral", "Dépôt adossé", minter.collateral, "base units"),
            ],
            checks=[check], dataset=build_dataset(builder, seed), end_time=at,
        ))
    return _result("A", seed, variants)


# --- B : attaquant sous les plafonds -----------------------------------------


def run_b(seed: int, params: SimulationParams) -> ScenarioResult:
    """Mints sous plafond : le contrat seul ne rejette rien, les surveillants alertent."""
    rng = random.Random(seed)
    builder = _Builder(rng, DEMO_REFERENCE_TIME)
    run = _simulate_attack(rng, builder, params)
    attackers = set(run.attackers)
    response = _respond(builder, run.ledger, run.alerts, attackers, params, run.traffic_end)
    attacker_alerts = [a for a in run.alerts if a.subject_address in attackers]
    first = min((a.created_at for a in attacker_alerts), default=None)
    delay_seconds = None if first is None else (first - run.attack_start).total_seconds()
    rejections = sum(1 for t in run.attack if t.amount > params.onchain_cap_per_tx)
    false_positives = sum(1 for a in run.alerts if a.subject_address not in attackers)
    destroyed = sum(run.ledger.burned.get(a, 0) for a in run.attackers)
    extended = bool(attacker_alerts) and all(
        any(d.perimeter_address == a.subject_address and d.expires_at is not None
            and d.expires_at - d.created_at == DEMO_EXTENDED_WINDOW for d in response.delays)
        for a in attacker_alerts
    )
    variant = ScenarioVariant(
        name=_MAIN, label="Attaquant sous les plafonds",
        metrics=[
            _metric("contract_rejections", "Rejets par le contrat seul", rejections,
                    "transferts"),
            _metric("alert_count", "Alertes", len(run.alerts), "alertes"),
            _metric("detection_delay_seconds", "Délai de détection", delay_seconds, "s"),
            _metric("false_positive_count", "Faux positifs", false_positives, "alertes"),
            _metric("suspect_ghost_destroyed", "Ghost suspect détruit", destroyed, "base units"),
            _metric("protocol_loss", "Perte protocole (Ghost suspect converti)",
                    run.ledger.total_converted_suspect(), "base units"),
        ],
        checks=[
            ScenarioCheck(label="détecté par les surveillants",
                          expected="au moins une alerte sur l'attaquant", passed=first is not None),
            ScenarioCheck(label="contrat seul ne rejette rien",
                          expected="rejets par le contrat seul = 0", passed=rejections == 0),
            ScenarioCheck(label="fenêtre allongée",
                          expected="retard appliqué sur chaque adresse attaquante alertée",
                          passed=extended),
        ],
        dataset=build_dataset(builder, seed), end_time=response.end_time,
    )
    return _result("B", seed, [variant])


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


def _legit_only(seed: int, params: SimulationParams, growth: float,
                scenario_id: str) -> ScenarioResult:
    rng = random.Random(seed)
    builder = _Builder(rng, DEMO_REFERENCE_TIME)
    start = builder.t0
    buckets = params.warmup_buckets + params.baseline_buckets
    legit = legit_addresses(rng, params.legit_address_count)
    traffic = legit_traffic(rng, legit, start, buckets, params, growth=growth)
    _log_traffic(builder, start, len(traffic))
    alerts = detect(builder, traffic, start, params)
    response = _respond(builder, GhostLedger(DEMO_NORMAL_WINDOW), alerts, set(), params,
                        start + buckets * _bucket(params))
    freezes = _count_actions(builder.actions,
                             {ResponseActionType.DELAY, ResponseActionType.DESTROY})
    no_alert = ScenarioCheck(label="zéro alerte", expected="aucune alerte sur du trafic légitime",
                             passed=not alerts)
    if scenario_id == "N1":
        metrics = [
            _metric("alert_count", "Alertes", len(alerts), "alertes"),
            _metric("freeze_count", "Retards / destructions appliqués", freezes, "actions"),
            _metric("false_positive_count", "Faux positifs", len(alerts), "alertes"),
        ]
        checks = [no_alert, ScenarioCheck(label="zéro gel", expected="aucun retard ni destruction",
                                          passed=freezes == 0)]
        label = "Trafic légitime seul"
    else:
        stats = bucket_stats(traffic, start, params.bucket_minutes, params.supply)
        growth_measured = stats[-1].volume / stats[0].volume if stats and stats[0].volume else None
        metrics = [
            _metric("volume_growth_measured", "Croissance du volume (dernière / première tranche)",
                    growth_measured, "×"),
            _metric("alert_count", "Alertes", len(alerts), "alertes"),
        ]
        checks = [ScenarioCheck(label="pas de déclenchement",
                                expected="aucune alerte malgré la croissance", passed=not alerts)]
        label = "Croissance légitime forte"
    variant = ScenarioVariant(name=_MAIN, label=label, metrics=metrics, checks=checks,
                              dataset=build_dataset(builder, seed), end_time=response.end_time)
    return _result(scenario_id, seed, [variant])


def run_n1(seed: int, params: SimulationParams) -> ScenarioResult:
    """Trafic legitime seul : on mesure les faux positifs."""
    return _legit_only(seed, params, 1.0, "N1")


def run_n2(seed: int, params: SimulationParams) -> ScenarioResult:
    """Croissance legitime forte et large : volume eleve SANS dispersion effondree."""
    return _legit_only(seed, params, params.growth_factor, "N2")


def run_n3(seed: int, params: SimulationParams) -> ScenarioResult:
    """Burst legitime concentre : retard declenche, aucune confirmation, retour seul."""
    rng = random.Random(seed)
    builder = _Builder(rng, DEMO_REFERENCE_TIME)
    start = builder.t0
    legit = legit_addresses(rng, params.legit_address_count)
    buckets = params.warmup_buckets + 1
    traffic = legit_traffic(rng, legit, start, buckets, params)
    sink = traffic[0].recipient  # adresse ancienne : deja active pendant le warmup
    burst = consolidation_burst(rng, legit, sink, start + params.warmup_buckets * _bucket(params),
                                params)
    _log_traffic(builder, start, len(traffic) + len(burst))
    ledger = GhostLedger(DEMO_NORMAL_WINDOW)
    for transfer in burst:
        ledger.credit(transfer.recipient, transfer.amount, LEGIT_RATIO, transfer.observed_at)
    alerts = detect(builder, sorted(traffic + burst, key=lambda t: t.observed_at), start, params)
    response = _respond(builder, ledger, alerts, set(), params, start + buckets * _bucket(params))
    states = derive_perimeter_states(builder.alerts, builder.actions, response.end_time)
    delayed = sum(1 for s in states.values() if s == PerimeterState.DELAYED)
    destroys = sum(1 for a in builder.actions if a.action_type == ResponseActionType.DESTROY)
    delays = _count_actions(builder.actions, {ResponseActionType.DELAY})
    variant = ScenarioVariant(
        name=_MAIN, label="Fausse alerte auto-expirante",
        metrics=[
            _metric("false_positive_count", "Faux positifs", len(alerts), "alertes"),
            _metric("delayed_perimeters_at_end", "Périmètres retardés à la fin", delayed,
                    "périmètres"),
            _metric("ghost_redeemed", "Ghost converti 1:1 après expiration",
                    sum(response.redeemed.values()), "base units"),
            _metric("destroy_count", "Destructions", destroys, "actions"),
        ],
        checks=[
            ScenarioCheck(label="fenêtre allongée déclenchée",
                          expected="au moins un retard appliqué", passed=delays > 0),
            ScenarioCheck(label="fenêtre revenue à la normale",
                          expected="aucun périmètre retardé à la fin", passed=delayed == 0),
            ScenarioCheck(label="aucun gel définitif", expected="0 destruction",
                          passed=destroys == 0),
        ],
        dataset=build_dataset(builder, seed), end_time=response.end_time,
    )
    return _result("N3", seed, [variant])


# --- Enregistrement ------------------------------------------------------------


def _spec(scenario_id: str, title: str, description: str, expected: str, optional: bool,
          runner: Callable[[int, SimulationParams], ScenarioResult]) -> ScenarioSpec:
    return ScenarioSpec(id=scenario_id, title=title, description=description, expected=expected,
                        optional=optional, depends_on=DEPENDS_ON[scenario_id],
                        replace_by=REPLACE_BY[scenario_id], runner=runner)


SPECS: tuple[ScenarioSpec, ...] = (
    _spec("A", "Même attaque rejouée (vulnérable vs protégé)",
          "Une autorisation signée demandant un montant anormal, rejouée sur le contrat "
          "vulnérable puis sur le contrat protégé (montant dérivé on-chain du dépôt).",
          "Le vulnérable se fait vider, le protégé borne la perte.", False, run_a),
    _spec("B", "Attaquant sous les plafonds",
          "L'attaquant reste sous les seuils on-chain pour échapper au contrat seul ; les "
          "surveillants doivent le repérer.",
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
