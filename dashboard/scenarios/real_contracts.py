"""Backend OPTIONNEL du scenario A (#70) : vrais contrats Foundry #4/#5 rejoues sur anvil.

Active seulement si `SH_DEMO_CONTRACTS_BACKEND=anvil`. Il faut alors `forge`, `anvil` et
`cast` (Foundry) dans le PATH, dans `SH_FOUNDRY_BIN` ou dans `~/.foundry/bin`, et les
dependances de `contracts/lib/` installees (voir `contracts/README.md`). Sinon, ou si le
rejeu echoue, le scenario A retombe AUTOMATIQUEMENT sur la simulation hors chaîne (avec
son bandeau) : la CI ne depend jamais d'anvil.

Le rejeu suit `contracts/test/ScenarioA.t.sol` sur une chaine anvil locale et jetable :
l'attaquant detient la cle `SERVICE_ROLE` (volee) et depose lui-meme, puis tente le mint
gonfle sur `VulnerableMinter` et sur `ProtectedMinter`. Les comptes sont les comptes
DEVERROUILLES d'anvil (`--unlocked`) : aucune cle privee n'est manipulee ici. Les
grandeurs lues on-chain (offre du stable, collateral detenu) sont des comptages sur une
chaine locale, pas des mesures du contrat deploye.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

CONTRACTS_BACKEND_ENV = "SH_DEMO_CONTRACTS_BACKEND"
FOUNDRY_BIN_ENV = "SH_FOUNDRY_BIN"
BACKEND_SIM = "sim"
BACKEND_ANVIL = "anvil"
OPT_IN_HINT = f"{CONTRACTS_BACKEND_ENV}={BACKEND_ANVIL}"

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
REQUIRED_LIBS = ("forge-std", "openzeppelin-contracts")
# ProtectedMinter : collateral 6 decimales -> stable 18 decimales, taux 1e18 = 1:1.
DECIMALS_SCALE = 10**12
RATE_ONE = 10**18
TOOLS = ("forge", "anvil", "cast")
COMMAND_TIMEOUT_SECONDS = 300.0
STARTUP_TIMEOUT_SECONDS = 20.0


class ContractsBackendError(RuntimeError):
    """Le rejeu on-chain n'a pas pu aboutir (outil absent, chaine, transaction)."""


def selected_backend() -> str:
    """Backend demande via `SH_DEMO_CONTRACTS_BACKEND` (`sim` par defaut)."""
    return os.environ.get(CONTRACTS_BACKEND_ENV, BACKEND_SIM).strip().lower() or BACKEND_SIM


def find_tool(name: str) -> str | None:
    """Chemin de l'outil Foundry `name` (SH_FOUNDRY_BIN, PATH, ~/.foundry/bin) ou None."""
    custom = os.environ.get(FOUNDRY_BIN_ENV)
    if custom:
        for candidate in (Path(custom) / name, Path(custom) / f"{name}.exe"):
            if candidate.is_file():
                return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    home = Path.home() / ".foundry" / "bin"
    for candidate in (home / name, home / f"{name}.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


def unavailable_reason() -> str | None:
    """Pourquoi le backend anvil ne peut pas tourner ici (None s'il le peut)."""
    missing = [tool for tool in TOOLS if find_tool(tool) is None]
    if missing:
        return f"outil(s) Foundry introuvable(s) : {', '.join(missing)}"
    libs = [lib for lib in REQUIRED_LIBS if not (CONTRACTS_DIR / "lib" / lib).is_dir()]
    if libs:
        return f"dépendances Foundry absentes dans contracts/lib : {', '.join(libs)}"
    return None


def parse_uint(output: str) -> int:
    """`cast call ...(uint256)` renvoie `123 [1.23e2]` : on garde l'entier."""
    token = output.strip().split()[0] if output.strip() else ""
    try:
        return int(token, 0)
    except ValueError as exc:
        raise ContractsBackendError(f"sortie cast inattendue : {output!r}") from exc


def last_json(output: str) -> dict[str, object]:
    """Dernier objet JSON d'une sortie forge / cast (`--json`)."""
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ContractsBackendError(f"sortie JSON introuvable : {output[-200:]!r}") from exc
    if not isinstance(value, dict):
        raise ContractsBackendError("sortie JSON inattendue")
    return value


class Chain(Protocol):
    """Operations on-chain utilisees par le rejeu (implementee par `AnvilChain`)."""

    accounts: list[str]

    def deploy(self, contract: str, sender: str, *args: str) -> str:
        """Deploie `contract` (`src/X.sol:X`) ; renvoie son adresse."""
        ...

    def send(self, sender: str, to: str, signature: str, *args: str) -> bool:
        """Envoie une transaction ; False si elle est rejetee (revert)."""
        ...

    def call(self, to: str, signature: str, *args: str) -> str:
        """Appel en lecture ; renvoie la sortie brute de `cast call`."""
        ...


class AnvilChain:
    """Chaine anvil locale et jetable ; transactions via `forge create` / `cast send --unlocked`."""

    def __init__(self) -> None:
        tools = {name: find_tool(name) for name in TOOLS}
        missing = [name for name, path in tools.items() if path is None]
        if missing:
            raise ContractsBackendError(f"outil(s) introuvable(s) : {', '.join(missing)}")
        self._tools: dict[str, str] = {k: v for k, v in tools.items() if v is not None}
        self._process: subprocess.Popen[bytes] | None = None
        self.rpc_url = ""
        self.accounts: list[str] = []

    def __enter__(self) -> AnvilChain:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.rpc_url = f"http://127.0.0.1:{port}"
        self._process = subprocess.Popen(
            [self._tools["anvil"], "--port", str(port), "--silent"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while True:
            try:
                accounts = json.loads(self._cast("rpc", "eth_accounts", "--rpc-url",
                                                 self.rpc_url))
                break
            except (ContractsBackendError, json.JSONDecodeError):
                if time.monotonic() > deadline or self._process.poll() is not None:
                    self.__exit__(None, None, None)
                    raise ContractsBackendError("anvil n'a pas démarré") from None
                time.sleep(0.2)
        self.accounts = [str(a) for a in accounts]
        return self

    def __exit__(self, *_: object) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def _run(self, tool: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                [self._tools[tool], *args], cwd=CONTRACTS_DIR, capture_output=True, text=True,
                timeout=COMMAND_TIMEOUT_SECONDS, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContractsBackendError(f"{tool} : {exc}") from exc
        if check and completed.returncode != 0:
            raise ContractsBackendError(f"{tool} {args[0]} a échoué : "
                                        f"{(completed.stderr or completed.stdout)[-300:]}")
        return completed

    def _cast(self, *args: str) -> str:
        return self._run("cast", *args).stdout

    def deploy(self, contract: str, sender: str, *args: str) -> str:
        command = ["create", contract, "--root", str(CONTRACTS_DIR), "--rpc-url", self.rpc_url,
                   "--unlocked", "--from", sender, "--broadcast", "--json"]
        if args:
            command += ["--constructor-args", *args]
        deployed = last_json(self._run("forge", *command).stdout).get("deployedTo")
        if not isinstance(deployed, str):
            raise ContractsBackendError(f"déploiement de {contract} sans adresse")
        return deployed

    def send(self, sender: str, to: str, signature: str, *args: str) -> bool:
        completed = self._run("cast", "send", to, signature, *args, "--rpc-url", self.rpc_url,
                              "--unlocked", "--from", sender, "--json", check=False)
        if completed.returncode != 0:
            return False
        return last_json(completed.stdout).get("status") in ("0x1", 1, "1")

    def call(self, to: str, signature: str, *args: str) -> str:
        return self._cast("call", to, signature, *args, "--rpc-url", self.rpc_url)


@dataclass(frozen=True)
class MinterReading:
    """Etat lu on-chain apres le rejeu d'une variante (stable : 18 decimales)."""

    minted: int  # totalSupply du stable (base units 18 dec.)
    collateral: int  # collateral detenu par le minter, converti en base units du stable
    signed_amount: int  # montant demande par la cle volee (18 dec.)
    inflated_call_accepted: bool

    @property
    def unbacked(self) -> int:
        """Offre non adossee au collateral detenu (perte protocole)."""
        return max(0, self.minted - self.collateral)


def _expect(ok: bool, what: str) -> None:
    if not ok:
        raise ContractsBackendError(f"transaction rejetée : {what}")


def _request(chain: Chain, usdc: str, minter: str, depositor: str, deposit: int) -> str:
    request_id = str(parse_uint(chain.call(minter, "nextRequestId()(uint256)")))
    _expect(chain.send(depositor, usdc, "approve(address,uint256)", minter, str(deposit)),
            "approve")
    _expect(chain.send(depositor, minter, "requestSwap(uint256)", str(deposit)), "requestSwap")
    return request_id


def _reading(chain: Chain, usdc: str, minter: str, signed: int, inflated_ok: bool) -> MinterReading:
    stable = chain.call(minter, "stable()(address)").strip().split()[0]
    supply = parse_uint(chain.call(stable, "totalSupply()(uint256)"))
    held = parse_uint(chain.call(usdc, "balanceOf(address)(uint256)", minter))
    return MinterReading(minted=supply, collateral=held * DECIMALS_SCALE, signed_amount=signed,
                         inflated_call_accepted=inflated_ok)


def replay_scenario_a(chain: Chain, deposit: int, multiplier: int) -> dict[str, MinterReading]:
    """Meme attaque que `ScenarioA.t.sol` sur les deux minters deployes sur `chain`.

    Args:
        chain: chaine ouverte (comptes deverrouilles).
        deposit: depot de l'attaquant, base units du collateral fictif (6 dec.).
        multiplier: montant signe = depot converti x `multiplier`.

    Returns:
        Lecture on-chain par variante (`vulnerable`, `protected`).
    """
    if len(chain.accounts) < 5:
        raise ContractsBackendError("anvil doit exposer au moins 5 comptes")
    admin, attacker, *guardians = chain.accounts[:5]
    signed = deposit * DECIMALS_SCALE * multiplier
    usdc = chain.deploy("src/MockUSDC.sol:MockUSDC", admin)
    _expect(chain.send(attacker, usdc, "mint(address,uint256)", attacker, str(2 * deposit)),
            "faucet MockUSDC")
    vulnerable = chain.deploy("src/VulnerableMinter.sol:VulnerableMinter", admin, usdc, admin,
                              attacker)
    protected = chain.deploy("src/ProtectedMinter.sol:ProtectedMinter", admin, usdc, admin,
                             attacker, str(RATE_ONE), f"[{','.join(guardians)}]")
    inflated = "completeSwap(uint256,address,uint256)"

    request_id = _request(chain, usdc, vulnerable, attacker, deposit)
    vulnerable_ok = chain.send(attacker, vulnerable, inflated, request_id, attacker, str(signed))
    readings = {"vulnerable": _reading(chain, usdc, vulnerable, signed, vulnerable_ok)}

    request_id = _request(chain, usdc, protected, attacker, deposit)
    protected_ok = chain.send(attacker, protected, inflated, request_id, attacker, str(signed))
    # Seul appel possible : « traiter la demande n°X ».
    _expect(chain.send(attacker, protected, "completeSwap(uint256)", request_id),
            "completeSwap(uint256)")
    readings["protected"] = _reading(chain, usdc, protected, signed, protected_ok)
    return readings


# --- Scenario C : balise de risque + faux marche de pret (#7) ----------------------------

# Garantie deposee (M-Ghost fictif, 18 dec.) et liquidite du marche (MockUSDC, 6 dec.), memes
# ordres de grandeur que `contracts/test/RiskBeacon.t.sol` (`_scenarioC`). Valeurs de demo.
C_ATTACK_COLLATERAL = 100_000 * 10**18
C_LEGIT_COLLATERAL = 50_000 * 10**18
C_MARKET_LIQUIDITY = 10_000_000 * 10**6
C_BASE_HAIRCUT_BPS = 500  # PROVISOIRE, comme le test de #7
C_SLOPE_HAIRCUT_BPS = 9_500  # PROVISOIRE, comme le test de #7
C_MAX_BORROW_SUSPECT = 1_000 * 10**18  # PROVISOIRE, comme le test de #7
C_INCIDENT_ID = 1


@dataclass(frozen=True)
class MarketReading:
    """Etat lu on-chain d'un faux marche de pret apres le rejeu du scenario C."""

    bad_debt: int  # dette non couverte par la garantie restante, base units du pret (6 dec.)
    loans_accepted: int
    legit_loans_refused: int
    attacker_borrowed: int


def _market_config(use_beacon: bool, ltv: float, ratio_threshold: float) -> str:
    """Tuple `MarketConfig` pour `--constructor-args`."""
    return (f"({str(use_beacon).lower()},{round(ltv * 10_000)},{C_BASE_HAIRCUT_BPS},"
            f"{C_SLOPE_HAIRCUT_BPS},{round(ratio_threshold * 10**18)},{C_MAX_BORROW_SUSPECT})")


def _deposit_and_borrow(chain: Chain, ghost: str, market: str, who: str, amount: int) -> int:
    """Depot de garantie puis emprunt de toute la capacite ; renvoie le montant emprunte."""
    _expect(chain.send(who, ghost, "approve(address,uint256)", market, str(amount)), "approve")
    _expect(chain.send(who, market, "deposit(uint256)", str(amount)), "deposit")
    capacity = parse_uint(chain.call(market, "capacityOf(address)(uint256)", who))
    if capacity == 0:
        return 0
    return capacity if chain.send(who, market, "borrow(uint256)", str(capacity)) else 0


def replay_scenario_c(chain: Chain, ltv: float, ratio_threshold: float) -> dict[str, MarketReading]:
    """Scenario C sur les vrais `RiskBeacon` et `MockLendingMarket` (#7).

    Le M-Ghost est `MockGhostRisk` (#7, `contracts/test/utils/`) tant que le contrat Ghost (#8)
    n'est pas livre. Meme sequence sur deux marches (sans / avec lecture de la balise) : un
    emprunteur legitime (Ghost propre) et l'attaquant (Ghost 100 % suspect) deposent et
    empruntent ; puis la part suspecte de la garantie detenue par le marche est detruite
    (multisig 2/3 simule par `MockGhostRisk.destroy`). Mauvaise creance = dette totale moins
    la garantie restante, au prix 1:1 PROVISOIRE de #7.
    """
    if len(chain.accounts) < 3:
        raise ContractsBackendError("anvil doit exposer au moins 3 comptes")
    admin, attacker, legit = chain.accounts[:3]
    ghost = chain.deploy("test/utils/MockGhostRisk.sol:MockGhostRisk", admin)
    beacon = chain.deploy("src/RiskBeacon.sol:RiskBeacon", admin, ghost)
    usdc = chain.deploy("src/MockUSDC.sol:MockUSDC", admin)
    readings: dict[str, MarketReading] = {}
    for name, use_beacon in (("without_beacon", False), ("with_beacon", True)):
        market = chain.deploy("src/MockLendingMarket.sol:MockLendingMarket", admin, ghost, usdc,
                              ghost, beacon, str(DECIMALS_SCALE),
                              _market_config(use_beacon, ltv, ratio_threshold))
        _expect(chain.send(admin, usdc, "mint(address,uint256)", market,
                           str(C_MARKET_LIQUIDITY)), "liquidite MockUSDC")
        _expect(chain.send(admin, ghost, "mint(address,uint256,uint256)", legit,
                           str(C_LEGIT_COLLATERAL), "0"), "Ghost propre")
        _expect(chain.send(admin, ghost, "mint(address,uint256,uint256)", attacker,
                           str(C_ATTACK_COLLATERAL), str(C_ATTACK_COLLATERAL)), "Ghost suspect")
        legit_borrowed = _deposit_and_borrow(chain, ghost, market, legit, C_LEGIT_COLLATERAL)
        attacker_borrowed = _deposit_and_borrow(chain, ghost, market, attacker,
                                                C_ATTACK_COLLATERAL)
        _expect(chain.send(admin, ghost, "destroy(address,uint256)", market, str(C_INCIDENT_ID)),
                "destruction 2/3 (simulee)")
        debt = parse_uint(chain.call(market, "totalDebt()(uint256)"))
        remaining = parse_uint(chain.call(ghost, "balanceOf(address)(uint256)", market))
        readings[name] = MarketReading(
            bad_debt=max(0, debt - remaining // DECIMALS_SCALE),
            loans_accepted=int(legit_borrowed > 0) + int(attacker_borrowed > 0),
            legit_loans_refused=int(legit_borrowed == 0),
            attacker_borrowed=attacker_borrowed,
        )
    return readings
