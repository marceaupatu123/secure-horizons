"""Generateur de donnees synthetiques (FICTIVES) — decision §6 (`docs/OPEN_ANSWERS.md`).

Produit des fichiers **JSONL** : une ligne = un modele de `shared.models`
(`MintRequest`, `MintEvent`, `TransferEvent`), valide par Pydantic strict. Le
schema n'est pas redefini ici : on serialise les modeles partages.

Jeux produits :

- `normal`  : trafic legitime seul (#59), denominateur du taux de faux positifs
  (§5). Mints coherents 1:1 vers le deposant (I1 + I3), transferts disperses
  sur une population d'adresses anciennes, saisonnalite par creneau de 5 min,
  croissance progressive.
- `A`       : mint gonfle facon Resolv (#24), rejoue en deux variantes sur le
  meme fond de trafic : `vulnerable` (mint ~400x le depot) et `protected`
  (mint derive du depot, 1:1).
- `B`       : hypothese du volet 1 qui tombe (#24, #49) : detournement a 1:1
  (I3) — la demande d'une victime est mintee vers une adresse neuve de
  l'attaquant — puis sortie rapide vers peu d'adresses neuves et un point de
  sortie (volume eleve ET dispersion effondree, §9).

Chaque fichier est accompagne d'un **manifeste** JSON (graine, parametres,
verite terrain de l'attaque : adresses, tx, `t0`) pour les mesures de la §5.
Les timestamps des evenements sont le temps simule du bloc (`t0`) ; les numeros
de bloc en derivent (temps de bloc approximatif, parametre).

Tous les parametres sont des **parametres de generation a calibrer**, pas des
chiffres mesures (`docs/CLAIMS.md`). Seule reference externe : Resolv
(~200 000 USDC deposes, 80M USR mintes, ratio ~400x), cf. §1.

Scenarios C et D : voir `data/scenarios_cd.py`.

Lancement : `python -m data.generate --scenario <normal|A|B|C|D|all> --seed <n>`
ou `make data`.
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import json
import math
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Union

from pydantic import ValidationError

from shared.models import (
    GhostTokenBurnEvent,
    GhostTokenMintEvent,
    GhostTokenRedemptionEvent,
    MintEvent,
    MintRequest,
    RiskBeaconUpdate,
    TransferEvent,
)

Event = Union[
    MintRequest,
    MintEvent,
    TransferEvent,
    GhostTokenMintEvent,
    GhostTokenRedemptionEvent,
    GhostTokenBurnEvent,
    RiskBeaconUpdate,
]
EVENT_MODELS: tuple[type[Any], ...] = (
    MintRequest,
    MintEvent,
    TransferEvent,
    GhostTokenMintEvent,
    GhostTokenRedemptionEvent,
    GhostTokenBurnEvent,
    RiskBeaconUpdate,
)
"""Modeles partages pouvant apparaitre dans un JSONL genere (normal, A, B, C, D)."""

FUJI_CHAIN_ID = 43113
TOKEN_DECIMALS = 6
"""Token fictif a 6 decimales (type USDC) : les montants base units tiennent en int64
(lecture `pandas.read_json` sans perte), y compris l'attaque a 80M."""
UNIT = 10**TOKEN_DECIMALS
DEPOSIT_TOKEN = "0x" + "d0" * 20
"""Token de depot fictif."""
EXIT_POINT = "0x" + "e1" * 20
"""Point de sortie fictif (exchange / bridge). La liste reelle reste ouverte (§2)."""
GENESIS_BLOCK = 30_000_000
DEFAULT_START = datetime(2026, 10, 10, tzinfo=timezone.utc)
DEFAULT_OUT_DIR = Path("data/generated")
RESOLV_INFLATION = 400
"""Ratio mint / depot de l'incident Resolv (post-mortem du 22 mars 2026, cf. §1)."""


@dataclass(frozen=True)
class GenerationParams:
    """Parametres de generation (a calibrer, pas des mesures).

    Attributes:
        seed: graine aleatoire (reproductibilite).
        start: debut de la periode simulee (UTC).
        hours: duree simulee.
        slot_minutes: creneau d'agregation du trafic (§2/§5 : 5 min).
        users: taille de la population legitime.
        mints_per_slot: nombre moyen de mints par creneau (avant saisonnalite).
        transfers_per_slot: nombre moyen de transferts par creneau.
        seasonality: amplitude de la variation jour/nuit (0 = plate).
        growth: croissance progressive du volume sur la periode (0.1 = +10 %).
        mean_deposit_tokens: depot moyen d'un utilisateur legitime (tokens).
        ghost_window_minutes: fenetre Ghost normale (§0bis : ex. 10 min).
        block_time_seconds: temps de bloc approximatif (Fuji ~2 s).
        attack_at_fraction: position de l'attaque dans la periode (historique
            suffisant avant pour calibrer la baseline mediane + MAD).
        attack_deposit_tokens: depot total de l'attaque (Resolv : ~200 000).
        attack_inflation: ratio mint / depot sur le contrat vulnerable (A).
        exit_hops: nombre d'adresses neuves intermediaires (B).
    """

    seed: int = 42
    start: datetime = DEFAULT_START
    hours: float = 24.0
    slot_minutes: int = 5
    users: int = 200
    mints_per_slot: float = 1.0
    transfers_per_slot: float = 12.0
    seasonality: float = 0.5
    growth: float = 0.1
    mean_deposit_tokens: float = 1_000.0
    ghost_window_minutes: int = 10
    block_time_seconds: float = 2.0
    attack_at_fraction: float = 0.75
    attack_deposit_tokens: int = 200_000
    attack_inflation: int = RESOLV_INFLATION
    exit_hops: int = 2

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError("start doit etre un datetime UTC timezone-aware.")
        positive = (
            "hours",
            "slot_minutes",
            "mean_deposit_tokens",
            "ghost_window_minutes",
            "block_time_seconds",
            "attack_deposit_tokens",
            "attack_inflation",
            "exit_hops",
        )
        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} doit etre > 0.")
        for name in ("mints_per_slot", "transfers_per_slot", "seasonality", "growth"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} doit etre >= 0.")
        if self.users < 2:
            raise ValueError("users doit etre >= 2.")
        if not 0 < self.attack_at_fraction < 1:
            raise ValueError("attack_at_fraction doit etre dans ]0, 1[.")

    @property
    def end(self) -> datetime:
        """Fin de la periode simulee."""
        return self.start + timedelta(hours=self.hours)

    @property
    def attack_at(self) -> datetime:
        """Instant de debut de l'attaque (`t0` des scenarios A et B)."""
        return self.start + timedelta(hours=self.hours * self.attack_at_fraction)

    def to_json(self) -> dict[str, Any]:
        """Parametres serialisables (manifeste)."""
        data = asdict(self)
        data["start"] = self.start.isoformat()
        return data


@dataclass
class GeneratedScenario:
    """Un jeu genere : evenements chronologiques + manifeste (verite terrain)."""

    name: str
    events: list[Event]
    manifest: dict[str, Any] = field(default_factory=dict)


def event_time(event: Event) -> datetime:
    """Horodatage simule de l'evenement (`t0`)."""
    if isinstance(event, MintRequest):
        return event.created_at
    if isinstance(event, GhostTokenMintEvent):
        return event.minted_at
    if isinstance(event, GhostTokenRedemptionEvent):
        return event.redeemed_at
    if isinstance(event, GhostTokenBurnEvent):
        return event.burned_at
    if isinstance(event, RiskBeaconUpdate):
        return event.published_at
    return event.observed_at


class _Ledger:
    """Soldes par adresse : vrai token + lots Ghost en fenetre (§0bis : tout transfert)."""

    def __init__(self, window: timedelta) -> None:
        self._window = window
        self.real: dict[str, int] = {}
        self.ghost: dict[str, list[tuple[int, datetime]]] = {}

    def mature(self, address: str, now: datetime) -> None:
        lots = self.ghost.get(address, [])
        matured = sum(amount for amount, at in lots if at <= now)
        if matured:
            self.real[address] = self.real.get(address, 0) + matured
            self.ghost[address] = [(a, at) for a, at in lots if at > now]

    def balances(self, address: str, now: datetime) -> tuple[int, int]:
        self.mature(address, now)
        return self.real.get(address, 0), sum(a for a, _ in self.ghost.get(address, []))

    def credit_ghost(self, address: str, amount: int, now: datetime) -> None:
        self.ghost.setdefault(address, []).append((amount, now + self._window))

    def debit(self, address: str, amount: int, from_ghost: bool) -> None:
        if not from_ghost:
            self.real[address] -= amount
            return
        remaining = amount
        lots: list[tuple[int, datetime]] = []
        for lot_amount, at in self.ghost[address]:  # FIFO : les plus anciens d'abord
            used = min(lot_amount, remaining)
            remaining -= used
            if lot_amount > used:
                lots.append((lot_amount - used, at))
        if remaining:
            raise ValueError("debit Ghost superieur au solde")
        self.ghost[address] = lots


class _Simulation:
    """Simulation a evenements discrets du trafic (file de priorite par horodatage)."""

    def __init__(self, params: GenerationParams) -> None:
        self.p = params
        self.rng = random.Random(params.seed)
        self.ledger = _Ledger(timedelta(minutes=params.ghost_window_minutes))
        self.events: list[Event] = []
        self._queue: list[tuple[datetime, int, Callable[[datetime], None]]] = []
        self._seq = itertools.count()
        self._request_ids = itertools.count()
        self.users = [self.new_address() for _ in range(params.users)]
        for user in self.users:  # soldes pre-existants (pas d'evenement emis)
            self.ledger.real[user] = self.deposit_amount()

    # --- identites fictives
    def new_address(self) -> str:
        return f"0x{self.rng.getrandbits(160):040x}"

    def new_tx(self) -> str:
        return f"0x{self.rng.getrandbits(256):064x}"

    def new_signature(self) -> str:
        return f"0x{self.rng.getrandbits(520):0130x}"

    def block(self, at: datetime) -> int:
        return GENESIS_BLOCK + int((at - self.p.start).total_seconds() // self.p.block_time_seconds)

    # --- tirages
    def poisson(self, lam: float) -> int:
        if lam <= 0:
            return 0
        threshold, k, prod = math.exp(-lam), 0, self.rng.random()
        while prod > threshold:
            k += 1
            prod *= self.rng.random()
        return k

    def deposit_amount(self) -> int:
        sigma = 1.0
        mu = math.log(self.p.mean_deposit_tokens) - sigma**2 / 2
        return max(1, int(self.rng.lognormvariate(mu, sigma) * UNIT))

    def rate_factor(self, at: datetime) -> float:
        hour = at.hour + at.minute / 60
        season = 1 + self.p.seasonality * math.sin(2 * math.pi * (hour - 6) / 24)
        progress = (at - self.p.start) / (self.p.end - self.p.start)
        return max(0.0, season) * (1 + self.p.growth * progress)

    # --- file d'evenements
    def schedule(self, at: datetime, action: Callable[[datetime], None]) -> None:
        heapq.heappush(self._queue, (at, next(self._seq), action))

    def run(self) -> list[Event]:
        while self._queue:
            at, _, action = heapq.heappop(self._queue)
            action(at)
        return self.events

    # --- actions on-chain simulees
    def mint(
        self,
        requester: str,
        deposit: int,
        at: datetime,
        *,
        recipient: str | None = None,
        minted: int | None = None,
        on_done: Callable[[MintRequest, MintEvent], None] | None = None,
    ) -> None:
        """Demande n°X a `at`, traitee quelques secondes plus tard.

        Par defaut : mint 1:1 vers le deposant (I1 + I3).
        """
        request = MintRequest(
            request_id=next(self._request_ids),
            requester=requester,
            deposit_token=DEPOSIT_TOKEN,
            deposit_amount=deposit,
            created_at=at,
            chain_id=FUJI_CHAIN_ID,
            signature=self.new_signature(),
        )
        self.events.append(request)
        delay = timedelta(seconds=self.rng.uniform(2, 20))
        target = recipient or requester
        amount = deposit if minted is None else minted

        def execute(when: datetime) -> None:
            event = MintEvent(
                tx_hash=self.new_tx(),
                log_index=0,
                block_number=self.block(when),
                chain_id=FUJI_CHAIN_ID,
                observed_at=when,
                recipient=target,
                amount=amount,
                request_id=request.request_id,
            )
            self.events.append(event)
            self.ledger.credit_ghost(target, amount, when)
            if on_done is not None:
                on_done(request, event)

        self.schedule(at + delay, execute)

    def transfer(
        self, sender: str, recipient: str, amount: int, at: datetime, *, from_ghost: bool
    ) -> TransferEvent:
        self.ledger.debit(sender, amount, from_ghost)
        event = TransferEvent(
            tx_hash=self.new_tx(),
            log_index=0,
            block_number=self.block(at),
            chain_id=FUJI_CHAIN_ID,
            observed_at=at,
            sender=sender,
            recipient=recipient,
            amount=amount,
            is_ghost=from_ghost,
        )
        self.events.append(event)
        self.ledger.credit_ghost(recipient, amount, at)
        return event

    def random_transfer(self, at: datetime) -> None:
        """Transfert legitime : expediteur et destinataire tires dans toute la population."""
        for _ in range(5):
            sender = self.rng.choice(self.users)
            real, ghost = self.ledger.balances(sender, at)
            if real + ghost == 0:
                continue
            from_ghost = real == 0 or (ghost > 0 and self.rng.random() >= real / (real + ghost))
            available = ghost if from_ghost else real
            amount = max(1, int(available * self.rng.uniform(0.05, 0.5)))
            recipient = self.rng.choice(self.users)
            while recipient == sender:
                recipient = self.rng.choice(self.users)
            self.transfer(sender, recipient, amount, at, from_ghost=from_ghost)
            return

    def plan_normal_traffic(self) -> None:
        slot = timedelta(minutes=self.p.slot_minutes)
        at = self.p.start
        while at < self.p.end:
            factor = self.rate_factor(at)
            span = min(slot, self.p.end - at).total_seconds()
            for _ in range(self.poisson(self.p.mints_per_slot * factor)):
                when = at + timedelta(seconds=self.rng.uniform(0, span))
                self.schedule(when, self._legit_mint)
            for _ in range(self.poisson(self.p.transfers_per_slot * factor)):
                when = at + timedelta(seconds=self.rng.uniform(0, span))
                self.schedule(when, self.random_transfer)
            at += slot

    def _legit_mint(self, at: datetime) -> None:
        self.mint(self.rng.choice(self.users), self.deposit_amount(), at)


# --------------------------------------------------------------------- scenarios


def _counts(events: list[Event]) -> dict[str, int]:
    return dict(Counter(type(e).__name__ for e in events))


def _manifest(name: str, params: GenerationParams, events: list[Event]) -> dict[str, Any]:
    return {
        "scenario": name,
        "fictive_data": True,
        "params": params.to_json(),
        "token_decimals": TOKEN_DECIMALS,
        "chain_id": FUJI_CHAIN_ID,
        "period": {"start": params.start.isoformat(), "end": params.end.isoformat()},
        "counts": _counts(events),
        "attack": None,
    }


def generate_normal(params: GenerationParams | None = None) -> GeneratedScenario:
    """Trafic legitime seul, sans aucune attaque (#59, denominateur FP §5)."""
    params = params or GenerationParams()
    sim = _Simulation(params)
    sim.plan_normal_traffic()
    events = sim.run()
    return GeneratedScenario("normal", events, _manifest("normal", params, events))


def _scenario_a_variant(params: GenerationParams, variant: str) -> GeneratedScenario:
    sim = _Simulation(params)
    attacker = sim.new_address()
    sim.plan_normal_traffic()
    deposits = [params.attack_deposit_tokens * UNIT // 2] * 2  # Resolv : deux appels
    attack_txs: list[str] = []
    request_ids: list[int] = []

    def record(request: MintRequest, event: MintEvent) -> None:
        request_ids.append(request.request_id)
        attack_txs.append(event.tx_hash)

    for i, deposit in enumerate(deposits):
        minted = deposit * params.attack_inflation if variant == "vulnerable" else deposit
        sim.schedule(
            params.attack_at + timedelta(seconds=30 * i),
            lambda at, d=deposit, m=minted: sim.mint(attacker, d, at, minted=m, on_done=record),
        )
    events = sim.run()
    manifest = _manifest(f"A_{variant}", params, events)
    manifest["attack"] = {
        "kind": "inflated_mint",
        "contract": variant,
        "started_at": params.attack_at.isoformat(),
        "attacker": attacker,
        "request_ids": request_ids,
        "tx_hashes": attack_txs,
        "deposit_total": sum(deposits),
        "minted_total": sum(
            e.amount for e in events if isinstance(e, MintEvent) and e.tx_hash in attack_txs
        ),
        "mint_to_deposit_ratio": params.attack_inflation if variant == "vulnerable" else 1,
    }
    return GeneratedScenario(f"scenario_a_{variant}", events, manifest)


def generate_scenario_a(params: GenerationParams | None = None) -> dict[str, GeneratedScenario]:
    """Scenario A : meme fond de trafic, mint gonfle sur vulnerable vs 1:1 sur protege."""
    params = params or GenerationParams()
    return {v: _scenario_a_variant(params, v) for v in ("vulnerable", "protected")}


def generate_scenario_b(params: GenerationParams | None = None) -> GeneratedScenario:
    """Scenario B : detournement a 1:1 (I3 non applique) puis sortie concentree."""
    params = params or GenerationParams()
    sim = _Simulation(params)
    attacker = sim.new_address()
    hops = [sim.new_address() for _ in range(params.exit_hops)]
    victim = sim.rng.choice(sim.users)
    sim.plan_normal_traffic()
    attack_txs: list[str] = []
    request_ids: list[int] = []

    def drain(sender: str, recipients: list[str], at: datetime) -> None:
        """Vide le solde Ghost de `sender` en parts egales vers `recipients`."""
        _, ghost = sim.ledger.balances(sender, at)
        share = ghost // len(recipients)
        for i, recipient in enumerate(recipients):
            amount = share if i < len(recipients) - 1 else ghost - share * (len(recipients) - 1)
            if amount > 0:
                event = sim.transfer(sender, recipient, amount, at, from_ghost=True)
                attack_txs.append(event.tx_hash)

    def after_mint(request: MintRequest, event: MintEvent) -> None:
        request_ids.append(request.request_id)
        attack_txs.append(event.tx_hash)
        split_at = event.observed_at + timedelta(seconds=sim.rng.uniform(60, 180))
        sim.schedule(split_at, lambda at: drain(attacker, hops, at))
        for hop in hops:
            exit_at = split_at + timedelta(seconds=sim.rng.uniform(60, 240))
            sim.schedule(exit_at, lambda at, h=hop: drain(h, [EXIT_POINT], at))

    deposit = params.attack_deposit_tokens * UNIT
    sim.schedule(
        params.attack_at,
        lambda at: sim.mint(victim, deposit, at, recipient=attacker, on_done=after_mint),
    )
    events = sim.run()
    manifest = _manifest("B", params, events)
    manifest["attack"] = {
        "kind": "recipient_hijack_1to1",
        "broken_invariant": "I3",
        "started_at": params.attack_at.isoformat(),
        "victim": victim,
        "attacker": attacker,
        "fresh_addresses": hops,
        "exit_point": EXIT_POINT,
        "request_ids": request_ids,
        "tx_hashes": attack_txs,
        "deposit_total": deposit,
    }
    return GeneratedScenario("scenario_b", events, manifest)


# ------------------------------------------------------------------- E/S JSONL


def write_scenario(scenario: GeneratedScenario, out_dir: Path) -> tuple[Path, Path]:
    """Ecrit `<nom>.jsonl` et `<nom>.manifest.json` dans `out_dir`.

    Returns:
        Les chemins du JSONL et du manifeste.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / f"{scenario.name}.jsonl"
    with jsonl.open("w", encoding="utf-8") as sink:
        for event in scenario.events:
            sink.write(event.model_dump_json() + "\n")
    manifest = out_dir / f"{scenario.name}.manifest.json"
    manifest.write_text(
        json.dumps({**scenario.manifest, "file": jsonl.name}, indent=2) + "\n", encoding="utf-8"
    )
    return jsonl, manifest


def parse_line(line: str) -> Event:
    """Valide une ligne JSONL contre le modele partage correspondant.

    Les modeles etant stricts (`extra="forbid"`), une ligne ne valide qu'un seul
    d'entre eux.

    Raises:
        ValueError: si la ligne ne correspond a aucun modele.
    """
    for model in EVENT_MODELS:
        try:
            return model.model_validate_json(line)
        except ValidationError:
            continue
    raise ValueError(f"ligne ne correspondant a aucun modele partage : {line[:80]}")


def load_jsonl(path: Path) -> list[Event]:
    """Relit un fichier JSONL genere (une ligne = un modele de `shared.models`)."""
    with path.open(encoding="utf-8") as source:
        return [parse_line(line) for line in source if line.strip()]


# ------------------------------------------------------------------------- CLI


def build(scenario: str, params: GenerationParams) -> list[GeneratedScenario]:
    """Genere les jeux demandes (`normal`, `A`, `B`, `C`, `D` ou `all`)."""
    from data.scenarios_cd import ContagionParams, generate_scenario_c, generate_scenario_d

    contagion = ContagionParams(seed=params.seed)
    jobs: dict[str, Callable[[], list[GeneratedScenario]]] = {
        "normal": lambda: [generate_normal(params)],
        "A": lambda: list(generate_scenario_a(params).values()),
        "B": lambda: [generate_scenario_b(params)],
        "C": lambda: list(generate_scenario_c(contagion).values()),
        "D": lambda: list(generate_scenario_d(contagion).values()),
    }
    names = list(jobs) if scenario == "all" else [scenario]
    return [s for name in names for s in jobs[name]()]


def main(argv: list[str] | None = None) -> None:
    """Point d'entree : `python -m data.generate`."""
    defaults = GenerationParams()
    parser = argparse.ArgumentParser(description="Genere des donnees synthetiques FICTIVES.")
    parser.add_argument("--scenario", choices=["normal", "A", "B", "C", "D", "all"], default="all")
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--hours", type=float, default=defaults.hours)
    parser.add_argument("--users", type=int, default=defaults.users)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    params = GenerationParams(seed=args.seed, hours=args.hours, users=args.users)
    for scenario in build(args.scenario, params):
        jsonl, _ = write_scenario(scenario, args.out_dir)
        print(f"{jsonl} : {len(scenario.events)} evenements {scenario.manifest['counts']}")


if __name__ == "__main__":
    main()
