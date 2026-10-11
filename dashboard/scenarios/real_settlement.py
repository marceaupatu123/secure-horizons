"""Backend OPTIONNEL du scenario D (#110) : vrais contrats Token Ghost (#8) + couche de reglement
§10bis (#84 : `SettlementRouter`, `AssetVault`, `AssetGhost`) rejoues sur une chaine anvil locale
et jetable.

Comme pour A, C et la partie Ghost de B/N3, ce chemin est OPT-IN (`SH_DEMO_CONTRACTS_BACKEND=anvil`)
et retombe AUTOMATIQUEMENT sur la simulation (bandeau conserve) si Foundry ou `contracts/lib`
manquent, ou si le rejeu echoue : la CI ne depend jamais d'anvil. Les grandeurs lues on-chain
(M' detruit, argent restitue, perte des speculateurs) sont des COMPTAGES sur une chaine locale,
pas des mesures du contrat deploye (cf. docs/CLAIMS.md).

Cas rejoue : §10bis cas 2bis (prix qui montent), modele sur `contracts/test/ScenarioSettlement.t.sol`
(`test_cas2bis_risingPrice_lastHolderLosesMarkup`). Il demontre la propriete centrale de la
decision §10bis : **le voleur ne garde rien, le protocole ne garde rien, et le risque est porte
par le marche secondaire du M' pur** (ici l'acheteur final qui a paye la marge).

Sequence :
  1. MockUSDC -> ProtectedMinter -> GhostToken (#8) + `SettlementRouter` (sur le M-Ghost) deployes ;
     une offre de fond legitime donne la marge du budget de quarantaine ;
  2. le minter protege emet du M' frauduleux au voleur (cle de service volee) ;
  3. le surveillant (`WATCHER_ROLE`) marque le voleur 100 % suspect (`delay`) ;
  4. un intermediaire A2 achete le M' du voleur via le routeur en bloquant du vrai USDC au coffre
     (`buyWithAsset`) : le voleur ne recoit que du Ghost de paiement ; le soupçon suit le M' vers A2 ;
  5. A2 revend le M' (devenu PUR) a l'acheteur final A40, paye hors routeur a un prix PLUS ELEVE
     (`sellPure`) : l'intermediaire encaisse la marge ;
  6. destruction 2/3 CONFIRMEE : le M' suspect de A40 est brule (jambe M', #8), puis le Ghost de
     paiement du voleur est brule et une racine de Merkle restitue a A40 l'argent bloque du voleur
     (jambe paiement, coffre §10bis) ;
  7. lectures on-chain : perte protocole (M' reel emis contre du suspect) = 0, perte speculateur
     = ce que A40 a paye moins ce qu'il a recupere (la marge), coffre vide, voleur a 0.
"""

from __future__ import annotations

from dataclasses import dataclass

from dashboard.scenarios.real_contracts import (
    Chain,
    ContractsBackendError,
    _delay_full,
    _deploy_ghost_world,
    _destroy_2of3_target,
    _expect,
    _fund_and_mint_ghost,
    parse_uint,
)

# Montants fictifs (6 dec. de MockUSDC / M'). Base units de MockUSDC (6 dec.).
D_THIEF_DEPOSIT = 10 * 10**6  # 10 USDC deposes par le voleur -> 10e18 de M' frauduleux
D_A2_PRICE = 10 * 10**6  # A2 paie 10 USDC (bloques au coffre) pour le M' du voleur
D_A40_PRICE = 15 * 10**6  # A40 paie 15 USDC a A2 (hors routeur) : la marge est de 5 USDC
# Offre de fond legitime (marge du budget de quarantaine : 2000 bps = 20 % de supplyValue).
D_BACKGROUND_DEPOSIT = 2_000 * 10**6

_ZERO_ADDR = "0x0000000000000000000000000000000000000000"


@dataclass(frozen=True)
class SettlementReading:
    """Etat lu on-chain apres le rejeu de D sur la couche de reglement §10bis (#84)."""

    mprime_destroyed: int  # M' suspect brule a la destruction 2/3 (18 dec.)
    thief_asset_kept: int  # vrai USDC garde par le voleur a la fin (doit valoir 0), 6 dec.
    protocol_loss: int  # vrai M emis contre du M' suspect (doit valoir 0, §10bis), 18 dec.
    speculator_loss: int  # USDC paye par A40 moins restitue (la marge perdue), 6 dec.
    intermediary_asset: int  # USDC garde par A2 (son prix de vente), 6 dec.
    last_holder_restituted: int  # USDC restitue a A40 (l'argent bloque du voleur), 6 dec.
    vault_locked_end: int  # actif restant bloque au coffre a la fin (doit valoir 0), 6 dec.


def _approve(chain: Chain, token: str, owner: str, spender: str, amount: int) -> None:
    _expect(chain.send(owner, token, "approve(address,uint256)", spender, str(amount)), "approve")


def _fund_usdc(chain: Chain, usdc: str, who: str, amount: int) -> None:
    _expect(chain.send(who, usdc, "mint(address,uint256)", who, str(amount)), "faucet MockUSDC")


def _usdc_balance(chain: Chain, usdc: str, who: str) -> int:
    return parse_uint(chain.call(usdc, "balanceOf(address)(uint256)", who))


def _m_balance(chain: Chain, ghost: str, who: str) -> int:
    """Solde de vrai M (`GhostedStable`, 18 dec.) de `who` : perte protocole si un suspect a minte."""
    underlying = chain.call(ghost, "underlying()(address)").strip().split()[0]
    return parse_uint(chain.call(underlying, "balanceOf(address)(uint256)", who))


def _vault_2of3(chain: Chain, vault: str, guardians: list[str], signature: str, *args: str) -> None:
    """Les deux premiers guardians votent l'action du coffre (quorum 2/3 generique §10bis)."""
    _expect(chain.send(guardians[0], vault, signature, *args), f"{signature} (guardian1)")
    _expect(chain.send(guardians[1], vault, signature, *args), f"{signature} (guardian2)")


def _restitution_root(chain: Chain, to: str, amount: int, nonce: int) -> str:
    """Racine de Merkle a UNE feuille (preuve vide) : la racine EST la feuille,
    `keccak256(bytes.concat(keccak256(abi.encode(address,uint256,uint256))))`.

    Calculee on-chain via `cast` (anvil) pour rester exactement aligne sur `AssetVault.restitute`,
    sans reimplementer keccak/abi en Python. La FakeChain fournit `settlement_leaf` a la place.
    """
    getter = getattr(chain, "settlement_leaf", None)
    if getter is not None:  # FakeChain : feuille deterministe locale
        return getter(to, amount, nonce)
    cast = getattr(chain, "_cast", None)
    rpc_url = getattr(chain, "rpc_url", None)
    if cast is None or not rpc_url:
        raise ContractsBackendError("calcul de la racine de restitution indisponible")
    inner = cast("abi-encode", "f(address,uint256,uint256)", to, str(amount), str(nonce)).strip()
    inner_hash = cast("keccak", inner).strip().split()[0]
    return cast("keccak", inner_hash).strip().split()[0]


def replay_scenario_d(chain: Chain) -> SettlementReading:
    """Rejoue D sur les vrais contrats #8 + §10bis #84 (voir l'en-tete du module)."""
    if len(chain.accounts) < 8:
        raise ContractsBackendError("anvil doit exposer au moins 8 comptes")
    admin, thief, a2, a40, watcher = chain.accounts[:5]
    guardians = chain.accounts[5:8]
    background = admin  # offre de fond legitime (marge du budget de quarantaine)

    usdc, minter, ghost = _deploy_ghost_world(chain, admin, thief, guardians, watcher)
    router = chain.deploy("src/SettlementRouter.sol:SettlementRouter", admin, ghost)

    # 1. Offre de fond + M' frauduleux emis au voleur (la cle de service volee traite la demande).
    _fund_and_mint_ghost(chain, usdc, minter, thief, background, D_BACKGROUND_DEPOSIT)
    mprime = _fund_and_mint_ghost(chain, usdc, minter, thief, thief, D_THIEF_DEPOSIT)

    # 2. Le surveillant marque le voleur 100 % suspect.
    incident_id = _delay_full(chain, ghost, watcher, thief, mprime)

    # 3. A2 achete le M' du voleur via le routeur en bloquant 10 USDC au coffre.
    _fund_usdc(chain, usdc, a2, D_A2_PRICE)
    _approve(chain, usdc, a2, router, D_A2_PRICE)
    _approve(chain, ghost, thief, router, mprime)
    _expect(chain.send(a2, router, "buyWithAsset(address,uint256,address,uint256)",
                       thief, str(mprime), usdc, str(D_A2_PRICE)), "buyWithAsset")
    vault = chain.call(router, "vaultOf(address)(address)", usdc).strip().split()[0]

    # 4. A40 paie A2 un prix PLUS ELEVE (hors routeur) puis achete le M' pur de A2 (`sellPure`).
    _fund_usdc(chain, usdc, a40, D_A40_PRICE)
    _expect(chain.send(a40, usdc, "transfer(address,uint256)", a2, str(D_A40_PRICE)),
            "paiement hors routeur A40 -> A2")
    _approve(chain, ghost, a2, router, mprime)
    _expect(chain.send(a40, router, "sellPure(address,uint256,address,uint256)",
                       a2, str(mprime), _ZERO_ADDR, "0"), "sellPure")

    # 5. Destruction 2/3 (jambe M') : le M' suspect de A40 est brule.
    _destroy_2of3_target(chain, ghost, guardians, incident_id, a40)
    mprime_destroyed = parse_uint(chain.call(ghost, "totalSuspectBurned()(uint256)"))

    # 6. Jambe paiement : bruler le Ghost de paiement du voleur (libere l'argent bloque), puis
    #    publier une racine de Merkle a une feuille et restituer a A40 l'argent bloque du voleur.
    _vault_2of3(chain, vault, guardians, "burnSeedPayment(address,uint256,uint256)",
                thief, str(D_THIEF_DEPOSIT), "0")
    root = _restitution_root(chain, a40, D_A2_PRICE, 0)
    _vault_2of3(chain, vault, guardians, "confirmRestitutionRoot(bytes32)", root)
    _expect(chain.send(a40, vault, "restitute(address,uint256,uint256,bytes32[])",
                       a40, str(D_A2_PRICE), "0", "[]"), "restitute")

    # 7. Lectures on-chain.
    return SettlementReading(
        mprime_destroyed=mprime_destroyed,
        thief_asset_kept=_usdc_balance(chain, usdc, thief),
        # Perte protocole = vrai M emis contre du M' suspect. Le M' reste en quarantaine (Ghost) :
        # aucun vrai M n'a ete minte frauduleusement. On lit les soldes M de tous les acteurs.
        protocol_loss=(_m_balance(chain, ghost, thief) + _m_balance(chain, ghost, a2)
                       + _m_balance(chain, ghost, a40)),
        # Perte speculateur = ce que A40 a paye moins ce qu'il a recupere (la marge).
        speculator_loss=max(0, D_A40_PRICE - _usdc_balance(chain, usdc, a40)),
        intermediary_asset=_usdc_balance(chain, usdc, a2),
        last_holder_restituted=parse_uint(chain.call(vault, "totalRestituted()(uint256)")),
        vault_locked_end=parse_uint(chain.call(vault, "locked()(uint256)")),
    )
