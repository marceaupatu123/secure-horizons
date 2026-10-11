// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../../src/MockUSDC.sol";
import {ProtectedMinter} from "../../src/ProtectedMinter.sol";
import {GhostedStable} from "../../src/GhostedStable.sol";
import {GhostToken} from "../../src/GhostToken.sol";

/// @notice Handler des tests d'invariants. Acteurs : 4 déposants honnêtes + `service`, détenteur
///         de la clé `SERVICE_ROLE` VOLÉE (qui peut aussi déposer). L'admin (taux) et les guardians
///         sont honnêtes (hypothèses H1, H2 du README).
/// @dev Toutes les valeurs attendues sont RECALCULÉES ici (formule et taux suivis par le handler),
///      sans appeler `quoteMint` du contrat.
contract ProtectedMinterHandler is Test {
    uint256 internal constant SCALE = 1e12;
    uint256 internal constant RATE_PRECISION = 1e18;
    uint256 internal constant MAX_DEPOSIT = 1e18; // unités 6 déc. (≤ 1e12 USDC fictifs)
    uint256 internal constant MIN_RATE = 1e6;
    uint256 internal constant MAX_RATE = 1e24;

    ProtectedMinter public minter;
    MockUSDC public usdc;
    GhostedStable public stable;
    GhostToken public ghost;
    address public service;
    address public admin;
    address[3] public guardians;
    address[5] public actors;

    /// @dev Taux courant tel que suivi par le handler (mis à jour seulement par l'admin honnête).
    uint256 public trackedRate;

    uint256[] public requestIds;
    mapping(uint256 => address) public depositorOf;
    mapping(uint256 => uint256) public depositOf;
    mapping(uint256 => uint256) public rateOf;
    mapping(uint256 => uint256) public expectedMint;
    mapping(uint256 => uint256) public completions;
    mapping(uint256 => uint256) public mintedObserved;
    mapping(uint256 => uint256) public supplyDelta;

    uint256 public ghost_sumDeposits;
    uint256 public ghost_sumExpectedAll;
    uint256 public ghost_sumMintedCompleted;
    mapping(address => uint256) public ghost_expectedFromDepositsOf;
    mapping(address => uint256) public ghost_expectedBalance;
    /// @dev Passe à true si une action interdite (clé volée, rejeu, demande inventée…) réussit.
    bool public ghost_unexpectedSuccess;
    /// @dev Passe à true si une action « doit réussir » (préconditions calculées ici) revert :
    ///      avec `fail_on_revert = false`, ce revert serait sinon avalé en silence.
    bool public ghost_unexpectedRevert;

    mapping(bytes32 => uint256) public calls;

    constructor(ProtectedMinter minter_, MockUSDC usdc_, address service_, address admin_, address[3] memory g) {
        minter = minter_;
        usdc = usdc_;
        stable = minter_.stable();
        ghost = minter_.ghost();
        service = service_;
        admin = admin_;
        guardians = g;
        trackedRate = minter_.rate();
        actors[0] = makeAddr("depositor0");
        actors[1] = makeAddr("depositor1");
        actors[2] = makeAddr("depositor2");
        actors[3] = makeAddr("depositor3");
        actors[4] = service_;
    }

    // ------------------------------------------------------------------ actions

    function requestSwap(uint256 actorSeed, uint256 amount) external {
        calls["requestSwap"]++;
        if (minter.paused()) return;
        address actor = actors[actorSeed % actors.length];
        amount = bound(amount, 1, MAX_DEPOSIT);
        uint256 expected = amount * SCALE * trackedRate / RATE_PRECISION;
        if (expected == 0) return;

        usdc.mint(actor, amount);
        vm.startPrank(actor);
        usdc.approve(address(minter), amount);
        // Doit réussir : non en pause, montant > 0, quote > 0 (recalculée ici).
        uint256 id;
        try minter.requestSwap(amount) returns (uint256 id_) {
            id = id_;
        } catch {
            vm.stopPrank();
            ghost_unexpectedRevert = true;
            return;
        }
        vm.stopPrank();
        calls["requestSwap_ok"]++;

        requestIds.push(id);
        depositorOf[id] = actor;
        depositOf[id] = amount;
        rateOf[id] = trackedRate;
        expectedMint[id] = expected;
        ghost_sumDeposits += amount;
        ghost_sumExpectedAll += expected;
        ghost_expectedFromDepositsOf[actor] += expected;
    }

    /// @notice La clé de service volée traite une demande existante (éventuellement déjà traitée).
    function completeSwap(uint256 idSeed) external {
        calls["completeSwap"]++;
        if (requestIds.length == 0) return;
        uint256 id = requestIds[idSeed % requestIds.length];
        address depositor = depositorOf[id];
        bool mustFail = minter.paused() || completions[id] > 0;
        uint256 balBefore = ghost.balanceOf(depositor);
        uint256 supplyBefore = ghost.supplyValue();

        vm.prank(service);
        try minter.completeSwap(id) {
            if (mustFail) {
                ghost_unexpectedSuccess = true;
                return;
            }
            calls["completeSwap_ok"]++;
            completions[id]++;
            mintedObserved[id] = ghost.balanceOf(depositor) - balBefore;
            supplyDelta[id] = ghost.supplyValue() - supplyBefore;
            ghost_sumMintedCompleted += expectedMint[id];
            ghost_expectedBalance[depositor] += expectedMint[id];
        } catch {
            // Demande existante, en attente, minter actif, rôle détenu : doit réussir.
            if (mustFail) calls["completeSwap_rejected"]++;
            else ghost_unexpectedRevert = true;
        }
    }

    /// @notice La clé volée tente de traiter une demande qui n'existe pas (inventée / future).
    function completeUnknown(uint256 id) external {
        calls["completeUnknown"]++;
        id = bound(id, minter.nextRequestId(), type(uint256).max);
        vm.prank(service);
        try minter.completeSwap(id) {
            ghost_unexpectedSuccess = true;
        } catch {}
    }

    /// @notice La clé volée tente de minter directement sur le token.
    function stolenKeyMintDirect(uint256 amount) external {
        calls["stolenKeyMintDirect"]++;
        vm.prank(service);
        try stable.mint(service, amount) {
            ghost_unexpectedSuccess = true;
        } catch {}
        // I4 révisé (#8) : émission directe de Ghost, doit échouer aussi.
        vm.prank(service);
        try ghost.issueFromMinter(service, amount, 0) {
            ghost_unexpectedSuccess = true;
        } catch {}
    }

    /// @notice La clé volée tente l'appel « à la Resolv » avec montant et destinataire.
    function stolenKeyInflatedCall(uint256 idSeed, uint256 amount) external {
        calls["stolenKeyInflatedCall"]++;
        uint256 id = requestIds.length == 0 ? idSeed : requestIds[idSeed % requestIds.length];
        vm.prank(service);
        (bool ok,) =
            address(minter).call(abi.encodeWithSignature("completeSwap(uint256,address,uint256)", id, service, amount));
        if (ok) ghost_unexpectedSuccess = true;
        // Variante « destinataire seul » (pas de montant) : doit échouer aussi.
        vm.prank(service);
        (ok,) = address(minter).call(abi.encodeWithSignature("completeSwap(uint256,address)", id, service));
        if (ok) ghost_unexpectedSuccess = true;
    }

    /// @notice La clé volée tente de changer le taux.
    function stolenKeySetRate(uint256 newRate) external {
        calls["stolenKeySetRate"]++;
        vm.prank(service);
        try minter.setRate(newRate) {
            ghost_unexpectedSuccess = true;
        } catch {}
    }

    /// @notice L'admin honnête change le taux (H1) : s'applique aux nouvelles demandes seulement.
    function adminSetRate(uint256 newRate) external {
        calls["adminSetRate"]++;
        newRate = bound(newRate, MIN_RATE, MAX_RATE);
        vm.prank(admin);
        // Doit réussir : admin honnête, taux > 0 (le setRate n'est pas soumis à la pause).
        try minter.setRate(newRate) {
            calls["adminSetRate_ok"]++;
            trackedRate = newRate;
        } catch {
            ghost_unexpectedRevert = true;
        }
    }

    /// @notice Un guardian honnête approuve une pause ou une dépause (peut échouer, sans attente).
    function guardianApprove(uint256 guardianSeed, bool toPause) external {
        calls["guardianApprove"]++;
        address g = guardians[guardianSeed % guardians.length];
        vm.prank(g);
        bool ok;
        if (toPause) {
            try minter.approvePause() {
                ok = true;
            } catch {}
        } else {
            try minter.approveUnpause() {
                ok = true;
            } catch {}
        }
        if (ok) calls["guardianApprove_ok"]++;
        else calls["guardianApprove_ko"]++;
    }

    // ------------------------------------------------------------------ vues pour les invariants

    function requestCount() external view returns (uint256) {
        return requestIds.length;
    }

    function actorCount() external view returns (uint256) {
        return actors.length;
    }
}
