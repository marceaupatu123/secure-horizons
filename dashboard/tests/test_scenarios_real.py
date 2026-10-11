"""Branchement des scenarios sur les vraies implementations (#70).

- A : adaptateur `real_contracts` teste contre une fausse chaine (meme protocole que
  `AnvilChain`), repli sur la simulation, et rejeu reel sur anvil quand Foundry est
  installe (test saute sinon, notamment en CI).
- B / N1-N3 : `real_pipeline` appelle les vrais surveillants #11/#12 et l'orchestrateur #17.
"""

from __future__ import annotations

import random

import pytest

from dashboard.demo_data import DEMO_REFERENCE_TIME, _Builder
from dashboard.scenarios import catalog, real_contracts
from dashboard.scenarios.config import DEFAULT_PARAMS
from dashboard.scenarios.models import REAL_LABEL, SIMULATION_LABEL
from dashboard.scenarios.real_contracts import (
    DECIMALS_SCALE,
    ContractsBackendError,
    last_json,
    parse_uint,
    replay_scenario_a,
)
from dashboard.scenarios.real_pipeline import generation_params, run_detectors
from data.generate import generate_normal


class FakeChain:
    """Fausse chaine : rejoue la logique des minters #4/#5 telle que decrite par leurs
    contrats (vulnerable : mint du montant signe ; protege : mint = depot x 1e12, l'appel
    a 3 arguments n'existe pas)."""

    def __init__(self) -> None:
        self.accounts = [f"0x{i:040x}" for i in range(1, 6)]
        self._next = 100
        self.kind: dict[str, str] = {}
        self.stable_of: dict[str, str] = {}
        self.supply: dict[str, int] = {}
        self.held: dict[str, int] = {}
        self.pending: dict[str, dict[int, int]] = {}

    def __enter__(self) -> FakeChain:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def _address(self) -> str:
        self._next += 1
        return f"0x{self._next:040x}"

    def deploy(self, contract: str, sender: str, *args: str) -> str:
        address = self._address()
        self.kind[address] = contract.split(":")[-1]
        if self.kind[address] in ("VulnerableMinter", "ProtectedMinter"):
            stable = self._address()
            self.stable_of[address] = stable
            self.supply[stable] = 0
            self.held[address] = 0
            self.pending[address] = {}
        return address

    def send(self, sender: str, to: str, signature: str, *args: str) -> bool:
        kind = self.kind.get(to)
        if signature.startswith(("mint(", "approve(")):
            return True
        if signature == "requestSwap(uint256)":
            request_id = len(self.pending[to])
            self.pending[to][request_id] = int(args[0])
            self.held[to] += int(args[0])
            return True
        if signature == "completeSwap(uint256,address,uint256)":
            if kind != "VulnerableMinter":
                return False  # selecteur absent du contrat protege : revert
            self.supply[self.stable_of[to]] += int(args[2])
            return True
        if signature == "completeSwap(uint256)" and kind == "ProtectedMinter":
            deposit = self.pending[to].pop(int(args[0]))
            self.supply[self.stable_of[to]] += deposit * DECIMALS_SCALE
            return True
        return False

    def call(self, to: str, signature: str, *args: str) -> str:
        if signature == "nextRequestId()(uint256)":
            return str(len(self.pending[to]))
        if signature == "stable()(address)":
            return self.stable_of[to]
        if signature == "totalSupply()(uint256)":
            return f"{self.supply[to]} [1e0]"
        if signature == "balanceOf(address)(uint256)":
            return str(self.held[args[0]])
        raise AssertionError(signature)


def test_parse_uint_and_last_json() -> None:
    assert parse_uint("1000000000000000000 [1e18]") == 10**18
    assert parse_uint("0x10") == 16
    with pytest.raises(ContractsBackendError):
        parse_uint("")
    assert last_json('log\n{"status": "0x1"}\n') == {"status": "0x1"}
    with pytest.raises(ContractsBackendError):
        last_json("pas de json")


def test_replay_reads_vulnerable_drained_protected_bounded() -> None:
    readings = replay_scenario_a(FakeChain(), deposit=1_000_000, multiplier=1_000)
    vulnerable, protected = readings["vulnerable"], readings["protected"]
    assert vulnerable.inflated_call_accepted is True
    assert vulnerable.unbacked == vulnerable.minted - vulnerable.collateral > 0
    assert protected.inflated_call_accepted is False
    assert protected.unbacked == 0
    assert protected.minted == 1_000_000 * DECIMALS_SCALE


def test_run_a_with_chain_uses_real_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)
    result = catalog.run_a(20, DEFAULT_PARAMS, chain_factory=FakeChain)
    assert result.simulated is False and result.replace_by == []
    sources = {m.source for v in result.variants for m in v.metrics}
    assert all(s.startswith(REAL_LABEL) for s in sources)
    assert result.metric("protected", "protocol_loss").value == 0
    assert all(c.passed for v in result.variants for c in v.checks)


def test_run_a_falls_back_to_simulation_when_anvil_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)

    def broken() -> FakeChain:
        raise ContractsBackendError("anvil n'a pas démarré")

    result = catalog.run_a(20, DEFAULT_PARAMS, chain_factory=broken)
    assert result.simulated is True
    assert "repli" in result.message and "anvil n'a pas démarré" in result.message
    assert {m.source for v in result.variants for m in v.metrics} == {SIMULATION_LABEL}


def test_default_backend_is_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(real_contracts.CONTRACTS_BACKEND_ENV, raising=False)
    assert real_contracts.selected_backend() == real_contracts.BACKEND_SIM
    assert catalog.run_a(20, DEFAULT_PARAMS).simulated is True


@pytest.mark.skipif(real_contracts.unavailable_reason() is not None,
                    reason="Foundry (forge/anvil/cast) ou contracts/lib absents")
def test_run_a_on_real_anvil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)
    result = catalog.run_a(20, DEFAULT_PARAMS)
    assert result.simulated is False, result.message
    assert result.metric("vulnerable", "protocol_loss").value > 0
    assert result.metric("protected", "protocol_loss").value == 0
    assert all(c.passed for v in result.variants for c in v.checks)


def test_run_detectors_on_generated_normal_traffic() -> None:
    gen = generation_params(20, DEFAULT_PARAMS)
    scenario = generate_normal(gen)
    builder = _Builder(random.Random(20), DEMO_REFERENCE_TIME)
    run = run_detectors(builder, scenario.events, scenario.manifest, DEFAULT_PARAMS)
    assert run.slots, "le surveillant #12 doit cloturer des tranches"
    assert run.alerts == []  # profil « petits transferts » : 0 faux positif (seed 20)


def test_run_c_falls_back_to_simulation_when_anvil_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)

    def broken() -> FakeChain:
        raise ContractsBackendError("anvil n'a pas démarré")

    result = catalog.run_c(20, DEFAULT_PARAMS, chain_factory=broken)
    assert result.simulated is True and "repli" in result.message
    assert {m.source for v in result.variants for m in v.metrics} == {SIMULATION_LABEL}


def test_market_config_tuple_matches_contract_struct() -> None:
    assert real_contracts._market_config(True, 0.5, 0.5) == (
        "(true,5000,500,9500,500000000000000000,1000000000000000000000)")


@pytest.mark.skipif(real_contracts.unavailable_reason() is not None,
                    reason="Foundry (forge/anvil/cast) ou contracts/lib absents")
def test_run_c_on_real_anvil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(real_contracts.CONTRACTS_BACKEND_ENV, real_contracts.BACKEND_ANVIL)
    result = catalog.run_c(20, DEFAULT_PARAMS)
    assert result.replace_by == [8], result.message  # seul le M-Ghost (#8) reste simule
    without = result.metric("without_beacon", "bad_debt").value
    with_beacon = result.metric("with_beacon", "bad_debt").value
    assert without is not None and without > 0
    assert with_beacon == 0
    assert result.metric("with_beacon", "legit_loans_refused").value == 0
    assert all(c.passed for v in result.variants for c in v.checks)
