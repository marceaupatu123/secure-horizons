"""Scenario D sur les VRAIS contrats : M-Ghost (#8) + couche de reglement §10bis (#84), rejeu
anvil (#110).

- Tests unitaires : une `FakeDChain` rejoue, SANS Foundry, la logique dont `replay_scenario_d`
  depend (cas §10bis 2bis) : emission du M' frauduleux, soupçon qui suit la valeur, achat protege
  (actif bloque au coffre + Ghost de paiement au vendeur), revente pure plus chere, destruction
  2/3 du M', brulage du Ghost de paiement du voleur, restitution par racine de Merkle. Rapides.
- Test reel : rejeu sur anvil, nomme `real_anvil`, saute proprement si Foundry ou `contracts/lib`
  manquent.
"""

from __future__ import annotations

import pytest

from dashboard.scenarios import catalog, real_contracts, real_settlement
from dashboard.scenarios.config import DEFAULT_PARAMS
from dashboard.scenarios.models import REAL_LABEL, SIMULATION_LABEL
from dashboard.scenarios.registry import get_spec
from dashboard.scenarios.real_contracts import DECIMALS_SCALE
from dashboard.scenarios.real_settlement import (
    D_A2_PRICE,
    D_A40_PRICE,
    D_THIEF_DEPOSIT,
    SettlementReading,
    replay_scenario_d,
)


def _addrs(arg: str) -> list[str]:
    return [a for a in arg.strip("[]").split(",") if a]


def _uints(arg: str) -> list[int]:
    return [int(a) for a in arg.strip("[]").split(",") if a]


class _GAcc:
    __slots__ = ("balance", "sc", "sp", "tagged")

    def __init__(self) -> None:
        self.balance = 0
        self.sc = 0
        self.sp = 0
        self.tagged = 0


class FakeDChain:
    """Fausse chaine : vrai M-Ghost (#8) + `SettlementRouter`/`AssetVault`/`AssetGhost` (§10bis).

    Modelise exactement ce dont `replay_scenario_d` depend (cas 2bis) : le soupçon suit la valeur
    du M', le routeur bloque l'actif au coffre et emet le Ghost de paiement au vendeur, la revente
    pure transmet le soupçon, la destruction 2/3 brule le M' confirme, le coffre brule le Ghost de
    paiement de la graine puis restitue l'argent LIBÉRÉ par racine de Merkle.
    """

    def __init__(self) -> None:
        self.accounts = [f"0x{i:040x}" for i in range(1, 9)]
        self._next = 100
        # Ghost (M')
        self._ghost = ""
        self._underlying = ""
        self._minter = ""
        self._usdc = ""
        self._usdc_bal: dict[str, int] = {}
        self._m: dict[str, int] = {}  # vrai M (reste a 0 : aucun suspect ne convertit)
        self._g: dict[str, _GAcc] = {}
        self._pending: dict[int, tuple[str, int]] = {}
        self._next_request = 0
        self._open_incident = 0
        self._confirmed: dict[int, bool] = {}
        self._total_suspect_burned = 0
        self._proposals: dict[int, tuple[int, list[str]]] = {}
        self._proposal_count = 0
        # Reglement
        self._router = ""
        self._vault = ""
        self._pay = ""  # AssetGhost
        self._vault_of: dict[str, str] = {}
        self._pay_bal: dict[str, int] = {}  # Ghost de paiement
        self._locked = 0
        self._total_restituted = 0
        self._restitution_root = ""
        self._claimed: dict[int, bool] = {}
        self._vault_voters: dict[tuple, set] = {}
        self._vault_executed: dict[tuple, bool] = {}

    def __enter__(self) -> FakeDChain:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def _addr(self) -> str:
        self._next += 1
        return f"0x{self._next:040x}"

    def _acc(self, who: str) -> _GAcc:
        return self._g.setdefault(who, _GAcc())

    def settlement_leaf(self, to: str, amount: int, nonce: int) -> str:
        # Feuille deterministe locale (la vraie chaine la calcule par keccak/abi via cast).
        return f"leaf:{to}:{amount}:{nonce}"

    def _transfer_ghost(self, frm: str, to: str, value: int) -> bool:
        src = self._acc(frm)
        if src.balance < value or value == 0:
            return False
        dst = self._acc(to)
        total = src.balance
        s = src.sc + src.sp
        moved = min(s, -(-value * s // total)) if total else 0
        moved_c = min(src.sc, -(-value * src.sc // total)) if total else 0
        moved_p = moved - moved_c
        src.sc -= moved_c
        src.sp -= moved_p
        dst.sc += moved_c
        dst.sp += moved_p
        if moved_p:
            dst.tagged = src.tagged
        src.balance -= value
        dst.balance += value
        return True

    # -- ecriture --
    def deploy(self, contract: str, sender: str, *args: str) -> str:
        name = contract.split(":")[-1]
        address = self._addr()
        if name == "MockUSDC":
            self._usdc = address
        elif name == "ProtectedMinter":
            self._minter = address
            self._ghost = self._addr()
            self._underlying = self._addr()
        elif name == "SettlementRouter":
            self._router = address
        return address

    def send(self, sender: str, to: str, signature: str, *args: str) -> bool:
        if signature == "mint(address,uint256)":
            self._usdc_bal[args[0]] = self._usdc_bal.get(args[0], 0) + int(args[1])
            return True
        if signature in ("approve(address,uint256)",) or signature.startswith("grantRole"):
            return True
        if signature == "transfer(address,uint256)" and to == self._usdc:
            amt = int(args[1])
            if self._usdc_bal.get(sender, 0) < amt:
                return False
            self._usdc_bal[sender] -= amt
            self._usdc_bal[args[0]] = self._usdc_bal.get(args[0], 0) + amt
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
            self._acc(depositor).balance += deposit * DECIMALS_SCALE
            return True
        if signature == "delay(address[],uint256[],uint64)":
            return self._delay(_addrs(args[0]), _uints(args[1]))
        if signature == "proposeDestroy(uint256,address[])":
            self._proposal_count += 1
            self._proposals[self._proposal_count] = (int(args[0]), _addrs(args[1]))
            return True
        if signature == "approveAction(uint256)":
            return self._approve(int(args[0]))
        # routeur
        if signature == "buyWithAsset(address,uint256,address,uint256)":
            return self._buy(sender, args[0], int(args[1]), args[2], int(args[3]))
        if signature == "sellPure(address,uint256,address,uint256)":
            return self._sell_pure(sender, args[0], int(args[1]))
        # coffre
        if signature == "burnSeedPayment(address,uint256,uint256)":
            return self._vault_vote(("BURN", args[0], args[1], args[2]), sender,
                                    lambda: self._burn_seed(args[0], int(args[1])))
        if signature == "confirmRestitutionRoot(bytes32)":
            return self._vault_vote(("ROOT", args[0]), sender,
                                    lambda: self._set_root(args[0]))
        if signature == "restitute(address,uint256,uint256,bytes32[])":
            return self._restitute(args[0], int(args[1]), int(args[2]))
        return False

    def _vault_vote(self, action: tuple, sender: str, effect) -> bool:
        """Quorum 2/3 generique du coffre : l'effet n'a lieu qu'a la 2e approbation DISTINCTE."""
        if self._vault_executed.get(action):
            return False  # ActionAlreadyExecuted
        voters = self._vault_voters.setdefault(action, set())
        if sender in voters:
            return False  # ActionAlreadyApproved
        voters.add(sender)
        if len(voters) >= 2:
            self._vault_executed[action] = True
            return effect()
        return True

    def _delay(self, accounts: list[str], amounts: list[int]) -> bool:
        if self._open_incident == 0 or self._confirmed.get(self._open_incident):
            self._open_incident += 1
            self._confirmed[self._open_incident] = False
        for who, amount in zip(accounts, amounts):
            acc = self._acc(who)
            room = acc.balance - acc.sc
            want = min(amount, room)
            if want > acc.sp:
                acc.sp = want
            if acc.sp:
                acc.tagged = self._open_incident
        return True

    def _approve(self, proposal_id: int) -> bool:
        incident, targets = self._proposals[proposal_id]
        self._confirmed[incident] = True
        for who in targets:
            acc = self._acc(who)
            acc.sc += acc.sp
            acc.sp = 0
            burned = min(acc.sc, acc.balance)
            acc.sc -= burned
            acc.balance -= burned
            self._total_suspect_burned += burned
        return True

    def _ensure_vault(self) -> str:
        if not self._vault:
            self._vault = self._addr()
            self._pay = self._addr()
            self._vault_of[self._usdc] = self._vault
        return self._vault

    def _buy(self, buyer: str, seller: str, mamount: int, asset: str, aamount: int) -> bool:
        if self._usdc_bal.get(buyer, 0) < aamount:
            return False
        self._ensure_vault()
        # l'acheteur bloque l'actif au coffre
        self._usdc_bal[buyer] -= aamount
        self._locked += aamount
        self._pay_bal[seller] = self._pay_bal.get(seller, 0) + aamount  # Ghost de paiement au vendeur
        # le M' passe du vendeur a l'acheteur (soupçon suit)
        return self._transfer_ghost(seller, buyer, mamount)

    def _sell_pure(self, buyer: str, seller: str, mamount: int) -> bool:
        return self._transfer_ghost(seller, buyer, mamount)

    def _burn_seed(self, seed: str, amount: int) -> bool:
        bal = self._pay_bal.get(seed, 0)
        if bal < amount:
            return False
        self._pay_bal[seed] = bal - amount  # libere l'argent bloque (locked - offre restante)
        return True

    def _set_root(self, root: str) -> bool:
        self._restitution_root = root
        return True

    def _restitute(self, to: str, amount: int, nonce: int) -> bool:
        if self._claimed.get(nonce):
            return False
        if self._restitution_root != self.settlement_leaf(to, amount, nonce):
            return False
        outstanding = sum(self._pay_bal.values())
        available = self._locked - outstanding
        if amount > available:
            return False
        self._claimed[nonce] = True
        self._locked -= amount
        self._total_restituted += amount
        self._usdc_bal[to] = self._usdc_bal.get(to, 0) + amount
        return True

    # -- lecture --
    def call(self, to: str, signature: str, *args: str) -> str:
        if signature == "ghost()(address)":
            return self._ghost
        if signature == "underlying()(address)":
            return self._underlying
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
            if to == self._usdc:
                return str(self._usdc_bal.get(args[0], 0))
            if to == self._underlying:
                return str(self._m.get(args[0], 0))
            return str(self._acc(args[0]).balance)
        if signature == "vaultOf(address)(address)":
            return self._vault_of.get(args[0], "0x" + "0" * 40)
        if signature == "assetGhost()(address)":
            return self._pay
        if signature == "locked()(uint256)":
            return str(self._locked)
        if signature == "totalRestituted()(uint256)":
            return str(self._total_restituted)
        raise AssertionError(f"call inattendu : {signature}")


# --- Tests unitaires (FakeChain) ---------------------------------------------


def test_replay_d_thief_zero_protocol_zero_speculator_bears_markup() -> None:
    reading = replay_scenario_d(FakeDChain())
    assert isinstance(reading, SettlementReading)
    # Le M' frauduleux est detruit (10e18).
    assert reading.mprime_destroyed == D_THIEF_DEPOSIT * DECIMALS_SCALE
    # Le voleur ne garde rien (il n'a reçu que du Ghost de paiement, brulé).
    assert reading.thief_asset_kept == 0
    # Le protocole ne garde rien : aucun vrai M n'a été émis contre le suspect.
    assert reading.protocol_loss == 0
    # L'intermediaire garde son prix de vente (15), l'acheteur final est restitué des 10 bloqués.
    assert reading.intermediary_asset == D_A40_PRICE
    assert reading.last_holder_restituted == D_A2_PRICE
    # Le spéculateur (acheteur final) porte la marge : payé 15, récupéré 10 -> perte 5.
    assert reading.speculator_loss == D_A40_PRICE - D_A2_PRICE
    # Le coffre est vidé.
    assert reading.vault_locked_end == 0


def test_run_d_anvil_all_real_no_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)
    result = catalog.run_d(20, DEFAULT_PARAMS, chain_factory=FakeDChain)
    assert result.simulated is False and result.replace_by == []
    sources = {m.source for v in result.variants for m in v.metrics}
    assert sources == {f"{REAL_LABEL} (#8, #84)"}
    assert SIMULATION_LABEL not in get_spec("D").result_banner(result)
    assert result.metric("main", "protocol_loss").value == 0
    assert result.metric("main", "speculator_loss").value > 0
    assert result.metric("main", "thief_asset_kept").value == 0
    assert all(c.passed for v in result.variants for c in v.checks)


def test_run_d_falls_back_to_simulation_when_anvil_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)

    def broken() -> FakeDChain:
        raise real_contracts.ContractsBackendError("anvil n'a pas démarré")

    result = catalog.run_d(20, DEFAULT_PARAMS, chain_factory=broken)
    assert result.simulated is True and "repli" in result.message
    assert {m.source for v in result.variants for m in v.metrics} == {SIMULATION_LABEL}
    # La variante simulee (pool a produit constant) est conservee telle quelle.
    assert result.metric("main", "protocol_loss").value == 0


def test_default_backend_leaves_d_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(real_contracts.CONTRACTS_BACKEND_ENV, raising=False)
    result = catalog.run_d(20, DEFAULT_PARAMS)
    assert result.simulated is True
    assert 8 in result.replace_by


# --- Test reel (anvil) : nomme pour la selection -k "real_anvil" -------------


@pytest.mark.skipif(real_contracts.unavailable_reason() is not None,
                    reason="Foundry (forge/anvil/cast) ou contracts/lib absents")
def test_replay_d_on_real_anvil() -> None:
    """Rejeu reel sur anvil : voleur a 0, perte protocole 0, marge portee par l'acheteur final,
    coffre vide."""
    with real_contracts.AnvilChain() as chain:
        reading = replay_scenario_d(chain)
    assert reading.mprime_destroyed > 0
    assert reading.thief_asset_kept == 0
    assert reading.protocol_loss == 0
    assert reading.speculator_loss == real_settlement.D_A40_PRICE - real_settlement.D_A2_PRICE
    assert reading.last_holder_restituted == real_settlement.D_A2_PRICE
    assert reading.vault_locked_end == 0
