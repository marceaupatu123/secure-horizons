"""Scenarios C et D (#25) : simulation hors chaine sur le registre de reference Ghost.

Donnees FICTIVES. Tout tourne sur `data.ghost_ledger.GhostLedger` ; les evenements produits
sont des modeles de `shared.models` (JSONL, decision §6). Les resultats chiffres du manifeste
sont **mesures sur cette simulation**, avec des parametres de generation a calibrer : ce ne
sont pas des mesures on-chain (`docs/CLAIMS.md`).

Trame commune (`docs/OPEN_ANSWERS.md`) :

1. trafic legitime de fond (transferts, conversions apres la fenetre) ;
2. `t0` : mint frauduleux **non adosse** (une hypothese du volet 1 est tombee, §1) ;
3. `t0 + detect_after` : alerte. Hypothese : le surveillant reconstitue hors chaine la
   propagation du soupcon depuis le mint (meme regle que §9) et seme le resultat comme graines
   (`Alert.seeds`). Les adresses semees sont retardees (§3) et publiees sur la balise ;
4. `t0 + confirm_after` : multisig 2/3, destruction de `ratio x solde Ghost` sur chaque adresse
   contaminee (§9).

Scenario D (marche secondaire du Ghost) — trois variantes :

- `otc`      : l'attaquant revend son Ghost a des speculateurs payes comptant, qui en revendent
  une partie a des utilisateurs legitimes ;
- `pool`     : il le vend a notre pool en reglement differe (`swap-id`, §10) ;
- `no_ghost` : meme attaque sans Ghost (fenetre nulle) = baseline « Resolv tel quel » (§5).

Scenario C (contagion vers un faux marche de pret) — deux variantes, `with_beacon` /
`without_beacon` : l'attaquant fragmente son Ghost et l'apporte en garantie ; le marche (un
coffre par pret) refuse ou non les deposants dont le ratio publie depasse un seuil.
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from data.generate import DEFAULT_START, FUJI_CHAIN_ID, GENESIS_BLOCK, UNIT, GeneratedScenario
from data.ghost_ledger import GhostLedger, LedgerParams, Movement
from shared.models import (
    BeaconRiskLevel,
    GhostTokenBurnEvent,
    GhostTokenMintEvent,
    GhostTokenRedemptionEvent,
    RiskBeaconUpdate,
    TransferEvent,
)

POOL = "0x" + "c0" * 20
"""Notre pool fictif (reglement differe, §10)."""


@dataclass(frozen=True)
class ContagionParams:
    """Parametres des scenarios C et D (a calibrer, pas des mesures).

    Attributes:
        seed: graine aleatoire.
        start: debut de la simulation (UTC).
        duration_minutes: duree simulee.
        users: utilisateurs legitimes.
        legit_ticks_per_minute: activite legitime moyenne (transfert + tentative de conversion).
        attack_at_minutes: instant du mint frauduleux (`t0`), depuis `start`.
        attack_amount_tokens: montant non adosse minte par l'attaquant.
        detect_after_minutes: delai `t0 -> alerte`.
        confirm_after_minutes: delai `t0 -> destruction multisig`.
        extended_window_minutes: retard applique aux adresses semees (§3 : 10 min -> 1 h).
        speculators: acheteurs de Ghost (D).
        sales: nombre de ventes de l'attaquant (D).
        sell_span_minutes: duree de la revente apres `t0` (D).
        ghost_price: prix d'un Ghost en USDC fictif, parite = 1.0 (D).
        resale_fraction: part revendue par un speculateur a un utilisateur legitime (D).
        attacker_hops: adresses neuves de l'attaquant apportant la garantie (C).
        borrow_span_minutes: duree pendant laquelle l'attaquant emprunte apres `t0` (C).
        legit_borrowers: emprunteurs legitimes (C).
        ltv: ratio pret / garantie du marche (C).
        beacon_ratio_threshold: ratio publie au-dela duquel le marche refuse (C).
        ledger: parametres du registre Ghost.
    """

    seed: int = 42
    start: datetime = DEFAULT_START
    duration_minutes: int = 120
    users: int = 50
    legit_ticks_per_minute: float = 2.0
    attack_at_minutes: float = 20.0
    attack_amount_tokens: int = 1_000_000
    detect_after_minutes: float = 3.0
    confirm_after_minutes: float = 20.0
    extended_window_minutes: int = 60
    speculators: int = 8
    sales: int = 8
    sell_span_minutes: float = 8.0
    ghost_price: float = 0.9
    resale_fraction: float = 0.5
    attacker_hops: int = 4
    borrow_span_minutes: float = 15.0
    legit_borrowers: int = 10
    ltv: float = 0.75
    beacon_ratio_threshold: float = 0.05
    ledger: LedgerParams = field(default_factory=LedgerParams)

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError("start doit etre un datetime UTC timezone-aware.")
        if not 0 < self.detect_after_minutes < self.confirm_after_minutes:
            raise ValueError("il faut 0 < detect_after < confirm_after.")
        if self.confirm_after_minutes - self.detect_after_minutes >= self.extended_window_minutes:
            raise ValueError("la destruction doit arriver avant la fin du retard.")
        end_of_attack = self.attack_at_minutes + max(
            self.confirm_after_minutes, self.sell_span_minutes, self.borrow_span_minutes
        )
        if end_of_attack >= self.duration_minutes:
            raise ValueError("duration_minutes trop courte pour l'attaque.")
        for name in ("users", "speculators", "sales", "attacker_hops", "attack_amount_tokens"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} doit etre >= 1.")
        for name in ("ghost_price", "resale_fraction", "ltv", "beacon_ratio_threshold"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} doit etre dans [0, 1].")

    def minutes(self, value: float) -> datetime:
        """Instant `start + value` minutes."""
        return self.start + timedelta(minutes=value)

    @property
    def t0(self) -> datetime:
        """Instant du mint frauduleux."""
        return self.minutes(self.attack_at_minutes)

    def to_json(self) -> dict[str, Any]:
        """Parametres serialisables (manifeste)."""
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["ledger"] = {
            "window_minutes": self.ledger.window / timedelta(minutes=1),
            "slot_minutes": self.ledger.slot / timedelta(minutes=1),
            "ratio_threshold": self.ledger.ratio_threshold,
            "suspect_threshold": self.ledger.suspect_threshold,
        }
        return data


@dataclass
class _Claim:
    """Creance `swap-id` d'un vendeur sur notre pool (§10)."""

    swap_id: str
    seller: str
    usdc: int
    ratio_at_swap: float
    payable_at: datetime
    cancelled: int = 0
    paid: int = 0


class _World:
    """Simulation a evenements discrets autour du registre Ghost."""

    def __init__(self, p: ContagionParams, ledger: LedgerParams) -> None:
        self.p = p
        self.rng = random.Random(p.seed)
        self.ledger = GhostLedger(ledger)
        self.events: list[Any] = []
        self.usdc: Counter[str] = Counter()
        self.groups: dict[str, str] = {}
        self.shadow: dict[str, float] = {}  # soupcon reconstitue hors chaine avant l'alerte
        self.alerted_at: datetime | None = None
        self.published: dict[str, float] = {}
        self.legit_conversions = 0
        self.legit_blocked = 0
        self.leaked_before_alert = 0.0
        self.burned_by_group: Counter[str] = Counter()
        self._queue: list[tuple[datetime, int, Callable[[datetime], None]]] = []
        self._seq = itertools.count()
        self._log = itertools.count()
        self.users = [self.new_address("legit") for _ in range(p.users)]
        for user in self.users:
            self.ledger.credit_real(user, int(self.rng.uniform(1_000, 50_000)) * UNIT)
        self.attacker = self.new_address("attacker")

    # --- identites et temps
    def new_address(self, group: str) -> str:
        address = f"0x{self.rng.getrandbits(160):040x}"
        self.groups[address] = group
        return address

    def new_tx(self) -> str:
        return f"0x{self.rng.getrandbits(256):064x}"

    def block(self, at: datetime) -> int:
        return GENESIS_BLOCK + int((at - self.p.start).total_seconds() // 2)

    def schedule(self, at: datetime, action: Callable[[datetime], None]) -> None:
        heapq.heappush(self._queue, (at, next(self._seq), action))

    def run(self) -> None:
        while self._queue:
            at, _, action = heapq.heappop(self._queue)
            action(at)

    # --- operations (registre + evenements)
    def _emit_ghost(self, recipient: str, mv: Movement, tx: str, at: datetime, source: str | None) -> None:
        if mv.expires_at is None:
            return
        self.events.append(
            GhostTokenMintEvent(
                tx_hash=tx,
                log_index=next(self._log),
                block_number=self.block(at),
                chain_id=FUJI_CHAIN_ID,
                minted_at=at,
                recipient=recipient,
                amount=mv.amount,
                incoming_ratio=mv.ratio,
                window_expires_at=mv.expires_at,
                source_transfer_tx=source,
            )
        )

    def fraud_mint(self, at: datetime) -> None:
        amount = self.p.attack_amount_tokens * UNIT
        mv = self.ledger.mint(self.attacker, amount, at, backed=False)
        self._emit_ghost(self.attacker, mv, self.new_tx(), at, None)
        if self.ledger.params.ghost_enabled:
            self.shadow[self.attacker] = float(amount)

    def spend(self, sender: str, recipient: str, amount: int, at: datetime) -> bool:
        """Transfert, Ghost d'abord s'il suffit. False si solde insuffisant."""
        account = self.ledger.account(sender)
        from_ghost = account.ghost >= amount
        if not from_ghost and account.real < amount:
            return False
        sender_ghost = account.ghost
        mv = self.ledger.transfer(sender, recipient, amount, at, from_ghost=from_ghost)
        tx = self.new_tx()
        self.events.append(
            TransferEvent(
                tx_hash=tx,
                log_index=next(self._log),
                block_number=self.block(at),
                chain_id=FUJI_CHAIN_ID,
                observed_at=at,
                sender=sender,
                recipient=recipient,
                amount=amount,
                is_ghost=from_ghost,
            )
        )
        self._emit_ghost(recipient, mv, tx, at, tx)
        if self.alerted_at is None and from_ghost and self.shadow.get(sender):
            moved = self.shadow[sender] * amount / sender_ghost
            self.shadow[sender] -= moved
            self.shadow[recipient] = self.shadow.get(recipient, 0.0) + moved
        return True

    def try_convert(self, address: str, at: datetime) -> None:
        ghost_before = self.ledger.account(address).ghost
        result = self.ledger.convert(address, at)
        legit = self.groups.get(address) == "legit"
        if result.amount:
            if self.alerted_at is None and self.shadow.get(address):
                leaked = self.shadow[address] * result.amount / ghost_before
                self.shadow[address] -= leaked
                self.leaked_before_alert += leaked
            self.events.append(
                GhostTokenRedemptionEvent(
                    tx_hash=self.new_tx(),
                    log_index=next(self._log),
                    block_number=self.block(at),
                    chain_id=FUJI_CHAIN_ID,
                    redeemed_at=at,
                    holder=address,
                    ghost_amount=result.amount,
                    token_amount=result.amount,
                    fee_amount=0,
                    contamination_ratio=result.ratio,
                )
            )
            self.legit_conversions += legit
        elif legit and result.blocked_reason != "aucune tranche echue":
            self.legit_blocked += 1

    def publish(self, address: str, at: datetime, level: BeaconRiskLevel) -> None:
        account = self.ledger.account(address)
        self.published[address] = account.ratio
        self.events.append(
            RiskBeaconUpdate(
                beacon_id=f"beacon-{len(self.published):04d}-{next(self._log)}",
                address=address,
                risk_level=level,
                contamination_ratio=account.ratio,
                suspect_amount=int(account.suspect),
                published_at=at,
                window_expires_at=account.delayed_until,
                chain_id=FUJI_CHAIN_ID,
            )
        )

    def raise_alert(self, at: datetime) -> None:
        """Seme le soupcon reconstitue, retarde et publie les adresses semees (§3, §9)."""
        self.alerted_at = at
        until = at + timedelta(minutes=self.p.extended_window_minutes)
        for address, suspect in sorted(self.shadow.items()):
            if suspect <= 0:
                continue
            self.ledger.mark_suspect(address, suspect)
            self.ledger.delay(address, until)
            self.publish(address, at, BeaconRiskLevel.ELEVATED)

    def confirm_destroy(self, at: datetime) -> None:
        """Multisig 2/3 : destruction de la fraction suspecte de chaque adresse contaminee."""
        decision_id = "rd-0001"
        for address in sorted(self.ledger.accounts):
            account = self.ledger.account(address)
            ratio, suspect = account.ratio, int(account.suspect)
            if ratio <= 0:
                continue
            burned = self.ledger.burn_suspect(address)
            self.ledger.lift_delay(address)
            if burned:
                self.burned_by_group[self.groups.get(address, "other")] += burned
                self.events.append(
                    GhostTokenBurnEvent(
                        tx_hash=self.new_tx(),
                        log_index=next(self._log),
                        block_number=self.block(at),
                        chain_id=FUJI_CHAIN_ID,
                        burned_at=at,
                        address=address,
                        burned_amount=burned,
                        contamination_ratio=ratio,
                        suspect_amount=suspect,
                        decision_id=decision_id,
                    )
                )
            self.publish(address, at, BeaconRiskLevel.FROZEN)

    # --- trafic legitime
    def plan_legit_traffic(self) -> None:
        minutes = 0.0
        rate = self.p.legit_ticks_per_minute
        while rate > 0:
            minutes += self.rng.expovariate(rate)
            if minutes >= self.p.duration_minutes:
                break
            self.schedule(self.p.minutes(minutes), self._legit_tick)

    def _legit_tick(self, at: datetime) -> None:
        sender, recipient = self.rng.sample(self.users, 2)
        account = self.ledger.account(sender)
        available = account.real or account.ghost
        if available:
            self.spend(sender, recipient, max(1, int(available * self.rng.uniform(0.01, 0.1))), at)
        self.try_convert(self.rng.choice(self.users), at)

    def plan_attack(self) -> None:
        p = self.p
        self.schedule(p.t0, self.fraud_mint)
        self.schedule(p.minutes(p.attack_at_minutes + p.detect_after_minutes), self.raise_alert)
        self.schedule(p.minutes(p.attack_at_minutes + p.confirm_after_minutes), self.confirm_destroy)

    def final_conversions(self) -> None:
        end = self.p.minutes(self.p.duration_minutes)
        for address in sorted(self.ledger.accounts):
            if self.groups.get(address) != "attacker":
                self.schedule(end, lambda at, a=address: self.try_convert(a, at))

    # --- mesures
    def holdings(self, group: str) -> int:
        return sum(
            a.real + a.ghost for addr, a in self.ledger.accounts.items() if self.groups.get(addr) == group
        )

    def common_results(self) -> dict[str, Any]:
        first_maturity = self.ledger.maturity_for(self.p.t0)
        margin = None
        if self.alerted_at is not None and self.ledger.params.ghost_enabled:
            margin = (first_maturity - self.alerted_at).total_seconds()
        return {
            "protocol_deficit": self.ledger.deficit,
            "reserve": self.ledger.reserve,
            "burned_total": self.ledger.burned_total,
            "burned_by_group": dict(self.burned_by_group),
            "suspect_escaped_by_conversion": int(self.ledger.converted_suspect),
            "suspect_leaked_before_alert": int(self.leaked_before_alert),
            "legit_conversions": self.legit_conversions,
            "legit_conversions_blocked": self.legit_blocked,
            "alert_at": self.alerted_at.isoformat() if self.alerted_at else None,
            "margin_before_conversion_seconds": margin,
        }


def _usdc(tokens: int, price: float) -> int:
    return int(tokens * price)


def _manifest(name: str, p: ContagionParams, world: _World, results: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario": name,
        "fictive_data": True,
        "params": p.to_json(),
        "chain_id": FUJI_CHAIN_ID,
        "counts": dict(Counter(type(e).__name__ for e in world.events)),
        "attack": {
            "kind": "unbacked_mint",
            "started_at": world.p.t0.isoformat(),
            "attacker": world.attacker,
            "minted": world.p.attack_amount_tokens * UNIT,
        },
        "results": results,
        "results_note": "mesure sur simulation hors chaine, parametres a calibrer",
    }


def _sorted_events(world: _World) -> list[Any]:
    def key(e: Any) -> datetime:
        for attr in ("observed_at", "minted_at", "redeemed_at", "burned_at", "published_at"):
            if hasattr(e, attr):
                return getattr(e, attr)
        raise TypeError(type(e))

    return sorted(world.events, key=key)  # tri stable : ordre d'emission conserve a egalite


# ------------------------------------------------------------------- scenario D


def _scenario_d(p: ContagionParams, variant: str) -> GeneratedScenario:
    ledger = replace(p.ledger, window=timedelta(0)) if variant == "no_ghost" else p.ledger
    world = _World(p, ledger)
    speculators = [world.new_address("speculator") for _ in range(p.speculators)]
    world.groups[POOL] = "pool"
    paid_by: Counter[str] = Counter()
    claims: list[_Claim] = []
    chunk = p.attack_amount_tokens * UNIT // p.sales
    offsets = sorted(world.rng.uniform(0.5, p.sell_span_minutes) for _ in range(p.sales))
    buyers = [world.rng.choice(speculators) for _ in range(p.sales)]
    resale_to = [world.rng.choice(world.users) for _ in range(p.sales)]
    resale_after = [world.rng.uniform(1, 4) for _ in range(p.sales)]

    def pay_claim(claim: _Claim, at: datetime) -> None:
        if world.ledger.is_delayed(claim.seller, at):  # §3 : pas de sortie pendant un retard
            world.schedule(world.ledger.account(claim.seller).delayed_until, lambda t: pay_claim(claim, t))  # type: ignore[arg-type]
            return
        claim.paid = claim.usdc - claim.cancelled
        world.usdc[POOL] -= claim.paid
        world.usdc[claim.seller] += claim.paid

    def sell(i: int, at: datetime) -> None:
        price_usdc = _usdc(chunk, p.ghost_price)
        if variant == "pool":
            ratio = world.ledger.account(world.attacker).ratio
            account = world.ledger.account(world.attacker)
            maturity = min(account.tranches) if account.tranches else at
            if world.spend(world.attacker, POOL, chunk, at):
                claim = _Claim(f"swap-{i:03d}", world.attacker, price_usdc, ratio, maturity)
                claims.append(claim)
                world.schedule(max(maturity, at), lambda t, c=claim: pay_claim(c, t))
            return
        buyer = buyers[i]
        if world.spend(world.attacker, buyer, chunk, at):
            world.usdc[buyer] -= price_usdc
            world.usdc[world.attacker] += price_usdc
            paid_by[buyer] += price_usdc
            world.schedule(at + timedelta(minutes=resale_after[i]), lambda t: resell(i, t))

    def resell(i: int, at: datetime) -> None:
        amount = int(chunk * p.resale_fraction)
        buyer, seller = resale_to[i], buyers[i]
        if amount and world.spend(seller, buyer, amount, at):
            price_usdc = _usdc(amount, p.ghost_price)
            world.usdc[buyer] -= price_usdc
            world.usdc[seller] += price_usdc
            paid_by[buyer] += price_usdc

    def cancel_claims(at: datetime) -> None:  # §10 : annulation a hauteur de ratio x montant
        for claim in claims:
            if claim.paid == 0:
                claim.cancelled = int(claim.ratio_at_swap * claim.usdc)

    world.plan_legit_traffic()
    world.plan_attack()
    for i, offset in enumerate(offsets):
        world.schedule(p.minutes(p.attack_at_minutes + offset), lambda t, i=i: sell(i, t))
    world.schedule(p.minutes(p.attack_at_minutes + p.confirm_after_minutes), cancel_claims)
    world.final_conversions()
    world.run()

    spec_paid = sum(paid_by[s] for s in speculators)
    spec_received = sum(world.usdc[s] for s in speculators) + spec_paid
    results = world.common_results()
    results.update(
        {
            "variant": variant,
            "attacker_usdc": world.usdc[world.attacker],
            "speculators_net_value": world.holdings("speculator") + spec_received - spec_paid,
            "legit_buyers_paid_usdc": sum(paid_by[u] for u in world.users),
            "pool_usdc_paid": -world.usdc[POOL],
            "pool_tokens_held": world.holdings("pool"),
            "claims": [asdict(c) | {"payable_at": c.payable_at.isoformat()} for c in claims],
        }
    )
    world.events = _sorted_events(world)
    return GeneratedScenario(f"scenario_d_{variant}", world.events, _manifest(f"D_{variant}", p, world, results))


def generate_scenario_d(params: ContagionParams | None = None) -> dict[str, GeneratedScenario]:
    """Scenario D : revente du Ghost frauduleux (`otc`, `pool`) vs baseline `no_ghost`."""
    params = params or ContagionParams()
    return {v: _scenario_d(params, v) for v in ("otc", "pool", "no_ghost")}


# ------------------------------------------------------------------- scenario C


@dataclass
class _Loan:
    borrower: str
    vault: str
    collateral: int
    debt: int
    attacker: bool
    taken_at: datetime


def _scenario_c(p: ContagionParams, with_beacon: bool) -> GeneratedScenario:
    world = _World(p, p.ledger)
    hops = [world.new_address("attacker") for _ in range(p.attacker_hops)]
    loans: list[_Loan] = []
    refused = {"attacker": 0, "legit": 0}
    borrow_at = [world.rng.uniform(1.5, p.borrow_span_minutes) for _ in hops]
    legit_borrowers = world.rng.sample(world.users, min(p.legit_borrowers, len(world.users)))
    legit_at = [world.rng.uniform(1, p.duration_minutes - 1) for _ in legit_borrowers]
    legit_share = [world.rng.uniform(0.1, 0.5) for _ in legit_borrowers]

    def split(at: datetime) -> None:
        share = p.attack_amount_tokens * UNIT // len(hops)
        for hop in hops:
            world.spend(world.attacker, hop, share, at)

    def borrow(borrower: str, amount: int, at: datetime, attacker: bool) -> None:
        if amount <= 0:
            return
        if with_beacon and world.published.get(borrower, 0.0) > p.beacon_ratio_threshold:
            refused["attacker" if attacker else "legit"] += 1
            return
        vault = world.new_address("vault")
        if world.spend(borrower, vault, amount, at):
            debt = _usdc(amount, p.ltv)
            loans.append(_Loan(borrower, vault, amount, debt, attacker, at))
            world.usdc[borrower] += debt

    world.plan_legit_traffic()
    world.plan_attack()
    world.schedule(p.minutes(p.attack_at_minutes + 1), split)
    for hop, offset in zip(hops, borrow_at):
        world.schedule(
            p.minutes(p.attack_at_minutes + offset),
            lambda t, h=hop: borrow(h, world.ledger.account(h).ghost, t, True),
        )
    for user, offset, share in zip(legit_borrowers, legit_at, legit_share):
        world.schedule(
            p.minutes(offset),
            lambda t, u=user, s=share: borrow(u, int(world.ledger.account(u).real * s), t, False),
        )
    world.final_conversions()
    world.run()

    bad_debt = 0
    defaults = 0
    for loan in loans:
        vault = world.ledger.account(loan.vault)
        value = vault.real + vault.ghost  # a parite
        if value < loan.debt:  # defaut rationnel : la garantie restante vaut moins que la dette
            bad_debt += loan.debt - value
            defaults += 1
    results = world.common_results()
    results.update(
        {
            "variant": "with_beacon" if with_beacon else "without_beacon",
            "bad_debt_usdc": bad_debt,
            "defaults": defaults,
            "loans_attacker": sum(l.attacker for l in loans),
            "loans_legit": sum(not l.attacker for l in loans),
            "refused_attacker": refused["attacker"],
            "refused_legit": refused["legit"],
            "lent_to_attacker_usdc": sum(l.debt for l in loans if l.attacker),
            "attacker_loans_before_alert": sum(
                l.attacker and world.alerted_at is not None and l.taken_at < world.alerted_at for l in loans
            ),
        }
    )
    name = "with_beacon" if with_beacon else "without_beacon"
    world.events = _sorted_events(world)
    return GeneratedScenario(f"scenario_c_{name}", world.events, _manifest(f"C_{name}", p, world, results))


def generate_scenario_c(params: ContagionParams | None = None) -> dict[str, GeneratedScenario]:
    """Scenario C : mauvaises creances d'un faux marche de pret, avec vs sans balise."""
    params = params or ContagionParams()
    return {
        "with_beacon": _scenario_c(params, True),
        "without_beacon": _scenario_c(params, False),
    }
