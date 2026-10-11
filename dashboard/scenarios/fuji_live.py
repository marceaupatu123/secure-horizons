"""Rejeu EN VRAI sur Avalanche Fuji (#148) : le schema de l'attaque Resolv, en transactions reelles.

Ce n'est PAS l'attaque Resolv elle-meme (elle a eu lieu sur Ethereum) : c'est son schema
(« la cle de service est volee, l'attaquant signe lui-meme un mint gonfle ») rejoue sur le
testnet Fuji (chain id 43113) avec les vrais contrats Foundry de `contracts/` :

  1. deploiement de `MockUSDC`, `VulnerableMinter` et `ProtectedMinter` (+ son `GhostToken`) ;
  2. contrat vulnerable : l'attaquant (cle SERVICE_ROLE volee) depose puis signe un mint gonfle
     x`multiplier` -> le contrat le credite ;
  3. contrat protege : meme tentative gonflee (rejetee on-chain), puis le seul appel possible
     « traiter la demande n°X » -> l'attaquant ne recoit que l'equivalent de son depot, en Ghost ;
  4. le `monitor` (vrai `ChainListener`) relit les mints sur la chaine ;
  5. reponse : la tentative de mint gonfle rejetee venant de la cle de service est le signal
     (REGLE DE DEMO du dashboard, pas un surveillant du module `detection`) ; le surveillant
     (`WATCHER_ROLE`) retarde le Ghost de l'attaquant, puis 2 gardiens sur 3 le detruisent.

Cle : `GUARDIAN_PRIVATE_KEY` (compte de TEST Fuji, `.env`, jamais journalisee). Les autres
roles (attaquant, surveillant, gardiens, gros porteur) sont des comptes de test DERIVES de cette
cle et approvisionnes en AVAX de test par elle. Le resultat (adresses, hash de transactions,
lectures on-chain) est public et sauvegarde en JSON pour la page de demo.

Lancer : `python -m dashboard.scenarios.fuji_live` (ecrit `dashboard/fuji_runs/latest.json`).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from dashboard.scenarios.real_contracts import CONTRACTS_DIR, DECIMALS_SCALE, RATE_ONE

LOGGER = logging.getLogger(__name__)

FUJI_CHAIN_ID = 43113
DEFAULT_RPC_URL = "https://api.avax-test.network/ext/bc/C/rpc"
EXPLORER_URL = "https://testnet.snowtrace.io"
KEY_ENV = "GUARDIAN_PRIVATE_KEY"
RPC_ENV = "FUJI_RPC_URL"
RUNS_DIR = Path(__file__).resolve().parents[1] / "fuji_runs"
LATEST_RUN_PATH = RUNS_DIR / "latest.json"

# Valeurs de DEMO, fictives (MockUSDC 6 decimales) : pas des mesures.
ATTACK_DEPOSIT = 1_000 * 10**6  # l'attaquant depose 1 000 USDC de test
ATTACK_MULTIPLIER = 1_000  # il signe un mint de 1 000 x son depot
# Offre de fond legitime : marge du budget de quarantaine (20 % de l'offre), sinon `delay` revert.
BACKGROUND_DEPOSIT = 10_000 * 10**6
# GhostConfig : FIXTURES de `contracts/test/utils/BaseTest.sol` (cf. real_contracts.py).
GHOST_CONFIG = (600, 60, 6, 2000, 0, 0, 0, 0, 0, 86400)
GHOST_W_SECONDS = 600
SUB_ACCOUNT_FUNDING_WEI = 10**16  # 0,01 AVAX de test par role
SUB_ACCOUNT_MIN_WEI = 5 * 10**15
FALLBACK_GAS = 600_000
RECEIPT_TIMEOUT_SECONDS = 180
ROLES = ("attacker", "watcher", "guardian1", "guardian2", "guardian3", "whale")
INFLATED_SIG = "completeSwap(uint256,address,uint256)"


class FujiLiveError(RuntimeError):
    """Le rejeu sur Fuji n'a pas pu aboutir (cle, RPC, transaction)."""


class TxRecord(BaseModel):
    """Une transaction reelle envoyee sur Fuji."""

    model_config = ConfigDict(extra="forbid")

    step: str
    actor: str
    label: str
    tx_hash: str
    block_number: int
    success: bool

    @property
    def url(self) -> str:
        """Lien Snowtrace testnet."""
        return f"{EXPLORER_URL}/tx/{self.tx_hash}"


class ObservedMint(BaseModel):
    """Mint relu sur la chaine par le vrai `monitor.ChainListener`."""

    model_config = ConfigDict(extra="forbid")

    token: str
    recipient: str
    amount: int
    tx_hash: str


class FujiRun(BaseModel):
    """Resultat complet d'un rejeu sur Fuji (donnees publiques uniquement : aucune cle)."""

    model_config = ConfigDict(extra="forbid")

    chain_id: int
    started_at: datetime
    finished_at: datetime
    accounts: dict[str, str]
    contracts: dict[str, str]
    transactions: list[TxRecord]
    deposit: int  # base units du stable (18 dec.)
    signed_amount: int  # montant signe par la cle volee (18 dec.)
    vulnerable_minted: int
    vulnerable_collateral: int
    protected_minted: int
    protected_collateral: int
    protected_inflated_rejected: bool
    attacker_ghost_before: int
    attacker_ghost_after: int
    observed_mints: list[ObservedMint]

    @property
    def vulnerable_loss(self) -> int:
        """Offre non adossee du contrat vulnerable (perte protocole)."""
        return max(0, self.vulnerable_minted - self.vulnerable_collateral)

    @property
    def protected_loss(self) -> int:
        """Offre non adossee du contrat protege."""
        return max(0, self.protected_minted - self.protected_collateral)


def address_url(address: str) -> str:
    """Lien Snowtrace testnet d'une adresse."""
    return f"{EXPLORER_URL}/address/{address}"


def load_artifact(name: str) -> dict[str, Any]:
    """ABI + bytecode de `contracts/out/<name>.sol/<name>.json` (faire `forge build` avant)."""
    path = CONTRACTS_DIR / "out" / f"{name}.sol" / f"{name}.json"
    if not path.is_file():
        raise FujiLiveError(f"artefact absent : {path.name} (lancer `forge build` dans contracts/)")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"abi": data["abi"], "bytecode": data["bytecode"]["object"]}


def derive_key(master_key: str, role: str) -> str:
    """Cle de test deterministe du role `role`, derivee de la cle maitre (testnet uniquement)."""
    from eth_utils import keccak

    seed = bytes.fromhex(master_key.removeprefix("0x")) + f"secure-horizons/demo/{role}".encode()
    return "0x" + keccak(seed).hex().removeprefix("0x")


def master_key_from_env() -> str:
    """Cle de test Fuji lue dans l'environnement / `.env` (FujiLiveError si absente)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(CONTRACTS_DIR.parent / ".env")
    except ImportError:  # pragma: no cover - python-dotenv est dans requirements.txt
        pass
    key = os.environ.get(KEY_ENV, "").strip()
    if not key or key.startswith("<"):
        raise FujiLiveError(f"{KEY_ENV} absente : renseigner un compte de TEST Fuji dans .env")
    return key


def key_available() -> bool:
    """Vrai si une cle de test Fuji est configuree (sans la renvoyer)."""
    try:
        master_key_from_env()
    except FujiLiveError:
        return False
    return True


class FujiRunner:
    """Envoie des transactions signees sur Fuji et journalise chacune (`TxRecord`)."""

    def __init__(self, web3: Any, master_key: str,
                 progress: Callable[[str], None] | None = None) -> None:
        from eth_account import Account

        self.w3 = web3
        if self.w3.eth.chain_id != FUJI_CHAIN_ID:
            raise FujiLiveError(f"chaîne inattendue {self.w3.eth.chain_id} (Fuji = 43113)")
        self.accounts = {"admin": Account.from_key(master_key)}
        for role in ROLES:
            self.accounts[role] = Account.from_key(derive_key(master_key, role))
        self.records: list[TxRecord] = []
        self._progress = progress or (lambda _msg: None)
        self._step = ""

    def address(self, role: str) -> str:
        """Adresse publique du role."""
        return str(self.accounts[role].address)

    def step(self, name: str) -> None:
        """Ouvre une etape (affichee et rattachee aux transactions suivantes)."""
        self._step = name
        self._progress(name)

    def _fees(self) -> dict[str, int]:
        base = int(self.w3.eth.get_block("latest").get("baseFeePerGas", 0))
        try:
            tip = max(int(self.w3.eth.max_priority_fee), 1)
        except Exception:  # noqa: BLE001 - certains noeuds n'exposent pas eth_maxPriorityFeePerGas
            tip = 10**9
        return {"maxPriorityFeePerGas": tip, "maxFeePerGas": 2 * base + tip}

    def _send(self, role: str, tx: dict[str, Any], label: str) -> Any:
        account = self.accounts[role]
        tx = {**tx, "from": account.address, "chainId": FUJI_CHAIN_ID,
              "nonce": self.w3.eth.get_transaction_count(account.address, "pending"), **self._fees()}
        signed = account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash,
                                                           timeout=RECEIPT_TIMEOUT_SECONDS)
        record = TxRecord(step=self._step, actor=role, label=label,
                          tx_hash="0x" + bytes(receipt["transactionHash"]).hex().removeprefix("0x"),
                          block_number=int(receipt["blockNumber"]),
                          success=int(receipt["status"]) == 1)
        self.records.append(record)
        self._progress(f"{'✔' if record.success else '✖'} {label}")
        return receipt

    def transact(self, role: str, fn: Any, label: str, expect_success: bool = True) -> bool:
        """Envoie l'appel `fn` ; une tentative qui revert est QUAND MEME diffusee (preuve)."""
        sender = self.accounts[role].address
        try:
            gas = int(fn.estimate_gas({"from": sender}) * 1.3) + 10_000
        except Exception:  # noqa: BLE001 - revert prevu : on le diffuse pour la trace on-chain
            gas = FALLBACK_GAS
        tx = fn.build_transaction({"from": sender, "gas": gas, "nonce": 0, "chainId": FUJI_CHAIN_ID,
                                   "maxFeePerGas": 0, "maxPriorityFeePerGas": 0})
        ok = int(self._send(role, {k: tx[k] for k in ("to", "data", "gas")}, label)["status"]) == 1
        if expect_success and not ok:
            raise FujiLiveError(f"transaction rejetée : {label}")
        return ok

    def transact_raw(self, role: str, to: str, data: str, label: str) -> bool:
        """Diffuse un appel brut (ex. selecteur absent du contrat) ; renvoie son statut on-chain."""
        receipt = self._send(role, {"to": to, "data": data, "gas": FALLBACK_GAS}, label)
        return int(receipt["status"]) == 1

    def deploy(self, name: str, label: str, *args: Any) -> Any:
        """Deploie `contracts/out/<name>` depuis l'admin ; renvoie le contrat web3."""
        artifact = load_artifact(name)
        factory = self.w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        data = factory.constructor(*args).data_in_transaction
        gas = int(self.w3.eth.estimate_gas({"from": self.address("admin"), "data": data}) * 1.2)
        receipt = self._send("admin", {"data": data, "gas": gas}, label)
        if int(receipt["status"]) != 1 or not receipt["contractAddress"]:
            raise FujiLiveError(f"déploiement échoué : {name}")
        return self.at(name, receipt["contractAddress"])

    def at(self, name: str, address: str) -> Any:
        """Contrat web3 `name` deja deploye a `address`."""
        return self.w3.eth.contract(address=self.w3.to_checksum_address(address),
                                    abi=load_artifact(name)["abi"])

    def fund_roles(self) -> None:
        """Approvisionne chaque role en AVAX de test depuis l'admin, si besoin."""
        for role in ROLES:
            address = self.accounts[role].address
            if self.w3.eth.get_balance(address) < SUB_ACCOUNT_MIN_WEI:
                self._send("admin", {"to": address, "value": SUB_ACCOUNT_FUNDING_WEI,
                                     "gas": 21_000}, f"AVAX de test pour le rôle {role}")


def _request(runner: FujiRunner, usdc: Any, minter: Any, who: str, amount: int) -> int:
    request_id = int(minter.functions.nextRequestId().call())
    runner.transact(who, usdc.functions.mint(runner.address(who), amount),
                    f"{who} reçoit {amount // 10**6} USDC de test")
    runner.transact(who, usdc.functions.approve(minter.address, amount), f"{who} autorise le dépôt")
    runner.transact(who, minter.functions.requestSwap(amount),
                    f"{who} dépose {amount // 10**6} USDC (demande n°{request_id})")
    return request_id


def observe_mints(web3: Any, token: str, from_block: int, to_block: int) -> list[ObservedMint]:
    """Mints de `token` relus par le VRAI `monitor.ChainListener` sur la plage de blocs."""
    from monitor.config import MonitorConfig
    from monitor.listener import ChainListener

    config = MonitorConfig(rpc_url=None, token_address=web3.to_checksum_address(token),
                           confirmations=0, start_block=from_block)
    events = ChainListener(config, web3=web3).fetch_mint_events(from_block, to_block)
    return [ObservedMint(token=token, recipient=str(e.recipient), amount=int(e.amount),
                         tx_hash=str(e.tx_hash)) for e in events]


def replay_on_fuji(web3: Any, master_key: str,
                   progress: Callable[[str], None] | None = None) -> FujiRun:
    """Rejoue le schema Resolv sur Fuji (voir docstring du module) ; ~30 transactions."""
    started = datetime.now(timezone.utc)
    runner = FujiRunner(web3, master_key, progress)
    first_block = int(web3.eth.block_number)
    signed = ATTACK_DEPOSIT * DECIMALS_SCALE * ATTACK_MULTIPLIER
    attacker = runner.address("attacker")
    guardians = [runner.address(f"guardian{i}") for i in (1, 2, 3)]

    runner.step("Préparation des comptes de test")
    runner.fund_roles()

    runner.step("Déploiement des contrats sur Fuji")
    usdc = runner.deploy("MockUSDC", "Déploiement du faux USDC de test")
    vulnerable = runner.deploy("VulnerableMinter", "Déploiement du contrat classique (vulnérable)",
                               usdc.address, runner.address("admin"), attacker)
    protected = runner.deploy("ProtectedMinter", "Déploiement du contrat Secure Horizons",
                              usdc.address, runner.address("admin"), attacker, RATE_ONE,
                              guardians, GHOST_CONFIG)
    ghost = runner.at("GhostToken", protected.functions.ghost().call())
    stable_v = runner.at("StableToken", vulnerable.functions.stable().call())
    runner.transact("admin", ghost.functions.grantRole(ghost.functions.WATCHER_ROLE().call(),
                                                       runner.address("watcher")),
                    "Le surveillant reçoit son rôle (il peut seulement retarder)")

    runner.step("Attaque n°1 : contrat classique")
    request_id = _request(runner, usdc, vulnerable, "attacker", ATTACK_DEPOSIT)
    runner.transact("attacker", vulnerable.get_function_by_signature(INFLATED_SIG)(
        request_id, attacker, signed), f"Clé volée : mint signé de {ATTACK_MULTIPLIER} × le dépôt")

    runner.step("Attaque n°2 : contrat Secure Horizons")
    whale = _request(runner, usdc, protected, "whale", BACKGROUND_DEPOSIT)
    runner.transact("attacker", protected.functions.completeSwap(whale),
                    "Un utilisateur honnête est servi normalement")
    request_id = _request(runner, usdc, protected, "attacker", ATTACK_DEPOSIT)
    inflated_data = vulnerable.encode_abi("completeSwap", args=[request_id, attacker, signed])
    inflated_ok = runner.transact_raw(
        "attacker", protected.address, inflated_data,
        f"Clé volée : même mint signé de {ATTACK_MULTIPLIER} × le dépôt (rejeté)")
    runner.transact("attacker", protected.functions.completeSwap(request_id),
                    "Seul appel possible : « traiter la demande n°X » (montant lu dans le coffre)")
    ghost_before = int(ghost.functions.balanceOf(attacker).call())

    runner.step("Réponse : le surveillant retarde, les humains détruisent")
    runner.transact("watcher", ghost.functions.delay([attacker], [ghost_before], GHOST_W_SECONDS),
                    "Le surveillant retarde le Ghost de l'attaquant")
    incident = int(ghost.functions.openIncidentId().call())
    runner.transact("guardian1", ghost.functions.proposeDestroy(incident, [attacker]),
                    "Gardien 1 propose la destruction")
    proposal = int(ghost.functions.proposalCount().call())
    runner.transact("guardian2", ghost.functions.approveAction(proposal),
                    "Gardien 2 valide : 2 sur 3, le Ghost suspect est détruit")
    ghost_after = int(ghost.functions.balanceOf(attacker).call())

    runner.step("Le monitor relit la chaîne")
    last_block = int(web3.eth.block_number)
    observed = (observe_mints(web3, stable_v.address, first_block, last_block)
                + observe_mints(web3, ghost.address, first_block, last_block))

    return FujiRun(
        chain_id=FUJI_CHAIN_ID, started_at=started, finished_at=datetime.now(timezone.utc),
        accounts={role: runner.address(role) for role in ("admin", *ROLES)},
        contracts={"MockUSDC": usdc.address, "VulnerableMinter": vulnerable.address,
                   "ProtectedMinter": protected.address, "GhostToken": ghost.address,
                   "StableToken (vulnérable)": stable_v.address},
        transactions=runner.records,
        deposit=ATTACK_DEPOSIT * DECIMALS_SCALE, signed_amount=signed,
        vulnerable_minted=int(stable_v.functions.totalSupply().call()),
        vulnerable_collateral=int(usdc.functions.balanceOf(vulnerable.address).call())
        * DECIMALS_SCALE,
        protected_minted=int(ghost.functions.supplyValue().call()),
        protected_collateral=int(usdc.functions.balanceOf(protected.address).call())
        * DECIMALS_SCALE,
        protected_inflated_rejected=not inflated_ok,
        attacker_ghost_before=ghost_before, attacker_ghost_after=ghost_after,
        observed_mints=observed,
    )


class LiveState(BaseModel):
    """Etat relu A L'INSTANT sur Fuji pour les contrats d'un rejeu (lecture seule)."""

    model_config = ConfigDict(extra="forbid")

    block_number: int
    vulnerable_minted: int
    vulnerable_collateral: int
    protected_minted: int
    protected_collateral: int
    attacker_ghost: int


def read_live_state(web3: Any, run: FujiRun) -> LiveState:
    """Relit sur Fuji (appels en lecture, aucune cle) l'etat des contrats de `run`."""
    def at(name: str, key: str) -> Any:
        return web3.eth.contract(address=web3.to_checksum_address(run.contracts[key]),
                                 abi=load_artifact(name)["abi"])

    usdc, ghost = at("MockUSDC", "MockUSDC"), at("GhostToken", "GhostToken")
    stable = at("StableToken", "StableToken (vulnérable)")
    attacker = web3.to_checksum_address(run.accounts["attacker"])
    return LiveState(
        block_number=int(web3.eth.block_number),
        vulnerable_minted=int(stable.functions.totalSupply().call()),
        vulnerable_collateral=int(usdc.functions.balanceOf(
            web3.to_checksum_address(run.contracts["VulnerableMinter"])).call()) * DECIMALS_SCALE,
        protected_minted=int(ghost.functions.supplyValue().call()),
        protected_collateral=int(usdc.functions.balanceOf(
            web3.to_checksum_address(run.contracts["ProtectedMinter"])).call()) * DECIMALS_SCALE,
        attacker_ghost=int(ghost.functions.balanceOf(attacker).call()),
    )


def connect(rpc_url: str | None = None) -> Any:
    """Client web3 sur Fuji (RPC publique par defaut)."""
    from web3 import Web3

    url = rpc_url or os.environ.get(RPC_ENV) or DEFAULT_RPC_URL
    return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))


def save_run(run: FujiRun, path: Path = LATEST_RUN_PATH) -> Path:
    """Ecrit le rejeu en JSON (donnees publiques uniquement)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run(path: Path = LATEST_RUN_PATH) -> FujiRun | None:
    """Dernier rejeu enregistre, ou None."""
    if not path.is_file():
        return None
    return FujiRun.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    """CLI : rejoue sur Fuji et enregistre `dashboard/fuji_runs/latest.json`."""
    run = replay_on_fuji(connect(), master_key_from_env(), progress=print)
    print(f"Rejeu enregistré : {save_run(run)} ({len(run.transactions)} transactions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
