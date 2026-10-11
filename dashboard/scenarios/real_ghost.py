"""Backend OPTIONNEL de la partie Ghost des scenarios B et N3 (#110) : vrais contrats
Token Ghost #8 (`GhostToken`, `ProtectedMinter`, `GuardianActions`, `GhostedStable`)
rejoues sur une chaine anvil locale et jetable.

Comme pour le scenario A (`real_contracts.replay_scenario_a`), ce chemin est OPT-IN
(`SH_DEMO_CONTRACTS_BACKEND=anvil`) et retombe AUTOMATIQUEMENT sur la simulation hors
chaîne (bandeau conserve) si Foundry ou `contracts/lib` manquent, ou si le rejeu echoue :
la CI ne depend jamais d'anvil. Les grandeurs lues on-chain (offre, reserve, montant
detruit, montant converti) sont des COMPTAGES sur une chaine locale, pas des mesures du
contrat deploye (cf. docs/CLAIMS.md).

Correspondance simule -> reel (voir dashboard/README.md pour le tableau complet) :

- lot de Ghost suspect credite dans `sim_contracts.GhostLedger` (ratio 1,0)
  -> `ProtectedMinter.requestSwap` + `completeSwap(id)` : `GhostToken.issueFromMinter`
     emet du M-Ghost frais au deposant ;
- ratio de soupçon par lot                   -> `delay(accounts, suspectAmounts, W)` du
     surveillant (`WATCHER_ROLE`) : seme `Sp` (soupçon en attente) sur chaque suspect ;
- saut de contagion (`GhostLedger.transfer`) -> `ghost.transfer(from, to, amount)`
     (ERC-20 standard) : le soupçon suit la valeur ;
- confirmation humaine 2/3 + destruction     -> `proposeDestroy(incidentId, targets)`
     (guardian1) puis `approveAction` (guardian2) : quorum 2/3, brule le soupçon confirme ;
- avance du temps au-dela de W                -> `evm_increaseTime` + `evm_mine` ;
- conversion 1:1 des legitimes apres W        -> `ghost.convert(amount)`.

N3 (fausse alerte) rejoue le MEME squelette, mais le surveillant seme un soupçon NUL
(`delay(sink, 0, W)` : circulation permise, conversion suspendue), aucune confirmation
2/3 n'arrive, puis la fenetre revient seule a la normale et le legitime convertit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from dashboard.scenarios.real_contracts import (
    ContractsBackendError,
    _expect,
    parse_uint,
)
from dashboard.scenarios.real_contracts import Chain  # Protocol, implemente par AnvilChain

# Fixtures du M-Ghost (#8), IDENTIQUES a `contracts/test/utils/BaseTest.sol` (PAS des mesures) :
# W = 600 s, creneau 60 s, maxExtensionFactor 6, budget 2000 bps, seuils de conversion a 0,
# marges a 0, restitutionClaimDelay 1 jour.
GHOST_W = 600
GHOST_SLOT = 60
GHOST_FIXTURE_CONFIG = "(600,60,6,2000,0,0,0,0,0,86400)"
# ProtectedMinter : taux 1e18 = 1:1, collateral 6 dec. -> stable 18 dec. (facteur 1e12).
RATE_ONE = 10**18
DECIMALS_SCALE = 10**12

# Montants fictifs (6 dec. de collateral), petits et coherents avec le profil « petits
# montants » de B dans catalog.py. Base units de MockUSDC (6 dec.).
B_ATTACKER_DEPOSIT = 100_000_000  # 100 USDC : Ghost emis = 100e18
B_LEGIT_DEPOSIT = 50_000_000  # 50 USDC chacun : Ghost emis = 50e18
B_CONTAGION_HOP = 40 * 10**18  # un saut de contagion de l'attaquant vers un relais (gpUSD, 18 dec.)
# Offre de fond legitime (comme `dave` dans GhostWatcher.t.sol) : donne au surveillant la marge
# du budget de quarantaine (2000 bps = 20 % de supplyValue), sinon `delay` revert budget depasse.
B_BACKGROUND_DEPOSIT = 10_000_000_000  # 10 000 USDC : Ghost emis = 10 000e18


@dataclass(frozen=True)
class GhostReading:
    """Etat lu on-chain apres le rejeu de la partie Ghost d'un scenario (18 decimales).

    Tous les montants sont en base units du M-Ghost / M (18 dec.).
    """

    destroyed: int  # Ghost suspect detruit par la destruction 2/3 (totalSuspectBurned)
    legit_converted: int  # M emis aux legitimes par conversion apres W
    attacker_converted: int  # M emis a l'attaquant par conversion (doit valoir 0 sous B)
    supply_value_before: int  # ghost.supplyValue() avant destruction / conversion
    supply_value_after: int  # ghost.supplyValue() a la fin du rejeu
    reserve: int  # ghost.reserve() a la fin (totalIssued - supplyValue - insuranceFund)
    destroy_confirmed: bool  # une destruction 2/3 a-t-elle eu lieu (B oui, N3 non)


# --- Helpers chaine ----------------------------------------------------------


def _increase_time(chain: Chain, seconds: int) -> None:
    """Avance l'horloge d'anvil de `seconds` puis mine un bloc (evm_increaseTime + evm_mine)."""
    # `cast rpc` passe par la meme pile que les autres appels : on reutilise AnvilChain._cast
    # via l'API publique `call` serait impossible (pas une lecture de contrat), donc on
    # s'appuie sur l'attribut interne `_cast` quand il existe (AnvilChain), sinon on no-op
    # (FakeChain controle son horloge autrement).
    cast = getattr(chain, "_cast", None)
    rpc_url = getattr(chain, "rpc_url", None)
    if cast is None or not rpc_url:
        advance = getattr(chain, "advance_time", None)
        if advance is not None:
            advance(seconds)
        return
    cast("rpc", "evm_increaseTime", json.dumps(seconds), "--rpc-url", rpc_url)
    cast("rpc", "evm_mine", "--rpc-url", rpc_url)


def _grant_watcher(chain: Chain, ghost: str, admin: str, watcher: str) -> None:
    """Donne `WATCHER_ROLE` a `watcher` (admin le detient par defaut, cf. constructeur)."""
    role = chain.call(ghost, "WATCHER_ROLE()(bytes32)").strip().split()[0]
    _expect(chain.send(admin, ghost, "grantRole(bytes32,address)", role, watcher),
            "grantRole(WATCHER_ROLE)")


def _mint_ghost(chain: Chain, usdc: str, minter: str, who: str, usdc_amount: int) -> int:
    """Depot de `usdc_amount` (6 dec.) par `who`, traite par la cle de service : `who` recoit
    `usdc_amount x 1e12` M-Ghost frais. Renvoie le montant Ghost emis (18 dec.)."""
    _expect(chain.send(who, usdc, "approve(address,uint256)", minter, str(usdc_amount)),
            "approve collateral")
    request_id = str(parse_uint(chain.call(minter, "nextRequestId()(uint256)")))
    _expect(chain.send(who, minter, "requestSwap(uint256)", str(usdc_amount)), "requestSwap")
    # La cle de service (volee) ne peut que « traiter la demande n°X » : elle n'a NI montant NI
    # destinataire. C'est le 2e compte anvil (= attaquant), fixe au deploiement.
    _expect(chain.send(_SERVICE_HOLDER[0], minter, "completeSwap(uint256)", request_id),
            "completeSwap(uint256)")
    return usdc_amount * DECIMALS_SCALE


# Rempli par `_deploy_world` : le compte « service » (= attaquant) deverrouille sur anvil.
_SERVICE_HOLDER: list[str] = [""]


def _deploy_world(chain: Chain) -> tuple[str, str, str, dict[str, str]]:
    """Deploie MockUSDC -> ProtectedMinter -> GhostToken ; renvoie (usdc, minter, ghost, roles).

    Les comptes anvil deverrouilles tiennent les roles : admin, service (= attaquant),
    guardian1..3, watcher, et des legitimes.
    """
    if len(chain.accounts) < 8:
        raise ContractsBackendError("anvil doit exposer au moins 8 comptes")
    admin, attacker, g1, g2, g3, watcher, legit1, legit2 = chain.accounts[:8]
    _SERVICE_HOLDER[0] = attacker
    usdc = chain.deploy("src/MockUSDC.sol:MockUSDC", admin)
    guardians = f"[{g1},{g2},{g3}]"
    minter = chain.deploy("src/ProtectedMinter.sol:ProtectedMinter", admin, usdc, admin,
                          attacker, str(RATE_ONE), guardians, GHOST_FIXTURE_CONFIG)
    ghost = chain.call(minter, "ghost()(address)").strip().split()[0]
    _grant_watcher(chain, ghost, admin, watcher)
    roles = {"admin": admin, "attacker": attacker, "g1": g1, "g2": g2, "g3": g3,
             "watcher": watcher, "legit1": legit1, "legit2": legit2}
    return usdc, minter, ghost, roles


def _fund(chain: Chain, usdc: str, who: str, amount: int) -> None:
    _expect(chain.send(who, usdc, "mint(address,uint256)", who, str(amount)), "faucet MockUSDC")


def _supply_value(chain: Chain, ghost: str) -> int:
    return parse_uint(chain.call(ghost, "supplyValue()(uint256)"))


def _m_balance(chain: Chain, ghost: str, who: str) -> int:
    """Solde de M (`GhostedStable`, 18 dec.) de `who`."""
    underlying = chain.call(ghost, "underlying()(address)").strip().split()[0]
    return parse_uint(chain.call(underlying, "balanceOf(address)(uint256)", who))


def _destroy_2of3(chain: Chain, ghost: str, roles: dict[str, str], incident_id: int,
                  targets: list[str]) -> None:
    """guardian1 propose la destruction de l'incident, guardian2 approuve (quorum 2/3)."""
    targets_arg = "[" + ",".join(targets) + "]"
    _expect(chain.send(roles["g1"], ghost, "proposeDestroy(uint256,address[])",
                       str(incident_id), targets_arg), "proposeDestroy")
    proposal_id = str(parse_uint(chain.call(ghost, "proposalCount()(uint256)")))
    _expect(chain.send(roles["g2"], ghost, "approveAction(uint256)", proposal_id),
            "approveAction (quorum 2/3)")


# --- Scenario B : detection + destruction 2/3 --------------------------------


def replay_scenario_b(chain: Chain) -> GhostReading:
    """Rejoue la partie Ghost de B sur les vrais contrats #8 (voir l'en-tete du module).

    Sequence :
      1. le minter protege emet du Ghost a l'attaquant et a deux legitimes ;
      2. l'attaquant fait circuler son Ghost (un saut de contagion vers un relais) ;
      3. le surveillant (`WATCHER_ROLE`) retarde les suspects (seme `Sp`) via `delay` ;
      4. les guardians confirment la destruction en 2/3 (`proposeDestroy` + `approveAction`) ;
      5. on avance le temps au-dela de W (`evm_increaseTime` + `evm_mine`) ;
      6. les legitimes convertissent (`convert`) ; l'attaquant tente de convertir (echoue).
    """
    usdc, minter, ghost, roles = _deploy_world(chain)
    attacker, legit1, legit2 = roles["attacker"], roles["legit1"], roles["legit2"]
    relay = roles["g3"]  # un compte deverrouille sert de relais de contagion (hors roles actifs)
    background = roles["admin"]  # offre de fond legitime (marge du budget de quarantaine)

    # 1. Emission du Ghost.
    _fund(chain, usdc, background, B_BACKGROUND_DEPOSIT)
    _fund(chain, usdc, attacker, B_ATTACKER_DEPOSIT)
    _fund(chain, usdc, legit1, B_LEGIT_DEPOSIT)
    _fund(chain, usdc, legit2, B_LEGIT_DEPOSIT)
    _mint_ghost(chain, usdc, minter, background, B_BACKGROUND_DEPOSIT)
    attacker_ghost = _mint_ghost(chain, usdc, minter, attacker, B_ATTACKER_DEPOSIT)
    _mint_ghost(chain, usdc, minter, legit1, B_LEGIT_DEPOSIT)
    _mint_ghost(chain, usdc, minter, legit2, B_LEGIT_DEPOSIT)

    # 2. Un saut de contagion : l'attaquant envoie une partie de son Ghost a un relais.
    hop = min(B_CONTAGION_HOP, attacker_ghost)
    _expect(chain.send(attacker, ghost, "transfer(address,uint256)", relay, str(hop)),
            "saut de contagion (transfer)")

    # 3. Le surveillant retarde l'attaquant et le relais contamine (seme tout leur solde).
    suspects = f"[{attacker},{relay}]"
    attacker_bal = parse_uint(chain.call(ghost, "balanceOf(address)(uint256)", attacker))
    relay_bal = parse_uint(chain.call(ghost, "balanceOf(address)(uint256)", relay))
    amounts = f"[{attacker_bal},{relay_bal}]"
    _expect(chain.send(roles["watcher"], ghost, "delay(address[],uint256[],uint64)",
                       suspects, amounts, str(GHOST_W)), "delay (surveillant)")
    incident_id = parse_uint(chain.call(ghost, "openIncidentId()(uint256)"))

    supply_before = _supply_value(chain, ghost)

    # 4. Destruction confirmee en 2/3.
    _destroy_2of3(chain, ghost, roles, incident_id, [attacker, relay])
    destroyed = parse_uint(chain.call(ghost, "totalSuspectBurned()(uint256)"))

    # 5. On passe la fenetre W (plus une marge d'un creneau).
    _increase_time(chain, GHOST_W + GHOST_SLOT)

    # 6. Les legitimes convertissent tout leur solde ; l'attaquant tente et echoue.
    legit_converted = 0
    for legit in (legit1, legit2):
        bal = parse_uint(chain.call(ghost, "convertibleOf(address)(uint256)", legit))
        if bal:
            m_before = _m_balance(chain, ghost, legit)
            _expect(chain.send(legit, ghost, "convert(uint256)", str(bal)), "convert (legitime)")
            legit_converted += _m_balance(chain, ghost, legit) - m_before

    attacker_before = _m_balance(chain, ghost, attacker)
    attacker_bal_now = parse_uint(chain.call(ghost, "balanceOf(address)(uint256)", attacker))
    if attacker_bal_now:
        # Soupçon detruit : la part suspecte est verrouillee / brulee, la conversion revert.
        chain.send(attacker, ghost, "convert(uint256)", str(attacker_bal_now))
    attacker_converted = _m_balance(chain, ghost, attacker) - attacker_before

    return GhostReading(
        destroyed=destroyed,
        legit_converted=legit_converted,
        attacker_converted=attacker_converted,
        supply_value_before=supply_before,
        supply_value_after=_supply_value(chain, ghost),
        reserve=parse_uint(chain.call(ghost, "reserve()(uint256)")),
        destroy_confirmed=True,
    )


# --- N3 : fausse alerte auto-expirante ---------------------------------------


def replay_scenario_n3(chain: Chain) -> GhostReading:
    """Rejoue la partie Ghost de N3 : burst legitime, retard SANS soupçon, aucune confirmation,
    la fenetre revient seule a la normale et le legitime convertit (voir catalog.run_n3).

    Sequence :
      1. un legitime (adresse ancienne, « sink ») recoit du Ghost frais (ratio 0) ;
      2. le surveillant retarde ce compte en semant un soupçon NUL (`delay(sink, 0, W)`) :
         conversion suspendue, mais aucune valeur n'est marquee suspecte ;
      3. aucune confirmation 2/3 n'arrive (silence) ;
      4. on avance au-dela de l'echeance de l'incident : la fenetre revient a la normale ;
      5. le legitime convertit tout son solde (`convert`).
    """
    usdc, minter, ghost, roles = _deploy_world(chain)
    sink = roles["legit1"]
    background = roles["admin"]  # offre de fond legitime (marge du budget de quarantaine)

    _fund(chain, usdc, background, B_BACKGROUND_DEPOSIT)
    _fund(chain, usdc, sink, B_LEGIT_DEPOSIT)
    _mint_ghost(chain, usdc, minter, background, B_BACKGROUND_DEPOSIT)
    _mint_ghost(chain, usdc, minter, sink, B_LEGIT_DEPOSIT)

    # Retard sans soupçon : circulation permise, conversion suspendue (cf. GhostWatcher.t.sol).
    _expect(chain.send(roles["watcher"], ghost, "delay(address[],uint256[],uint64)",
                       f"[{sink}]", "[0]", str(GHOST_W)), "delay sans soupçon")
    incident_id = parse_uint(chain.call(ghost, "openIncidentId()(uint256)"))
    expires_at = _incident_expiry(chain, ghost, incident_id)

    supply_before = _supply_value(chain, ghost)

    # Aucune confirmation : on laisse l'incident expirer (silence -> retour automatique).
    _increase_time(chain, GHOST_W + GHOST_SLOT)
    # S'assurer qu'on est bien au-dela de l'echeance de l'incident ET de l'echeance de maturite.
    now = _block_timestamp(chain)
    if now <= expires_at:
        _increase_time(chain, int(expires_at - now) + GHOST_SLOT)

    legit_converted = 0
    bal = parse_uint(chain.call(ghost, "convertibleOf(address)(uint256)", sink))
    if bal:
        m_before = _m_balance(chain, ghost, sink)
        _expect(chain.send(sink, ghost, "convert(uint256)", str(bal)), "convert apres retour")
        legit_converted = _m_balance(chain, ghost, sink) - m_before

    return GhostReading(
        destroyed=parse_uint(chain.call(ghost, "totalSuspectBurned()(uint256)")),
        legit_converted=legit_converted,
        attacker_converted=0,
        supply_value_before=supply_before,
        supply_value_after=_supply_value(chain, ghost),
        reserve=parse_uint(chain.call(ghost, "reserve()(uint256)")),
        destroy_confirmed=False,
    )


def _incident_expiry(chain: Chain, ghost: str, incident_id: int) -> int:
    """`expiresAt` de l'incident (2e champ du tuple `incidents(id)`)."""
    raw = chain.call(ghost, "incidents(uint256)(uint64,uint64,bool,uint256)", str(incident_id))
    tokens = [t for t in raw.replace("\n", " ").split() if t]
    # Format cast : « openedAt expiresAt confirmed extendedBalance » (valeurs sur lignes/espaces).
    nums = [t for t in tokens if t.replace("x", "").replace("X", "").isalnum()
            and (t.isdigit() or t.startswith(("0x", "0X")))]
    return int(nums[1], 0) if len(nums) > 1 else 0


def _block_timestamp(chain: Chain) -> int:
    """Horodatage du bloc courant (lecture via le minuteur d'anvil quand disponible)."""
    cast = getattr(chain, "_cast", None)
    rpc_url = getattr(chain, "rpc_url", None)
    if cast is None or not rpc_url:
        getter = getattr(chain, "block_timestamp", None)
        return int(getter()) if getter is not None else 0
    block = json.loads(cast("rpc", "eth_getBlockByNumber", "latest", "false", "--rpc-url",
                            rpc_url))
    return int(block["timestamp"], 0)
