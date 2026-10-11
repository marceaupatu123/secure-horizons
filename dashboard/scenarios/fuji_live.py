"""Rejeu EN VRAI sur Avalanche Fuji (#148), raconté en 3 cas, étape par étape.

Chaque cas est une suite d'ÉTAPES INTÉRESSANTES (`DemoStep`) : une commande de « terminal »,
le contrat touché, et l'effet obtenu, adossés à de vraies transactions Fuji (chain id 43113).
Les gestes d'intendance (dépôts de collatéral, approvisionnement en AVAX de test) sont joués mais
NON exposés comme étapes : on suppose que le collatéral existait déjà.

- **Cas « le mint passe »** : contrat classique vulnérable, la clé volée signe un mint gonflé qui
  est accepté → jetons créés sans réserve.
- **Cas « le mint est bloqué »** : notre `ProtectedMinter`, même mint gonflé rejeté on-chain, puis
  seul « traiter la demande n°X » possible → l'attaquant n'obtient que son dépôt, en Ghost.
- **Cas « un vendeur de Ghost pose problème »** : le vendeur écoule son Ghost via le
  `SettlementRouter` (l'acheteur paie en USDC, bloqué au coffre ; le vendeur reçoit du Ghost de
  paiement). On découvre un souci avec le vendeur (méthode NON divulguée) ; les gardiens 2/3
  détruisent tout le Ghost suspect en circulation et brûlent le Ghost de paiement du vendeur : son
  USDC, encore gelé au coffre faute de conversion, est restitué à l'acheteur honnête.

Cle : `GUARDIAN_PRIVATE_KEY` (compte de TEST Fuji, `.env`, jamais journalisée). Les autres rôles
sont des comptes de test DÉRIVÉS de cette clé et approvisionnés par elle. Résultat public (adresses,
hash, étapes) dans `dashboard/fuji_runs/latest.json`.

Lancer : `python -m dashboard.scenarios.fuji_live`.
"""

from __future__ import annotations

import json
import logging
import os
import time
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

# Valeurs de DEMO, fictives (MockUSDC 6 décimales) : pas des mesures.
ATTACK_DEPOSIT = 1_000 * 10**6  # dépôt réel de l'attaquant
ATTACK_MULTIPLIER = 1_000  # il signe un mint de 1 000 × son dépôt
SELL_AMOUNT_USDC = 1_000 * 10**6  # Ghost écoulé par le vendeur (cas 3), et prix payé par l'acheteur
BACKGROUND_DEPOSIT = 10_000 * 10**6  # offre de fond légitime (marge du budget de quarantaine)
GHOST_CONFIG = (600, 60, 6, 2000, 0, 0, 0, 0, 0, 86400)  # fixtures de contracts/test
# Fenêtre RACCOURCIE (1 s) pour montrer une conversion M-Ghost -> M-Coin en direct sur Fuji
# (la fenêtre de démo réelle est de 10 min, cf. demo_data.DEMO_NORMAL_WINDOW).
GHOST_CONFIG_FAST = (1, 1, 6, 2000, 0, 0, 0, 0, 0, 86400)
RECOVERY_DEPOSIT = 1_000 * 10**6  # dépôt d'un utilisateur honnête (cas « fenêtre de reprise »)
CONVERT_POLL_SECONDS = 3.0
CONVERT_POLL_TRIES = 8
GHOST_W_SECONDS = 600
SUB_ACCOUNT_FUNDING_WEI = 10**16  # 0,01 AVAX de test par rôle
SUB_ACCOUNT_MIN_WEI = 5 * 10**15
FALLBACK_GAS = 900_000
RECEIPT_TIMEOUT_SECONDS = 180
ROLES = ("attacker", "buyer", "spec1", "spec2", "spec3", "watcher",
         "guardian1", "guardian2", "guardian3", "whale")
INCIDENT_ACTORS = ("attacker", "buyer", "watcher", "guardian1", "guardian2", "guardian3")

CASE_MINT_PASSES = "mint-passe"
CASE_MINT_BLOCKED = "mint-bloque"
CASE_RECOVERY_WINDOW = "fenetre-reprise"
CASE_SPECULATIVE = "marche-speculatif"
CASE_GHOST_SELLER = "ghost-vendeur"
CASE_CONTAGION = "contagion"
# Prix (USDC, 6 déc.) des reventes successives du M-Ghost : volatils = spéculation.
SPEC_PRICES_USDC = (1_000 * 10**6, 1_300 * 10**6, 1_100 * 10**6)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
# Marché de prêt fictif (cf. real_contracts._market_config) : décotes PROVISOIRES de #7.
MARKET_LTV_BPS = 8000
MARKET_BASE_HAIRCUT_BPS = 500
MARKET_SLOPE_HAIRCUT_BPS = 9500
MARKET_MAX_BORROW_RATIO = 5 * 10**17  # 0,5 : seuil de ratio suspect (balise)
MARKET_MAX_BORROW_SUSPECT = 1_000 * 10**18
CONTAGION_LIQUIDITY = 100_000 * 10**6  # liquidité USDC du marché

ACTOR_LABELS = {
    "admin": "L'équipe",
    "protocole": "Automatique (échéance atteinte)",
    "attacker": "Le pirate (clé volée)",
    "buyer": "Un acheteur honnête",
    "spec1": "Spéculateur 1",
    "spec2": "Spéculateur 2",
    "spec3": "Spéculateur 3",
    "watcher": "Le surveillant",
    "guardian1": "Gardien 1",
    "guardian2": "Gardien 2",
    "guardian3": "Gardien 3",
    "whale": "Un gros porteur",
}
# Pour le journal d'audit DORA (convention `shared.AuditLogEntry.actor`).
FUJI_ACTORS_ONCHAIN = {
    "admin": "equipe:deploiement",
    "attacker": "attaquant:cle_service_volee",
    "buyer": "utilisateur:acheteur_honnete",
    "watcher": "monitor:surveillant_onchain",
    "guardian1": "multisig:gardien1",
    "guardian2": "multisig:gardien2",
    "guardian3": "multisig:gardien3",
    "whale": "utilisateur:gros_porteur",
}


class FujiLiveError(RuntimeError):
    """Le rejeu sur Fuji n'a pas pu aboutir (clé, RPC, transaction)."""


class TxRecord(BaseModel):
    """Une transaction réelle envoyée sur Fuji (toutes, intendance comprise)."""

    model_config = ConfigDict(extra="forbid")

    step: str
    actor: str
    label: str
    tx_hash: str
    block_number: int
    success: bool
    timestamp: datetime | None = None

    @property
    def url(self) -> str:
        """Lien Snowtrace testnet."""
        return f"{EXPLORER_URL}/tx/{self.tx_hash}"


class DemoStep(BaseModel):
    """Une étape INTÉRESSANTE d'un cas : commande de terminal + effet, adossée à de vraies tx."""

    model_config = ConfigDict(extra="forbid")

    case: str
    command: str  # ce qui est tapé dans le faux terminal
    actor: str
    actor_label: str
    contract: str  # contrat touché
    contract_url: str
    narration: str  # ce que fait l'étape (sur le bouton, avant exécution)
    effect: str  # résultat affiché après exécution
    outcome: str  # "accepted" | "rejected" | "defended"
    tx_urls: list[str]
    success: bool


class ObservedMint(BaseModel):
    """Mint relu sur la chaîne par le vrai `monitor.ChainListener`."""

    model_config = ConfigDict(extra="forbid")

    token: str
    recipient: str
    amount: int
    tx_hash: str


class FujiRun(BaseModel):
    """Résultat complet d'un rejeu sur Fuji (données publiques uniquement : aucune clé)."""

    model_config = ConfigDict(extra="forbid")

    chain_id: int
    started_at: datetime
    finished_at: datetime
    accounts: dict[str, str]
    contracts: dict[str, str]
    transactions: list[TxRecord]
    steps: list[DemoStep]
    # Cas 1 / 2 (clé volée), montants en base units du stable (18 déc.).
    deposit: int
    signed_amount: int
    vulnerable_minted: int
    vulnerable_collateral: int
    protected_minted: int
    protected_collateral: int
    protected_inflated_rejected: bool
    # Cas 3 (vendeur de Ghost).
    sell_mprime: int  # M' écoulé par le vendeur
    buyer_paid_usdc: int  # USDC payé par l'acheteur (6 déc.)
    seller_payment_before: int  # Ghost de paiement du vendeur avant destruction
    seller_payment_after: int
    buyer_mprime_after: int  # M' de l'acheteur après destruction (doit être 0)
    frozen_usdc_before: int  # USDC gelé au coffre avant restitution
    buyer_restituted_usdc: int  # USDC rendu à l'acheteur
    seller_usdc_final: int  # USDC encaissé par le vendeur au final (doit être 0)
    observed_mints: list[ObservedMint]

    @property
    def vulnerable_loss(self) -> int:
        """Offre non adossée du contrat vulnérable (perte protocole)."""
        return max(0, self.vulnerable_minted - self.vulnerable_collateral)

    @property
    def protected_loss(self) -> int:
        """Offre non adossée du contrat protégé."""
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
    """Clé de test déterministe du rôle, dérivée de la clé maître (testnet uniquement)."""
    from eth_utils import keccak

    seed = bytes.fromhex(master_key.removeprefix("0x")) + f"secure-horizons/demo/{role}".encode()
    return "0x" + keccak(seed).hex().removeprefix("0x")


def master_key_from_env() -> str:
    """Clé de test Fuji lue dans l'environnement / `.env` (FujiLiveError si absente)."""
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
    """Vrai si une clé de test Fuji est configurée (sans la renvoyer)."""
    try:
        master_key_from_env()
    except FujiLiveError:
        return False
    return True


def _merkle_single_leaf(to: str, amount: int, nonce: int) -> bytes:
    """Racine de Merkle d'une seule feuille `restitute` (= la feuille, preuve vide)."""
    from eth_abi import encode
    from eth_utils import keccak, to_canonical_address

    inner = keccak(encode(["address", "uint256", "uint256"],
                          [to_canonical_address(to), amount, nonce]))
    return keccak(inner)


class FujiRunner:
    """Envoie des transactions signées sur Fuji, journalise chacune, et collecte les étapes."""

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
        self.steps: list[DemoStep] = []
        self.contracts: dict[str, str] = {}
        self._progress = progress or (lambda _msg: None)
        self._phase = ""

    def address(self, role: str) -> str:
        """Adresse publique du rôle."""
        return str(self.accounts[role].address)

    def contract_url(self, name: str) -> str:
        """Lien Snowtrace du contrat déployé `name` (chaîne vide si inconnu)."""
        address = self.contracts.get(name)
        return address_url(address) if address else ""

    def phase(self, name: str) -> None:
        """Ouvre une phase (rattachée aux transactions suivantes et affichée)."""
        self._phase = name
        self._progress(name)

    def add_step(self, case: str, command: str, actor: str, contract: str, narration: str,
                 effect: str, outcome: str, tx_urls: list[str], success: bool) -> None:
        """Enregistre une étape intéressante (visible dans le terminal de la démo)."""
        self.steps.append(DemoStep(
            case=case, command=command, actor=actor, actor_label=ACTOR_LABELS.get(actor, actor),
            contract=contract, contract_url=self.contract_url(contract), narration=narration,
            effect=effect, outcome=outcome, tx_urls=tx_urls, success=success))
        self._progress(f"  → {command}")

    def _fees(self) -> dict[str, int]:
        base = int(self.w3.eth.get_block("latest").get("baseFeePerGas", 0))
        try:
            tip = max(int(self.w3.eth.max_priority_fee), 1)
        except Exception:  # noqa: BLE001 - certains nœuds n'exposent pas eth_maxPriorityFeePerGas
            tip = 10**9
        return {"maxPriorityFeePerGas": tip, "maxFeePerGas": 2 * base + tip}

    def _send(self, role: str, tx: dict[str, Any], label: str) -> tuple[Any, TxRecord]:
        account = self.accounts[role]
        tx = {**tx, "from": account.address, "chainId": FUJI_CHAIN_ID,
              "nonce": self.w3.eth.get_transaction_count(account.address, "pending"), **self._fees()}
        signed = account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash,
                                                           timeout=RECEIPT_TIMEOUT_SECONDS)
        block = self.w3.eth.get_block(int(receipt["blockNumber"]))
        record = TxRecord(step=self._phase, actor=role, label=label,
                          tx_hash="0x" + bytes(receipt["transactionHash"]).hex().removeprefix("0x"),
                          block_number=int(receipt["blockNumber"]),
                          success=int(receipt["status"]) == 1,
                          timestamp=datetime.fromtimestamp(int(block["timestamp"]), timezone.utc))
        self.records.append(record)
        self._progress(f"{'✔' if record.success else '✖'} {label}")
        return receipt, record

    def transact(self, role: str, fn: Any, label: str, expect_success: bool = True) -> TxRecord:
        """Envoie l'appel `fn` ; une tentative qui revert est QUAND MÊME diffusée (preuve)."""
        sender = self.accounts[role].address
        try:
            gas = int(fn.estimate_gas({"from": sender}) * 1.3) + 10_000
        except Exception:  # noqa: BLE001 - revert prévu : on le diffuse pour la trace on-chain
            gas = FALLBACK_GAS
        tx = fn.build_transaction({"from": sender, "gas": gas, "nonce": 0, "chainId": FUJI_CHAIN_ID,
                                   "maxFeePerGas": 0, "maxPriorityFeePerGas": 0})
        _, record = self._send(role, {k: tx[k] for k in ("to", "data", "gas")}, label)
        if expect_success and not record.success:
            raise FujiLiveError(f"transaction rejetée : {label}")
        return record

    def transact_raw(self, role: str, to: str, data: str, label: str) -> TxRecord:
        """Diffuse un appel brut (sélecteur absent du contrat) ; renvoie le TxRecord."""
        _, record = self._send(role, {"to": to, "data": data, "gas": FALLBACK_GAS}, label)
        return record

    def deploy(self, name: str, label: str, *args: Any) -> Any:
        """Déploie `contracts/out/<name>` depuis l'admin ; renvoie le contrat web3."""
        artifact = load_artifact(name)
        factory = self.w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        data = factory.constructor(*args).data_in_transaction
        gas = int(self.w3.eth.estimate_gas({"from": self.address("admin"), "data": data}) * 1.2)
        receipt, _ = self._send("admin", {"data": data, "gas": gas}, label)
        if int(receipt["status"]) != 1 or not receipt["contractAddress"]:
            raise FujiLiveError(f"déploiement échoué : {name}")
        self.contracts[name] = receipt["contractAddress"]
        return self.at(name, receipt["contractAddress"])

    def at(self, name: str, address: str) -> Any:
        """Contrat web3 `name` déjà déployé à `address`."""
        return self.w3.eth.contract(address=self.w3.to_checksum_address(address),
                                    abi=load_artifact(name)["abi"])

    def fund_roles(self) -> None:
        """Approvisionne chaque rôle en AVAX de test depuis l'admin, si besoin (intendance)."""
        for role in ROLES:
            address = self.accounts[role].address
            if self.w3.eth.get_balance(address) < SUB_ACCOUNT_MIN_WEI:
                self._send("admin", {"to": address, "value": SUB_ACCOUNT_FUNDING_WEI,
                                     "gas": 21_000}, f"AVAX de test pour le rôle {role}")


def _deposit(runner: FujiRunner, usdc: Any, minter: Any, who: str, amount: int) -> int:
    """Intendance (non exposée) : `who` reçoit `amount` USDC et dépose dans `minter`."""
    runner.transact(who, usdc.functions.mint(runner.address(who), amount), f"faucet USDC {who}")
    runner.transact(who, usdc.functions.approve(minter.address, amount), f"approve {who}")
    request_id = int(minter.functions.nextRequestId().call())
    runner.transact(who, minter.functions.requestSwap(amount), f"requestSwap {who}")
    return request_id


def _mint_ghost(runner: FujiRunner, usdc: Any, minter: Any, service: str, who: str,
                amount: int) -> None:
    """Intendance : `who` dépose puis la clé de service traite la demande -> Ghost frais."""
    request_id = _deposit(runner, usdc, minter, who, amount)
    runner.transact(service, minter.functions.completeSwap(request_id), f"completeSwap {who}")


def observe_mints(web3: Any, token: str, from_block: int, to_block: int) -> list[ObservedMint]:
    """Mints de `token` relus par le VRAI `monitor.ChainListener` sur la plage de blocs."""
    from monitor.config import MonitorConfig
    from monitor.listener import ChainListener

    config = MonitorConfig(rpc_url=None, token_address=web3.to_checksum_address(token),
                           confirmations=0, start_block=from_block)
    events = ChainListener(config, web3=web3).fetch_mint_events(from_block, to_block)
    return [ObservedMint(token=token, recipient=str(e.recipient), amount=int(e.amount),
                         tx_hash=str(e.tx_hash)) for e in events]


def _tok(base_units_18: int) -> str:
    return f"{base_units_18 // 10**18:,}".replace(",", " ")


def _usdc(base_units_6: int) -> str:
    return f"{base_units_6 // 10**6:,}".replace(",", " ")


def _case_mint_passes(runner: FujiRunner, usdc: Any) -> dict[str, int]:
    """Cas 1 : contrat classique, le mint gonflé passe."""
    runner.phase("Cas 1 — le mint passe (contrat classique)")
    admin, attacker = runner.address("admin"), runner.address("attacker")
    signed = ATTACK_DEPOSIT * DECIMALS_SCALE * ATTACK_MULTIPLIER
    vulnerable = runner.deploy("VulnerableMinter", "Déploiement du contrat classique",
                               usdc.address, admin, attacker)
    stable = runner.at("StableToken", vulnerable.functions.stable().call())
    request_id = _deposit(runner, usdc, vulnerable, "attacker", ATTACK_DEPOSIT)  # intendance
    rec = runner.transact("attacker", vulnerable.get_function_by_signature(
        "completeSwap(uint256,address,uint256)")(request_id, attacker, signed),
        "mint gonflé accepté")
    minted = int(stable.functions.totalSupply().call())
    held = int(usdc.functions.balanceOf(vulnerable.address).call()) * DECIMALS_SCALE
    runner.add_step(
        CASE_MINT_PASSES, f"cle-volee > mint --montant {_tok(signed)} --preuve signature-volee",
        "attacker", "VulnerableMinter",
        "La clé volée signe la création de 1 000 fois le dépôt réel. Le contrat classique croit la "
        "signature.",
        f"✗ ACCEPTÉ. {_tok(minted)} jetons créés pour seulement {_usdc(ATTACK_DEPOSIT)} USDC "
        f"déposés : {_tok(minted - held)} jetons n'ont AUCUNE réserve derrière eux.",
        "accepted", [rec.url], rec.success)
    return {"minted": minted, "collateral": held, "signed": signed}


def _case_mint_blocked(runner: FujiRunner, usdc: Any) -> dict[str, int]:
    """Cas 2 : ProtectedMinter, le mint gonflé est rejeté, seul le dépôt est servi."""
    runner.phase("Cas 2 — le mint est bloqué (Crypto-Secure)")
    admin, attacker = runner.address("admin"), runner.address("attacker")
    guardians = [runner.address(f"guardian{i}") for i in (1, 2, 3)]
    signed = ATTACK_DEPOSIT * DECIMALS_SCALE * ATTACK_MULTIPLIER
    protected = runner.deploy("ProtectedMinter", "Déploiement du contrat Crypto-Secure",
                              usdc.address, admin, attacker, RATE_ONE, guardians, GHOST_CONFIG)
    ghost = runner.at("GhostToken", protected.functions.ghost().call())
    runner.contracts["GhostToken"] = ghost.address
    request_id = _deposit(runner, usdc, protected, "attacker", ATTACK_DEPOSIT)  # intendance
    inflated = runner.at("VulnerableMinter", protected.address).encode_abi(
        "completeSwap", args=[request_id, attacker, signed])
    rej = runner.transact_raw("attacker", protected.address, inflated, "mint gonflé rejeté")
    runner.add_step(
        CASE_MINT_BLOCKED, f"cle-volee > mint --montant {_tok(signed)} --preuve signature-volee",
        "attacker", "ProtectedMinter",
        "La clé volée tente EXACTEMENT le même mint gonflé que sur le contrat classique.",
        "✓ REJETÉ par la blockchain. Ce contrat n'a pas d'appel « crois mon montant » : "
        "le montant signé est ignoré.",
        "rejected", [rej.url], not rej.success)
    served = runner.transact("attacker", protected.functions.completeSwap(request_id),
                             "traiter la demande (montant lu au coffre)")
    minted = int(ghost.functions.supplyValue().call())
    held = int(usdc.functions.balanceOf(protected.address).call()) * DECIMALS_SCALE
    runner.add_step(
        CASE_MINT_BLOCKED, f"cle-volee > traiter-demande --id {request_id}",
        "attacker", "ProtectedMinter",
        "Seul appel possible : « traite la demande n°X ». Le contrat lit lui-même le dépôt dans le "
        "coffre.",
        f"✓ {_tok(ATTACK_DEPOSIT * DECIMALS_SCALE)} Ghost émis, adossés 1:1 au dépôt réel. Pas un "
        "jeton de plus. Une clé volée ne rapporte rien.",
        "defended", [served.url], served.success)
    return {"minted": minted, "collateral": held, "rejected": not rej.success}


def _case_recovery_window(runner: FujiRunner, usdc: Any) -> None:
    """Cas « fenêtre de reprise » : un échange donne du M-Ghost, converti en M-Coin après la fenêtre.

    C'est le levier de reprise : entre le M-Ghost (réversible) et le M-Coin (définitif) il y a la
    fenêtre de sécurité ; pendant elle, on peut geler/détruire (cas suivant). Ici tout est clean,
    donc la conversion aboutit. Fenêtre raccourcie à 1 s pour la jouer en direct sur Fuji.
    """
    runner.phase("Cas « fenêtre de reprise » — M-Ghost → M-Coin")
    admin, honest = runner.address("admin"), runner.address("buyer")
    guardians = [runner.address(f"guardian{i}") for i in (1, 2, 3)]
    minter = runner.deploy("ProtectedMinter", "Déploiement du minter (fenêtre de reprise)",
                           usdc.address, admin, runner.address("whale"), RATE_ONE, guardians,
                           GHOST_CONFIG_FAST)
    runner.contracts["ProtectedMinter (reprise)"] = minter.address
    ghost = runner.at("GhostToken", minter.functions.ghost().call())
    runner.contracts["GhostToken (reprise)"] = ghost.address
    mcoin = runner.at("GhostedStable", ghost.functions.underlying().call())
    runner.contracts["M-Coin (GhostedStable)"] = mcoin.address

    # Intendance (non exposée) : faucet + approve de l'utilisateur honnête.
    runner.transact("buyer", usdc.functions.mint(honest, RECOVERY_DEPOSIT), "faucet USDC honnête")
    runner.transact("buyer", usdc.functions.approve(minter.address, RECOVERY_DEPOSIT),
                    "approve honnête")
    request_id = int(minter.functions.nextRequestId().call())
    req = runner.transact("buyer", minter.functions.requestSwap(RECOVERY_DEPOSIT), "dépôt honnête")
    comp = runner.transact("whale", minter.functions.completeSwap(request_id), "émission M-Ghost")
    mghost = int(ghost.functions.balanceOf(honest).call())
    runner.add_step(
        CASE_RECOVERY_WINDOW,
        f"honnete > echanger --depot {_usdc(RECOVERY_DEPOSIT)}USDC",
        "buyer", "ProtectedMinter (reprise)",
        "Un utilisateur honnête échange 1 000 USDC. Que reçoit-il tout de suite ?",
        f"✓ Il reçoit {_tok(mghost)} M-Ghost — PAS encore du M-Coin. Convertible en M-Coin "
        "seulement après la fenêtre de sécurité : c'est CETTE fenêtre qui permet de tout reprendre "
        "si un problème surgit (voir le cas suivant).",
        "defended", [req.url, comp.url], comp.success)

    # Attendre la maturité (fenêtre raccourcie), puis convertir en M-Coin.
    for _ in range(CONVERT_POLL_TRIES):
        if int(ghost.functions.convertibleOf(honest).call()) >= mghost:
            break
        time.sleep(CONVERT_POLL_SECONDS)
    conv = runner.transact("buyer", ghost.functions.convert(mghost),
                           "réalisation 1:1 à l'échéance")
    minted_mcoin = int(mcoin.functions.balanceOf(honest).call())
    runner.add_step(
        CASE_RECOVERY_WINDOW, "⏱ échéance atteinte (10 min, aucune anomalie) → M-Ghost = M-Coin 1:1",
        "protocole", "GhostToken (reprise)",
        "Personne ne « convertit » : au bout de la fenêtre sans anomalie, le M-Ghost arrive à "
        "échéance tout seul et vaut du M-Coin 1:1. Réaliser le vrai jeton est une formalité "
        "permissionless (détenteur ou automate), qui ne peut pas être refusée.",
        f"✓ Échéance atteinte sans anomalie : {_tok(mghost)} M-Ghost valent désormais "
        f"{_tok(minted_mcoin)} M-Coin définitifs, adossés 1:1 à l'USDC. Avant l'échéance, tout "
        "restait réversible ; après, c'est final — mais ici aucune reprise n'était nécessaire.",
        "defended", [conv.url], conv.success)


def _contagion_world(runner: FujiRunner, usdc: Any, use_beacon: bool) -> tuple[Any, Any, Any]:
    """Déploie minter+ghost (+balise si use_beacon) et un marché de prêt ; renvoie (ghost, market, incident).

    Intendance NON exposée : l'attaquant reçoit du Ghost (collatéral), est signalé (suspect),
    une offre de fond donne la marge du budget de quarantaine, le marché a sa liquidité USDC.
    """
    admin = runner.address("admin")
    guardians = [runner.address(f"guardian{i}") for i in (1, 2, 3)]
    suffix = "pare-feu" if use_beacon else "aveugle"
    minter = runner.deploy("ProtectedMinter", f"Déploiement du minter ({suffix})",
                           usdc.address, admin, runner.address("whale"), RATE_ONE, guardians,
                           GHOST_CONFIG)
    ghost = runner.at("GhostToken", minter.functions.ghost().call())
    runner.contracts[f"GhostToken ({suffix})"] = ghost.address
    runner.transact("admin", ghost.functions.grantRole(ghost.functions.WATCHER_ROLE().call(),
                                                       runner.address("watcher")), "rôle surveillant")
    beacon_addr = ZERO_ADDRESS
    if use_beacon:
        beacon = runner.deploy("RiskBeacon", "Déploiement de la balise de risque", ghost.address)
        beacon_addr = beacon.address
    cfg = (use_beacon, MARKET_LTV_BPS, MARKET_BASE_HAIRCUT_BPS, MARKET_SLOPE_HAIRCUT_BPS,
           MARKET_MAX_BORROW_RATIO, MARKET_MAX_BORROW_SUSPECT)
    market = runner.deploy("MockLendingMarket", f"Déploiement du marché de prêt ({suffix})",
                           ghost.address, usdc.address, ghost.address, beacon_addr,
                           DECIMALS_SCALE, cfg)
    runner.contracts[f"Marché de prêt ({suffix})"] = market.address
    runner.transact("whale", usdc.functions.mint(market.address, CONTAGION_LIQUIDITY),
                    "liquidité du marché")  # intendance
    _mint_ghost(runner, usdc, minter, "whale", "whale", BACKGROUND_DEPOSIT)  # budget quarantaine
    _mint_ghost(runner, usdc, minter, "whale", "attacker", ATTACK_DEPOSIT)  # collatéral attaquant
    suspect = int(ghost.functions.balanceOf(runner.address("attacker")).call())
    delayed = runner.transact("watcher", ghost.functions.delay([runner.address("attacker")],
                              [suspect], GHOST_W_SECONDS), "signalement de l'attaquant")  # intendance
    incident = int(ghost.functions.openIncidentId().call())
    return ghost, market, incident


def _case_contagion(runner: FujiRunner, usdc: Any) -> None:
    """Cas « pare-feu de contagion » (C) : un collatéral empoisonné contamine un marché aveugle,
    mais est refusé par un marché qui lit la balise de risque."""
    runner.phase("Cas « pare-feu de contagion » — la fraude ne se propage pas")
    attacker = runner.address("attacker")

    # Marché AVEUGLE : il ne lit pas la balise ; il accepte le collatéral suspect.
    ghost, market, incident = _contagion_world(runner, usdc, use_beacon=False)
    collat = int(ghost.functions.balanceOf(attacker).call())
    runner.transact("attacker", ghost.functions.approve(market.address, collat),
                    "approve collatéral")  # intendance
    runner.transact("attacker", market.functions.deposit(collat), "dépôt collatéral")  # intendance
    capacity = int(market.functions.capacityOf(attacker).call())
    borrow = runner.transact("attacker", market.functions.borrow(capacity),
                             "emprunt sur marché aveugle", expect_success=False)
    borrowed = int(market.functions.totalDebt().call())
    runner.add_step(
        CASE_CONTAGION, f"pirate > emprunter --marche aveugle --max",
        "attacker", "Marché de prêt (aveugle)",
        "Le pirate dépose son Ghost suspect dans un marché de prêt qui ne lit PAS la balise, et "
        "emprunte dessus.",
        f"✗ ACCEPTÉ : {_usdc(borrowed)} USDC prêtés contre un collatéral empoisonné. Le marché "
        "aveugle vient de laisser entrer la fraude.",
        "accepted", [borrow.url], borrow.success)

    # Les gardiens détruisent le Ghost suspect -> le collatéral du marché aveugle s'évapore.
    runner.transact("guardian1", ghost.functions.proposeDestroy(incident, [market.address]),
                    "proposition destruction")
    approve = runner.transact("guardian2", ghost.functions.approveAction(
        int(ghost.functions.proposalCount().call())), "validation 2/3")
    remaining = int(ghost.functions.balanceOf(market.address).call()) // DECIMALS_SCALE
    bad_debt = max(0, borrowed - remaining)
    runner.add_step(
        CASE_CONTAGION, f"gardiens > detruire-ghost --incident {incident}",
        "guardian2", "GhostToken (aveugle)",
        "La fraude est confirmée : les gardiens 2/3 détruisent le Ghost suspect, y compris celui "
        "déposé dans le marché aveugle.",
        f"⚠ Le collatéral du marché aveugle s'évapore : il reste {_usdc(borrowed)} USDC prêtés sans "
        f"adossement → {_usdc(bad_debt)} USDC de créance douteuse. La fraude a contaminé le marché.",
        "accepted", [approve.url], approve.success)

    # Marché PARE-FEU : il lit la balise ; il refuse le même collatéral suspect.
    ghost2, market2, _ = _contagion_world(runner, usdc, use_beacon=True)
    collat2 = int(ghost2.functions.balanceOf(attacker).call())
    runner.transact("attacker", ghost2.functions.approve(market2.address, collat2),
                    "approve collatéral")  # intendance
    runner.transact("attacker", market2.functions.deposit(collat2), "dépôt collatéral")  # intendance
    cap2 = int(market2.functions.capacityOf(attacker).call())
    refused = runner.transact("attacker", market2.functions.borrow(max(cap2, 1)),
                              "emprunt sur marché pare-feu", expect_success=False)
    runner.add_step(
        CASE_CONTAGION, "pirate > emprunter --marche pare-feu --max",
        "attacker", "Marché de prêt (pare-feu)",
        "Le pirate tente EXACTEMENT le même emprunt sur un marché qui lit la balise de risque.",
        "✓ REFUSÉ on-chain (BorrowRefused) : la balise signale que l'emprunteur n'est pas dans "
        "l'état NORMAL. Zéro prêt, zéro créance douteuse. La contagion est stoppée à la porte.",
        "defended", [refused.url], not refused.success)


def _case_speculative_market(runner: FujiRunner, usdc: Any) -> None:
    """Cas « marché spéculatif du Ghost » : le détenteur revend son M-Ghost en boucle AVANT toute
    conversion en M-Coin (quarantaine liquide) ; une fraude confirmée tard frappe le spéculateur."""
    runner.phase("Cas « marché spéculatif du Ghost » — reventes avant tout M-Coin")
    admin = runner.address("admin")
    guardians = [runner.address(f"guardian{i}") for i in (1, 2, 3)]
    minter = runner.deploy("ProtectedMinter", "Déploiement du minter (marché)",
                           usdc.address, admin, runner.address("whale"), RATE_ONE, guardians,
                           GHOST_CONFIG)
    runner.contracts["ProtectedMinter (marché)"] = minter.address
    ghost = runner.at("GhostToken", minter.functions.ghost().call())
    runner.contracts["GhostToken (marché)"] = ghost.address
    router = runner.deploy("SettlementRouter", "Déploiement du routeur (marché)", ghost.address)
    runner.contracts["SettlementRouter (marché)"] = router.address
    runner.transact("admin", ghost.functions.grantRole(ghost.functions.WATCHER_ROLE().call(),
                                                       runner.address("watcher")), "rôle surveillant")
    # Intendance : offre de fond (budget) + le détenteur initial reçoit son M-Ghost.
    _mint_ghost(runner, usdc, minter, "whale", "whale", BACKGROUND_DEPOSIT)
    _mint_ghost(runner, usdc, minter, "whale", "attacker", SELL_AMOUNT_USDC)
    mg = SELL_AMOUNT_USDC * DECIMALS_SCALE

    # Chaîne de reventes : détenteur -> spec1 -> spec2 -> spec3, à des prix volatils.
    chain = [("attacker", "spec1"), ("spec1", "spec2"), ("spec2", "spec3")]
    urls = []
    for (seller, buyer), price in zip(chain, SPEC_PRICES_USDC):
        runner.transact(seller, ghost.functions.approve(router.address, mg), "approve M'")
        runner.transact(buyer, usdc.functions.mint(runner.address(buyer), price), "faucet USDC")
        runner.transact(buyer, usdc.functions.approve(router.address, price), "approve USDC")
        rec = runner.transact(buyer, router.functions.buyWithAsset(
            runner.address(seller), mg, usdc.address, price),
            f"{buyer} achète le Ghost ({price // 10**6} USDC)")
        urls.append(rec.url)
    runner.add_step(
        CASE_SPECULATIVE, "marche > revendre-ghost --chaine detenteur→spec1→spec2→spec3",
        "spec3", "SettlementRouter (marché)",
        "Le détenteur n'a pas encore de M-Coin, mais revend son M-Ghost. Puis les spéculateurs se "
        "le revendent entre eux.",
        f"✓ Le même lot de M-Ghost a changé de mains {len(chain)} fois en quelques secondes, à "
        f"{', '.join(str(p // 10**6) for p in SPEC_PRICES_USDC)} USDC — un marché spéculatif liquide "
        "s'est formé, alors qu'AUCUN M-Coin n'existe encore (fenêtre non échue).",
        "accepted", urls, True)

    # Fraude confirmée tardivement : le Ghost est détruit chez le spéculateur qui le détient.
    holder = runner.address("spec3")
    runner.transact("watcher", ghost.functions.delay([holder], [mg], GHOST_W_SECONDS),
                    "signalement tardif")
    incident = int(ghost.functions.openIncidentId().call())
    runner.transact("guardian1", ghost.functions.proposeDestroy(incident, [holder]),
                    "proposition destruction")
    approve = runner.transact("guardian2", ghost.functions.approveAction(
        int(ghost.functions.proposalCount().call())), "validation 2/3")
    holder_after = int(ghost.functions.balanceOf(holder).call())
    runner.add_step(
        CASE_SPECULATIVE, "gardiens > detruire-ghost (fraude confirmée tard)",
        "guardian2", "GhostToken (marché)",
        "On confirme la fraude APRÈS plusieurs reventes. Qui paie ?",
        f"✓ Le Ghost est détruit chez le dernier spéculateur (solde : {_tok(holder_after)}). C'est "
        "LUI qui encaisse la perte — le protocole n'a jamais émis de M-Coin, sa perte est de 0. Le "
        "risque a été transféré au marché spéculatif.",
        "defended", [approve.url], approve.success)


def _case_ghost_seller(runner: FujiRunner, usdc: Any) -> dict[str, int]:
    """Cas 3 : un vendeur de Ghost est signalé -> destruction de tout le Ghost + USDC gelé rendu."""
    runner.phase("Cas 3 — un vendeur de Ghost pose problème")
    admin = runner.address("admin")
    seller, buyer = runner.address("attacker"), runner.address("buyer")
    guardians = [runner.address(f"guardian{i}") for i in (1, 2, 3)]
    minter = runner.deploy("ProtectedMinter", "Déploiement du minter du cas 3",
                           usdc.address, admin, runner.address("whale"), RATE_ONE, guardians,
                           GHOST_CONFIG)
    ghost = runner.at("GhostToken", minter.functions.ghost().call())
    runner.contracts["GhostToken"] = ghost.address
    router = runner.deploy("SettlementRouter", "Déploiement du routeur de règlement",
                           ghost.address)
    watcher_role = ghost.functions.WATCHER_ROLE().call()
    runner.transact("admin", ghost.functions.grantRole(watcher_role, runner.address("watcher")),
                    "rôle surveillant")
    # Intendance (non exposée) : offre de fond légitime + le vendeur détient déjà du Ghost.
    # La clé de service (whale, ≠ admin) traite les dépôts.
    _mint_ghost(runner, usdc, minter, "whale", "whale", BACKGROUND_DEPOSIT)
    _mint_ghost(runner, usdc, minter, "whale", "attacker", SELL_AMOUNT_USDC)
    sell_mprime = SELL_AMOUNT_USDC * DECIMALS_SCALE

    # Étape : l'acheteur achète le Ghost du vendeur ; son USDC est bloqué au coffre.
    runner.transact("attacker", ghost.functions.approve(router.address, sell_mprime),
                    "approve M' vendeur")  # intendance
    runner.transact("buyer", usdc.functions.mint(buyer, SELL_AMOUNT_USDC), "faucet USDC acheteur")
    runner.transact("buyer", usdc.functions.approve(router.address, SELL_AMOUNT_USDC),
                    "approve USDC acheteur")  # intendance
    buy = runner.transact("buyer", router.functions.buyWithAsset(
        seller, sell_mprime, usdc.address, SELL_AMOUNT_USDC), "achat de Ghost (USDC bloqué)")
    vault = runner.at("AssetVault", router.functions.vaultOf(usdc.address).call())
    runner.contracts["AssetVault"] = vault.address
    payment_ghost = runner.at("AssetGhost", vault.functions.assetGhost().call())
    runner.contracts["AssetGhost"] = payment_ghost.address
    seller_payment_before = int(payment_ghost.functions.balanceOf(seller).call())
    frozen_before = int(usdc.functions.balanceOf(vault.address).call())
    runner.add_step(
        CASE_GHOST_SELLER,
        f"acheteur > acheter-ghost --vendeur {seller[:10]}… --prix {_usdc(SELL_AMOUNT_USDC)}USDC",
        "buyer", "SettlementRouter",
        "Un acheteur honnête achète le Ghost que le vendeur met en vente.",
        f"✓ {_usdc(frozen_before)} USDC de l'acheteur sont BLOQUÉS au coffre. Le vendeur reçoit "
        f"{_usdc(seller_payment_before)} Ghost de paiement — non encaissables tant qu'ils ne sont "
        "pas convertis en USDC.",
        "accepted", [buy.url], buy.success)

    # Étape : on signale le vendeur (méthode non divulguée) -> tout son Ghost est gelé.
    delay = runner.transact("watcher", ghost.functions.delay([buyer], [sell_mprime],
                                                             GHOST_W_SECONDS), "signalement + gel")
    incident = int(ghost.functions.openIncidentId().call())
    runner.add_step(
        CASE_GHOST_SELLER, f"surveillant > signaler --compte {seller[:10]}…",
        "watcher", "GhostToken",
        "On découvre un problème avec ce vendeur (comment : non divulgué). Le surveillant ne peut "
        "que GELER, jamais détruire.",
        "⚠ Vendeur signalé. Tout le Ghost suspect encore en circulation est gelé : plus personne "
        "ne peut l'encaisser le temps de l'enquête.",
        "defended", [delay.url], delay.success)

    # Étape : les gardiens 2/3 détruisent TOUT le Ghost suspect en circulation.
    propose = runner.transact("guardian1", ghost.functions.proposeDestroy(incident, [buyer]),
                              "proposition destruction")
    pid = int(ghost.functions.proposalCount().call())
    approve = runner.transact("guardian2", ghost.functions.approveAction(pid), "validation 2/3")
    buyer_mprime_after = int(ghost.functions.balanceOf(buyer).call())
    runner.add_step(
        CASE_GHOST_SELLER, f"gardiens > detruire-ghost --incident {incident}",
        "guardian2", "GhostToken",
        "Deux gardiens sur trois décident : on détruit tout le Ghost suspect qui existe.",
        f"✓ 2 sur 3. Tout le Ghost suspect est détruit (il en reste {_tok(buyer_mprime_after)}). "
        "Le Ghost frauduleux cesse d'exister.",
        "defended", [propose.url, approve.url], approve.success)

    # Étape : brûler le Ghost de paiement du vendeur -> son USDC reste gelé, il n'encaisse rien.
    runner.transact("guardian1", vault.functions.burnSeedPayment(seller, SELL_AMOUNT_USDC, 0),
                    "burn paiement 1/2")
    burn2 = runner.transact("guardian2", vault.functions.burnSeedPayment(seller, SELL_AMOUNT_USDC, 0),
                            "burn paiement 2/2")
    seller_payment_after = int(payment_ghost.functions.balanceOf(seller).call())
    runner.add_step(
        CASE_GHOST_SELLER, f"gardiens > bruler-paiement --vendeur {seller[:10]}…",
        "guardian2", "AssetVault",
        "On brûle le Ghost de paiement que le vendeur avait reçu.",
        f"✓ Ghost de paiement du vendeur : {_usdc(seller_payment_after)}. Son USDC était gelé au "
        "coffre faute de conversion : il n'a JAMAIS pu l'encaisser.",
        "defended", [burn2.url], burn2.success)

    # Étape : rendre l'USDC gelé à l'acheteur honnête.
    root = _merkle_single_leaf(buyer, SELL_AMOUNT_USDC, 0)
    runner.transact("guardian1", vault.functions.confirmRestitutionRoot(root), "racine 1/2")
    runner.transact("guardian2", vault.functions.confirmRestitutionRoot(root), "racine 2/2")
    restitute = runner.transact("buyer", vault.functions.restitute(buyer, SELL_AMOUNT_USDC, 0, []),
                                "restitution acheteur")
    buyer_restituted = int(usdc.functions.balanceOf(buyer).call())
    seller_usdc_final = int(usdc.functions.balanceOf(seller).call())
    frozen_after = int(usdc.functions.balanceOf(vault.address).call())
    runner.add_step(
        CASE_GHOST_SELLER, f"gardiens > restituer --vers {buyer[:10]}…",
        "guardian2", "AssetVault",
        "On rend à l'acheteur honnête l'argent qui était gelé.",
        f"✓ {_usdc(buyer_restituted)} USDC rendus à l'acheteur. Coffre vidé "
        f"({_usdc(frozen_after)} USDC restant). Le vendeur malhonnête finit à "
        f"{_usdc(seller_usdc_final)} USDC : il n'a rien gagné.",
        "defended", [restitute.url], restitute.success)
    return {"sell_mprime": sell_mprime, "buyer_paid": SELL_AMOUNT_USDC,
            "payment_before": seller_payment_before, "payment_after": seller_payment_after,
            "buyer_mprime_after": buyer_mprime_after, "frozen_before": frozen_before,
            "buyer_restituted": buyer_restituted, "seller_usdc_final": seller_usdc_final}


def replay_on_fuji(web3: Any, master_key: str,
                   progress: Callable[[str], None] | None = None) -> FujiRun:
    """Rejoue les 3 cas sur Fuji (voir docstring du module)."""
    started = datetime.now(timezone.utc)
    runner = FujiRunner(web3, master_key, progress)
    first_block = int(web3.eth.block_number)

    runner.phase("Préparation des comptes de test")
    runner.fund_roles()
    usdc = runner.deploy("MockUSDC", "Déploiement du faux USDC de test")

    case1 = _case_mint_passes(runner, usdc)
    case2 = _case_mint_blocked(runner, usdc)
    _case_recovery_window(runner, usdc)
    _case_speculative_market(runner, usdc)
    case3 = _case_ghost_seller(runner, usdc)
    _case_contagion(runner, usdc)

    runner.phase("Le monitor relit la chaîne")
    stable_v = runner.at("StableToken",
                         runner.at("VulnerableMinter",
                                   runner.contracts["VulnerableMinter"]).functions.stable().call())
    last_block = int(web3.eth.block_number)
    observed = observe_mints(web3, stable_v.address, first_block, last_block)

    return FujiRun(
        chain_id=FUJI_CHAIN_ID, started_at=started, finished_at=datetime.now(timezone.utc),
        accounts={role: runner.address(role) for role in ("admin", *ROLES)},
        contracts=dict(runner.contracts),
        transactions=runner.records, steps=runner.steps,
        deposit=ATTACK_DEPOSIT * DECIMALS_SCALE, signed_amount=case1["signed"],
        vulnerable_minted=case1["minted"], vulnerable_collateral=case1["collateral"],
        protected_minted=case2["minted"], protected_collateral=case2["collateral"],
        protected_inflated_rejected=case2["rejected"],
        sell_mprime=case3["sell_mprime"], buyer_paid_usdc=case3["buyer_paid"],
        seller_payment_before=case3["payment_before"], seller_payment_after=case3["payment_after"],
        buyer_mprime_after=case3["buyer_mprime_after"], frozen_usdc_before=case3["frozen_before"],
        buyer_restituted_usdc=case3["buyer_restituted"], seller_usdc_final=case3["seller_usdc_final"],
        observed_mints=observed,
    )


class LiveState(BaseModel):
    """État relu À L'INSTANT sur Fuji pour les contrats d'un rejeu (lecture seule)."""

    model_config = ConfigDict(extra="forbid")

    block_number: int
    vulnerable_minted: int


def read_live_state(web3: Any, run: FujiRun) -> LiveState:
    """Relit sur Fuji (appels en lecture, aucune clé) un invariant stable du rejeu."""
    vulnerable = web3.eth.contract(
        address=web3.to_checksum_address(run.contracts["VulnerableMinter"]),
        abi=load_artifact("VulnerableMinter")["abi"])
    stable = web3.eth.contract(address=web3.to_checksum_address(vulnerable.functions.stable().call()),
                               abi=load_artifact("StableToken")["abi"])
    return LiveState(block_number=int(web3.eth.block_number),
                     vulnerable_minted=int(stable.functions.totalSupply().call()))


def connect(rpc_url: str | None = None) -> Any:
    """Client web3 sur Fuji (RPC publique par défaut)."""
    from web3 import Web3

    url = rpc_url or os.environ.get(RPC_ENV) or DEFAULT_RPC_URL
    return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))


def save_run(run: FujiRun, path: Path = LATEST_RUN_PATH) -> Path:
    """Écrit le rejeu en JSON (données publiques uniquement)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run(path: Path = LATEST_RUN_PATH) -> FujiRun | None:
    """Dernier rejeu enregistré, ou None."""
    if not path.is_file():
        return None
    return FujiRun.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    """CLI : rejoue sur Fuji et enregistre `dashboard/fuji_runs/latest.json`."""
    run = replay_on_fuji(connect(), master_key_from_env(), progress=print)
    print(f"Rejeu enregistré : {save_run(run)} ({len(run.transactions)} transactions, "
          f"{len(run.steps)} étapes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
