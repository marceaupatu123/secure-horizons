"""Rejeu de la partie Ghost des scenarios B et N3 (#110) sur les vrais contrats #8.

- Tests unitaires : une `FakeChain` rejoue la logique du `GhostToken` / `ProtectedMinter` /
  `GuardianActions` (soupçon qui suit la valeur, retard borné par le budget, destruction 2/3,
  conversion 1:1 après W) telle que decrite par ces contrats. Rapides, sans Foundry.
- Test reel : rejeu sur une chaine anvil locale, saute proprement si Foundry (forge/anvil/cast)
  ou `contracts/lib` manquent (notamment en CI du job par defaut).
"""

from __future__ import annotations

import pytest

from dashboard.scenarios import catalog, real_contracts, real_ghost
from dashboard.scenarios.config import DEFAULT_PARAMS
from dashboard.scenarios.models import REAL_LABEL, SIMULATION_LABEL
from dashboard.scenarios.real_ghost import (
    DECIMALS_SCALE,
    GHOST_SLOT,
    GHOST_W,
    GhostReading,
    replay_scenario_b,
    replay_scenario_n3,
)


class _Account:
    __slots__ = ("balance", "sc", "sp", "matured_at", "extended_until", "counted_incident")

    def __init__(self) -> None:
        self.balance = 0  # Ghost detenu (18 dec.)
        self.sc = 0  # soupçon confirme
        self.sp = 0  # soupçon en attente
        self.matured_at = 0  # instant a partir duquel le lot est echu (echeance de maturite)
        self.extended_until = 0  # fin de fenetre allongee (retard du surveillant)
        self.counted_incident = 0  # incident ayant deja compte son solde (budget)


class FakeGhostChain:
    """Fausse chaine modelisant la machine a etats du M-Ghost (#8) utilisee par le rejeu.

    Elle reproduit, sans Foundry, les proprietes dont le rejeu depend : le soupçon suit la
    valeur transferee, le surveillant ne peut retarder que dans la limite du budget de
    quarantaine (20 %), la destruction 2/3 brule le soupçon confirme, et la conversion n'est
    possible qu'apres l'echeance ET hors fenetre allongee, la part suspecte restant verrouillee.
    """

    QUARANTINE_BPS = 2000
    BPS = 10_000

    def __init__(self) -> None:
        self.accounts = [f"0x{i:040x}" for i in range(1, 9)]
        self._next = 100
        self.time = 1_000_000
        # contrats
        self.minter = ""
        self.ghost = ""
        self.underlying = ""
        self.usdc = ""
        self._usdc_bal: dict[str, int] = {}
        self._ghost: dict[str, _Account] = {}
        self._m: dict[str, int] = {}  # soldes de M (GhostedStable)
        self._pending: dict[int, tuple[str, int]] = {}  # requestId -> (depositor, deposit 6 dec.)
        self._next_request = 0
        self._open_incident = 0
        self._incident_expiry: dict[int, int] = {}
        self._incident_confirmed: dict[int, bool] = {}
        self._incident_ext_balance: dict[int, int] = {}
        self._proposals: dict[int, tuple[int, list[str]]] = {}  # id -> (incidentId, targets)
        self._proposal_count = 0
        self._total_suspect_burned = 0
        self._total_issued = 0

    # -- contexte --
    def __enter__(self) -> FakeGhostChain:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def _addr(self) -> str:
        self._next += 1
        return f"0x{self._next:040x}"

    def _acc(self, who: str) -> _Account:
        return self._ghost.setdefault(who, _Account())

    def _supply_value(self) -> int:
        return sum(self._m.values()) + sum(a.balance for a in self._ghost.values())

    # -- horloge (helpers de real_ghost) --
    def advance_time(self, seconds: int) -> None:
        self.time += int(seconds)

    def block_timestamp(self) -> int:
        return self.time

    # -- deploiement / ecriture --
    def deploy(self, contract: str, sender: str, *args: str) -> str:
        name = contract.split(":")[-1]
        address = self._addr()
        if name == "MockUSDC":
            self.usdc = address
        elif name == "ProtectedMinter":
            self.minter = address
            self.ghost = self._addr()
            self.underlying = self._addr()
        return address

    def send(self, sender: str, to: str, signature: str, *args: str) -> bool:
        if signature == "mint(address,uint256)":  # faucet MockUSDC
            self._usdc_bal[args[0]] = self._usdc_bal.get(args[0], 0) + int(args[1])
            return True
        if signature == "approve(address,uint256)":
            return True
        if signature.startswith("grantRole"):
            return True
        if signature == "requestSwap(uint256)":
            deposit = int(args[0])
            if self._usdc_bal.get(sender, 0) < deposit:
                return False
            self._usdc_bal[sender] -= deposit
            self._pending[self._next_request] = (sender, deposit)
            self._next_request += 1
            return True
        if signature == "completeSwap(uint256)":
            depositor, deposit = self._pending.pop(int(args[0]))
            amount = deposit * DECIMALS_SCALE
            acc = self._acc(depositor)
            acc.balance += amount
            acc.matured_at = max(acc.matured_at, self.time + GHOST_W)
            self._total_issued += amount
            return True
        if signature == "transfer(address,uint256)":
            return self._transfer(sender, args[0], int(args[1]))
        if signature == "delay(address[],uint256[],uint64)":
            return self._delay(_addrs(args[0]), _uints(args[1]))
        if signature == "proposeDestroy(uint256,address[])":
            self._proposal_count += 1
            self._proposals[self._proposal_count] = (int(args[0]), _addrs(args[1]))
            return True
        if signature == "approveAction(uint256)":
            return self._approve_action(int(args[0]))
        if signature == "convert(uint256)":
            return self._convert(sender, int(args[0]))
        return False

    def _transfer(self, frm: str, to: str, value: int) -> bool:
        src = self._acc(frm)
        if src.balance < value or value == 0:
            return False
        dst = self._acc(to)
        total = src.balance
        moved_s = min(src.sc + src.sp, -(-value * (src.sc + src.sp) // total)) if total else 0
        moved_c = min(src.sc, -(-value * src.sc // total)) if total else 0
        moved_p = moved_s - moved_c
        src.sc -= moved_c
        src.sp -= moved_p
        dst.sc += moved_c
        dst.sp += moved_p
        src.balance -= value
        dst.balance += value
        dst.matured_at = max(dst.matured_at, self.time + GHOST_W)
        return True

    def _delay(self, accounts: list[str], amounts: list[int]) -> bool:
        incident = self._open_incident
        if (incident == 0 or self._incident_confirmed.get(incident)
                or self.time >= self._incident_expiry.get(incident, 0)):
            incident += 1
            self._open_incident = incident
            self._incident_expiry[incident] = self.time + GHOST_W
            self._incident_confirmed[incident] = False
            self._incident_ext_balance[incident] = 0
        end = self._incident_expiry[incident]
        for who, amount in zip(accounts, amounts):
            acc = self._acc(who)
            acc.extended_until = max(acc.extended_until, end)
            room = acc.balance - acc.sc
            want = min(amount, room)
            if want > acc.sp:
                acc.sp = want
            if acc.counted_incident != incident:
                acc.counted_incident = incident
                self._incident_ext_balance[incident] += acc.balance
        # Budget de quarantaine : tout le lot revert si depasse.
        if self._incident_ext_balance[incident] * self.BPS > self.QUARANTINE_BPS * self._supply_value():
            return False
        return True

    def _approve_action(self, proposal_id: int) -> bool:
        incident, targets = self._proposals[proposal_id]
        if self.time >= self._incident_expiry.get(incident, 0) and not self._incident_confirmed.get(incident):
            return False
        self._incident_confirmed[incident] = True
        for who in targets:
            acc = self._acc(who)
            # confirmation : Sp -> Sc, puis destruction du soupçon confirme.
            acc.sc += acc.sp
            acc.sp = 0
            burned = acc.sc
            acc.sc = 0
            acc.balance -= burned
            self._total_suspect_burned += burned
        return True

    def _convert(self, who: str, amount: int) -> bool:
        acc = self._acc(who)
        if amount == 0 or acc.balance == 0:
            return False
        if self.time < acc.matured_at or self.time < acc.extended_until:
            return False
        suspect = acc.sc + acc.sp
        # Seuils de conversion a 0 (fixture) : tout soupçon bloque ; sinon part suspecte verrouillee.
        if suspect > 0:
            return False
        if amount > acc.balance - suspect:
            return False
        acc.balance -= amount
        self._m[who] = self._m.get(who, 0) + amount  # marges a 0 : M = montant
        return True

    # -- lecture --
    def call(self, to: str, signature: str, *args: str) -> str:
        if signature == "ghost()(address)":
            return self.ghost
        if signature == "underlying()(address)":
            return self.underlying
        if signature == "WATCHER_ROLE()(bytes32)":
            return "0x" + "11" * 32
        if signature == "nextRequestId()(uint256)":
            return str(self._next_request)
        if signature == "openIncidentId()(uint256)":
            return str(self._open_incident)
        if signature == "proposalCount()(uint256)":
            return str(self._proposal_count)
        if signature == "totalSuspectBurned()(uint256)":
            return str(self._total_suspect_burned)
        if signature == "balanceOf(address)(uint256)":
            if to == self.underlying:
                return str(self._m.get(args[0], 0))
            return str(self._acc(args[0]).balance)
        if signature == "supplyValue()(uint256)":
            return str(self._supply_value())
        if signature == "reserve()(uint256)":
            return str(max(0, self._total_issued - self._supply_value()))
        if signature == "convertibleOf(address)(uint256)":
            acc = self._acc(args[0])
            if self.time < acc.extended_until or self.time < acc.matured_at:
                return "0"
            suspect = acc.sc + acc.sp
            return "0" if suspect > 0 else str(acc.balance - suspect)
        if signature.startswith("incidents(uint256)"):
            incident = int(args[0])
            exp = self._incident_expiry.get(incident, 0)
            return f"0 {exp} false 0"
        raise AssertionError(f"call inattendu : {signature}")


def _addrs(arg: str) -> list[str]:
    return [a for a in arg.strip("[]").split(",") if a]


def _uints(arg: str) -> list[int]:
    return [int(a) for a in arg.strip("[]").split(",") if a]


# --- Tests unitaires (FakeChain) ---------------------------------------------


def test_replay_b_destroys_suspect_blocks_attacker_frees_legit() -> None:
    reading = replay_scenario_b(FakeGhostChain())
    assert isinstance(reading, GhostReading)
    assert reading.destroy_confirmed is True
    # L'attaquant (100e18) a envoye 40e18 a un relais : 100e18 de suspect au total, tout detruit.
    assert reading.destroyed == 100 * 10**18
    assert reading.attacker_converted == 0  # soupçon detruit : rien a convertir
    assert reading.legit_converted == 100 * 10**18  # deux legitimes de 50e18
    # supplyValue baisse exactement du montant detruit.
    assert reading.supply_value_before - reading.supply_value_after == reading.destroyed
    assert reading.reserve == reading.destroyed  # le brule devient reserve de restitution


def test_replay_n3_no_destruction_legit_converts_after_return() -> None:
    reading = replay_scenario_n3(FakeGhostChain())
    assert reading.destroy_confirmed is False
    assert reading.destroyed == 0
    assert reading.attacker_converted == 0
    assert reading.legit_converted == 50 * 10**18  # le sink convertit apres le retour a la normale
    assert reading.supply_value_before == reading.supply_value_after  # rien detruit


def test_run_b_with_chain_uses_real_ghost_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)
    result = catalog.run_b(20, DEFAULT_PARAMS, chain_factory=FakeGhostChain)
    assert result.simulated is False and result.replace_by == []  # plus aucune brique simulee
    sources = {m.source for v in result.variants for m in v.metrics}
    assert any(s == f"{REAL_LABEL} (#8)" for s in sources)
    assert result.metric("main", "attacker_converted_onchain").value == 0
    assert result.metric("main", "ghost_destroyed_onchain").value > 0
    assert all(c.passed for v in result.variants for c in v.checks)


def test_run_n3_with_chain_uses_real_ghost_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)
    result = catalog.run_n3(20, DEFAULT_PARAMS, chain_factory=FakeGhostChain)
    assert result.simulated is False and result.replace_by == []
    assert result.metric("main", "ghost_destroyed_onchain").value == 0
    assert result.metric("main", "legit_converted_onchain").value > 0
    assert all(c.passed for v in result.variants for c in v.checks)


def test_run_b_falls_back_to_simulation_when_anvil_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)

    def broken() -> FakeGhostChain:
        raise real_contracts.ContractsBackendError("anvil n'a pas démarré")

    result = catalog.run_b(20, DEFAULT_PARAMS, chain_factory=broken)
    assert result.simulated is True
    assert 8 in result.replace_by  # le Ghost reste simule
    assert "repli" in result.message and "anvil n'a pas démarré" in result.message
    assert SIMULATION_LABEL in result.message


def test_default_backend_leaves_b_and_n3_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(real_contracts.CONTRACTS_BACKEND_ENV, raising=False)
    for runner in (catalog.run_b, catalog.run_n3):
        result = runner(20, DEFAULT_PARAMS)
        assert result.simulated is True
        assert 8 in result.replace_by


# --- Test reel (anvil) -------------------------------------------------------


@pytest.mark.skipif(real_contracts.unavailable_reason() is not None,
                    reason="Foundry (forge/anvil/cast) ou contracts/lib absents")
def test_replay_b_and_n3_on_real_anvil() -> None:
    """Rejeu reel sur anvil : destruction > 0, attaquant converti = 0, legitimes convertis
    apres W > 0, aucune conversion avant W (B) ; aucune destruction, conversion apres le
    retour a la normale (N3)."""
    with real_contracts.AnvilChain() as chain:
        b = replay_scenario_b(chain)
    assert b.destroy_confirmed is True
    assert b.destroyed > 0
    assert b.attacker_converted == 0
    assert b.legit_converted > 0
    assert b.supply_value_before - b.supply_value_after == b.destroyed

    with real_contracts.AnvilChain() as chain:
        n3 = replay_scenario_n3(chain)
    assert n3.destroy_confirmed is False
    assert n3.destroyed == 0
    assert n3.legit_converted > 0
    assert n3.supply_value_before == n3.supply_value_after


@pytest.mark.skipif(real_contracts.unavailable_reason() is not None,
                    reason="Foundry (forge/anvil/cast) ou contracts/lib absents")
def test_no_conversion_before_window_on_real_anvil() -> None:
    """Avant W, meme un lot propre n'est pas convertible (echeance de maturite non atteinte)."""
    with real_contracts.AnvilChain() as chain:
        usdc, minter, ghost, roles = real_ghost._deploy_world(chain)
        legit = roles["legit1"]
        real_ghost._fund(chain, usdc, legit, real_ghost.B_LEGIT_DEPOSIT)
        real_ghost._mint_ghost(chain, usdc, minter, legit, real_ghost.B_LEGIT_DEPOSIT)
        # Juste apres l'emission : rien n'est echu (W = 600 s non ecoule).
        convertible = real_contracts.parse_uint(
            chain.call(ghost, "convertibleOf(address)(uint256)", legit))
        assert convertible == 0
        # Apres W + un creneau : tout est convertible.
        real_ghost._increase_time(chain, GHOST_W + GHOST_SLOT)
        convertible_after = real_contracts.parse_uint(
            chain.call(ghost, "convertibleOf(address)(uint256)", legit))
        assert convertible_after == real_ghost.B_LEGIT_DEPOSIT * DECIMALS_SCALE
