"""Scenario C sur le VRAI M-Ghost (#8) + balise/marche de pret (#7), rejeu sur anvil (#110).

- Tests unitaires : une `FakeCChain` rejoue, SANS Foundry, la logique dont `replay_scenario_c`
  depend : le minter protege emet du Ghost frais (soupçon 0), le surveillant seme du soupçon qui
  SUIT la valeur au transfert (depot de garantie), la balise lit l'etat du Ghost, le faux marche
  refuse l'emprunt d'un compte non NORMAL et importe le soupçon au depot, la destruction 2/3
  brule le soupçon confirme detenu par le marche. Rapides.
- Test reel : rejeu sur anvil, saute proprement si Foundry ou `contracts/lib` manquent (CI du
  job par defaut).

Le test reel vit dans `test_scenarios_real.py` (`test_run_c_on_real_anvil`). Ici : la FakeChain.
"""

from __future__ import annotations

import pytest

from dashboard.scenarios import catalog, real_contracts
from dashboard.scenarios.config import DEFAULT_PARAMS
from dashboard.scenarios.models import REAL_LABEL, SIMULATION_LABEL
from dashboard.scenarios.registry import get_spec
from dashboard.scenarios.real_contracts import DECIMALS_SCALE, GHOST_W


def _addrs(arg: str) -> list[str]:
    return [a for a in arg.strip("[]").split(",") if a]


def _uints(arg: str) -> list[int]:
    return [int(a) for a in arg.strip("[]").split(",") if a]


class _GhostAcc:
    __slots__ = ("balance", "sc", "sp", "extended_until", "tagged_incident")

    def __init__(self) -> None:
        self.balance = 0
        self.sc = 0  # soupçon confirme
        self.sp = 0  # soupçon en attente
        self.extended_until = 0
        self.tagged_incident = 0


class FakeCChain:
    """Fausse chaine modelisant le vrai M-Ghost (#8) + `RiskBeacon` + `MockLendingMarket` (#7).

    Reproduit, sans Foundry, exactement ce dont `replay_scenario_c` depend :
    - le minter protege emet du Ghost frais (soupçon 0) a `completeSwap(id)` ;
    - le surveillant (`delay`) seme `Sp = min(montant, solde − Sc)` et pose une fenetre allongee ;
    - un transfert de Ghost deplace le soupçon au prorata (le soupçon suit la valeur) ;
    - la balise traduit l'etat du Ghost (RETARDE si fenetre allongee, DETRUIT apres destruction) ;
    - le marche importe le soupçon au depot (avec balise) et refuse l'emprunt d'un etat != NORMAL ;
    - la destruction 2/3 confirme l'incident (Sp -> Sc) puis brule le Sc des cibles.
    """

    BPS = 10_000
    WAD = 10**18

    def __init__(self) -> None:
        self.accounts = [f"0x{i:040x}" for i in range(1, 9)]
        self._next = 100
        self.time = 1_000_000
        # Ghost
        self._ghost_addr = ""
        self._minter = ""
        self._usdc = ""
        self._usdc_bal: dict[str, int] = {}
        self._g: dict[str, _GhostAcc] = {}
        self._pending: dict[int, tuple[str, int]] = {}
        self._next_request = 0
        self._open_incident = 0
        self._incident_confirmed: dict[int, bool] = {}
        self._destroyed_at: dict[str, int] = {}
        self._destroyed_incident: dict[str, int] = {}
        self._total_suspect_burned = 0
        self._proposals: dict[int, tuple[int, list[str]]] = {}
        self._proposal_count = 0
        # Marche / balise : config du dernier marche deploye
        self._beacon_ghost: dict[str, str] = {}  # beacon -> ghost
        self._markets: dict[str, dict] = {}  # market -> config + positions

    def __enter__(self) -> FakeCChain:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    # -- helpers --
    def _addr(self) -> str:
        self._next += 1
        return f"0x{self._next:040x}"

    def _acc(self, who: str) -> _GhostAcc:
        return self._g.setdefault(who, _GhostAcc())

    def _effective_suspect(self, who: str) -> int:
        acc = self._acc(who)
        sp = acc.sp
        if sp and not self._incident_confirmed.get(acc.tagged_incident):
            # Sp valide seulement si l'incident est confirme ou encore vivant (ici toujours vivant).
            pass
        return acc.sc + sp

    def _ratio(self, who: str) -> int:
        acc = self._acc(who)
        return 0 if acc.balance == 0 else self._effective_suspect(who) * self.WAD // acc.balance

    def _state(self, who: str) -> int:
        # 0 NORMAL, 1 RETARDE, 2 DETRUIT (pas de pause ici).
        acc = self._acc(who)
        if self._destroyed_at.get(who, 0) != 0:
            return 2
        if acc.extended_until != 0 and self.time < acc.extended_until:
            return 1
        return 0

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
            dst.tagged_incident = src.tagged_incident
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
            self._ghost_addr = self._addr()
        elif name == "RiskBeacon":
            self._beacon_ghost[address] = args[0]
        elif name == "MockLendingMarket":
            # args (apres sender): collateral(ghost), loan(usdc), ghost, beacon, scale, config
            cfg = args[5]
            fields = cfg.strip("()").split(",")
            use_beacon = fields[0] == "true"
            ltv_bps = int(fields[1])
            base_hc = int(fields[2])
            slope_hc = int(fields[3])
            max_ratio = int(fields[4])
            max_suspect = int(fields[5])
            self._markets[address] = {
                "use_beacon": use_beacon, "ltv_bps": ltv_bps, "base_hc": base_hc,
                "slope_hc": slope_hc, "max_ratio": max_ratio, "max_suspect": max_suspect,
                "scale": int(args[4]), "positions": {}, "total_debt": 0,
            }
        return address

    def send(self, sender: str, to: str, signature: str, *args: str) -> bool:
        if signature == "mint(address,uint256)":  # faucet MockUSDC OU liquidite marche
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
            self._acc(depositor).balance += deposit * DECIMALS_SCALE
            return True
        if signature == "delay(address[],uint256[],uint64)":
            return self._delay(_addrs(args[0]), _uints(args[1]), int(args[2]))
        if signature == "proposeDestroy(uint256,address[])":
            self._proposal_count += 1
            self._proposals[self._proposal_count] = (int(args[0]), _addrs(args[1]))
            return True
        if signature == "approveAction(uint256)":
            return self._approve(int(args[0]))
        # Marche
        if signature == "deposit(uint256)":
            return self._deposit(sender, to, int(args[0]))
        if signature == "borrow(uint256)":
            return self._borrow(sender, to, int(args[0]))
        return False

    def _delay(self, accounts: list[str], amounts: list[int], duration: int) -> bool:
        if self._open_incident == 0 or self._incident_confirmed.get(self._open_incident):
            self._open_incident += 1
            self._incident_confirmed[self._open_incident] = False
        incident = self._open_incident
        for who, amount in zip(accounts, amounts):
            acc = self._acc(who)
            acc.extended_until = max(acc.extended_until, self.time + duration)
            room = acc.balance - acc.sc
            want = min(amount, room)
            if want > acc.sp:
                acc.sp = want
            if acc.sp:
                acc.tagged_incident = incident
        return True

    def _approve(self, proposal_id: int) -> bool:
        incident, targets = self._proposals[proposal_id]
        self._incident_confirmed[incident] = True
        for who in targets:
            acc = self._acc(who)
            acc.sc += acc.sp  # Sp -> Sc a la confirmation
            acc.sp = 0
            burned = min(acc.sc, acc.balance)
            acc.sc -= burned
            acc.balance -= burned
            self._total_suspect_burned += burned
            self._destroyed_at[who] = self.time
            self._destroyed_incident[who] = incident
        return True

    def _deposit(self, who: str, market: str, amount: int) -> bool:
        m = self._markets[market]
        before = self._effective_suspect(market) if m["use_beacon"] else 0
        if not self._transfer_ghost(who, market, amount):
            return False
        imported = 0
        if m["use_beacon"]:
            imported = max(0, self._effective_suspect(market) - before)
        pos = m["positions"].setdefault(who, {"collateral": 0, "suspect": 0, "debt": 0})
        pos["collateral"] += amount
        pos["suspect"] += imported
        return True

    def _capacity(self, market: str, who: str) -> int:
        m = self._markets[market]
        pos = m["positions"].get(who, {"collateral": 0, "suspect": 0})
        coll = pos["collateral"]
        if not m["use_beacon"]:
            hc = m["base_hc"]
        else:
            ratio = 0 if coll == 0 else pos["suspect"] * self.WAD // coll
            hc = m["base_hc"] + m["slope_hc"] * ratio // self.WAD
            hc = min(hc, self.BPS)
        return coll * (self.BPS - hc) * m["ltv_bps"] // (self.BPS * self.BPS * m["scale"])

    def _borrow(self, who: str, market: str, amount: int) -> bool:
        m = self._markets[market]
        pos = m["positions"].get(who, {"collateral": 0, "suspect": 0, "debt": 0})
        if m["use_beacon"]:
            ratio = 0 if pos["collateral"] == 0 else pos["suspect"] * self.WAD // pos["collateral"]
            if (self._state(who) != 0 or ratio > m["max_ratio"]
                    or pos["suspect"] > m["max_suspect"]):
                return False
        new_debt = pos["debt"] + amount
        if new_debt > self._capacity(market, who):
            return False
        pos["debt"] = new_debt
        m["total_debt"] += amount
        return True

    # -- lecture --
    def call(self, to: str, signature: str, *args: str) -> str:
        if signature == "ghost()(address)":
            return self._ghost_addr
        if signature == "WATCHER_ROLE()(bytes32)":
            return "0x" + "11" * 32
        if signature == "nextRequestId()(uint256)":
            return str(self._next_request)
        if signature == "openIncidentId()(uint256)":
            return str(self._open_incident)
        if signature == "proposalCount()(uint256)":
            return str(self._proposal_count)
        if signature == "balanceOf(address)(uint256)":
            return str(self._acc(args[0]).balance)
        if signature == "capacityOf(address)(uint256)":
            return str(self._capacity(to, args[0]))
        if signature == "totalDebt()(uint256)":
            return str(self._markets[to]["total_debt"])
        raise AssertionError(f"call inattendu : {signature}")


# --- Tests unitaires (FakeChain) ---------------------------------------------


def test_replay_c_reads_beacon_reduces_bad_debt() -> None:
    readings = real_contracts.replay_scenario_c(FakeCChain(), DEFAULT_PARAMS.lending_ltv,
                                                DEFAULT_PARAMS.beacon_ratio_threshold)
    without, with_beacon = readings["without_beacon"], readings["with_beacon"]
    # Sans balise : l'attaquant emprunte, sa garantie suspecte est detruite -> mauvaise creance.
    assert without.bad_debt > 0
    assert without.attacker_borrowed > 0
    # Avec balise : l'attaquant (RETARDE, 100 % suspect) est refuse -> aucune mauvaise creance.
    assert with_beacon.bad_debt == 0
    assert with_beacon.attacker_borrowed == 0
    # Le legitime n'est jamais refuse.
    assert with_beacon.legit_loans_refused == 0
    assert without.legit_loans_refused == 0


def test_run_c_anvil_all_real_no_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)
    result = catalog.run_c(20, DEFAULT_PARAMS, chain_factory=FakeCChain)
    # Tout vient de la chaine : plus rien de simule, bandeau sans « simulation hors chaîne ».
    assert result.simulated is False and result.replace_by == []
    sources = {m.source for v in result.variants for m in v.metrics}
    assert sources == {f"{REAL_LABEL} (#7, #8)"}
    assert SIMULATION_LABEL not in get_spec("C").result_banner(result)
    assert result.metric("with_beacon", "bad_debt").value == 0
    assert result.metric("without_beacon", "bad_debt").value > 0
    assert all(c.passed for v in result.variants for c in v.checks)


def test_run_c_falls_back_to_simulation_when_anvil_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)

    def broken() -> FakeCChain:
        raise real_contracts.ContractsBackendError("anvil n'a pas démarré")

    result = catalog.run_c(20, DEFAULT_PARAMS, chain_factory=broken)
    assert result.simulated is True and "repli" in result.message
    assert {m.source for v in result.variants for m in v.metrics} == {SIMULATION_LABEL}


def test_default_backend_leaves_c_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(real_contracts.CONTRACTS_BACKEND_ENV, raising=False)
    result = catalog.run_c(20, DEFAULT_PARAMS)
    assert result.simulated is True
    assert 7 in result.replace_by and 25 in result.replace_by


# --- Test reel (anvil) : nomme pour la selection -k "real_anvil" -------------


@pytest.mark.skipif(real_contracts.unavailable_reason() is not None,
                    reason="Foundry (forge/anvil/cast) ou contracts/lib absents")
def test_replay_c_on_real_anvil() -> None:
    """Rejeu reel sur anvil : sans balise, mauvaise creance > 0 ; avec balise, 0 (attaquant
    refuse), aucun emprunt legitime refuse."""
    with real_contracts.AnvilChain() as chain:
        readings = real_contracts.replay_scenario_c(chain, DEFAULT_PARAMS.lending_ltv,
                                                    DEFAULT_PARAMS.beacon_ratio_threshold)
    assert readings["without_beacon"].bad_debt > 0
    assert readings["with_beacon"].bad_debt == 0
    assert readings["with_beacon"].attacker_borrowed == 0
    assert readings["with_beacon"].legit_loans_refused == 0
    _ = GHOST_W  # fixture utilisee par le rejeu
