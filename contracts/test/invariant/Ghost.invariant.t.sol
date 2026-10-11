// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {StdInvariant} from "forge-std/StdInvariant.sol";
import {console} from "forge-std/console.sol";
import {BaseTest} from "../utils/BaseTest.sol";
import {ProtectedMinter} from "../../src/ProtectedMinter.sol";
import {GhostedStable} from "../../src/GhostedStable.sol";
import {GhostConfig, GhostToken} from "../../src/GhostToken.sol";
import {GhostHandler} from "./GhostHandler.sol";

/// @notice Invariants du M-Ghost (#8, design §8.2), VÉRIFIÉS PAR FUZZING (jamais « prouvés »).
///         (a) rien ne sort avant W ; (b) tranches == modèle d'ombre ; (c) conservation du
///         soupçon et verrou partiel ; (d) destruction exacte ; (e) solvabilité et réserve ;
///         (f) bornes du surveillant. Le handler tourne avec deux configurations (seuils à 0 et
///         seuils > 0). Hypothèses H1–H5 : contracts/README.md.
abstract contract GhostInvariantBase is StdInvariant, BaseTest {
    ProtectedMinter internal pm;
    GhostedStable internal m;
    GhostToken internal ghost;
    GhostHandler internal handler;
    address internal eve = makeAddr("eve");
    address internal whale = makeAddr("whale");

    function _cfg() internal pure virtual returns (GhostConfig memory);

    function setUp() public {
        vm.warp(1_200_000);
        _deployUsdc();
        (pm, m, ghost) = _deployProtectedWith(_cfg());
        address[] memory actors = new address[](5);
        (actors[0], actors[1], actors[2], actors[3], actors[4]) = (alice, bob, carol, attacker, eve);
        handler = new GhostHandler(pm, usdc, service, watcher, _guardians(), actors, whale, 20_000e6);

        bytes4[] memory s = new bytes4[](15);
        s[0] = GhostHandler.mint.selector;
        s[1] = GhostHandler.transferGhost.selector;
        s[2] = GhostHandler.transferM.selector;
        s[3] = GhostHandler.convert.selector;
        s[4] = GhostHandler.convertSuspectPart.selector;
        s[5] = GhostHandler.warp.selector;
        s[6] = GhostHandler.watcherDelay.selector;
        s[7] = GhostHandler.watcherChainIncident.selector;
        s[8] = GhostHandler.watcherForbidden.selector;
        s[9] = GhostHandler.guardianDestroy.selector;
        s[10] = GhostHandler.guardianExtend.selector;
        s[11] = GhostHandler.guardianClear.selector;
        s[12] = GhostHandler.guardianRestitute.selector;
        s[13] = GhostHandler.sweep.selector;
        s[14] = GhostHandler.guardianPause.selector;
        targetSelector(FuzzSelector({addr: address(handler), selectors: s}));
        targetContract(address(handler));
    }

    function _actors() internal view returns (address[] memory a) {
        uint256 n = handler.actorCount();
        a = new address[](n);
        for (uint256 i = 0; i < n; i++) {
            a[i] = handler.actors(i);
        }
    }

    /// @notice (a) Σ entrées d'horodatage ≤ now − W ≥ Σ converti + Σ convertible : aucune valeur
    ///         ne devient convertible avant W après son entrée en Ghost.
    function invariant_a_nothingOutBeforeW() public view {
        address[] memory a = _actors();
        uint256 out = handler.ghost_converted();
        for (uint256 i = 0; i < a.length; i++) {
            out += ghost.convertibleOf(a[i]);
        }
        assertGe(handler.ghost_entriesOlderThanW(), out);
        assertEq(ghost.totalConverted(), handler.ghost_converted());
    }

    /// @notice (b) Tranches du contrat == modèle d'ombre (échéances arrondies, plus anciennes
    ///         d'abord, destruction des plus récentes) ; contrôles par transfert dans le handler.
    function invariant_b_bucketsMatchShadow() public view {
        assertFalse(handler.ghost_bucketViolation(), handler.ghost_firstFailure());
        address[] memory a = _actors();
        for (uint256 i = 0; i < a.length; i++) {
            assertEq(ghost.balanceOf(a[i]), handler.shadowTotal(a[i]), "balance");
            assertEq(ghost.maturedEffectiveOf(a[i]), handler.shadowMaturedEffective(a[i]), "matured part");
            (uint64[] memory sm, uint256[] memory sv) = handler.shadowLive(a[i]);
            (uint64[] memory cm, uint256[] memory cv) = ghost.bucketsOf(a[i]);
            uint256 k;
            for (uint256 j = 0; j < cm.length; j++) {
                if (cm[j] <= block.timestamp) continue; // échue non réglée : comptée dans la part échue
                assertEq(cm[j], sm[k], "maturity");
                assertEq(cv[j], sv[k], "amount");
                k++;
            }
            assertEq(k, sm.length, "bucket count");
        }
    }

    /// @notice (c) Σ (Sc + Sp) == semé − brûlé − expiré − blanchi ; Sc + Sp ≤ solde ; aucune
    ///         conversion n'a laissé `balanceOf < S`.
    function invariant_c_suspicionConserved() public view {
        assertFalse(handler.ghost_lockViolation(), handler.ghost_firstFailure());
        address[] memory a = _actors();
        uint256 sum;
        for (uint256 i = 0; i < a.length; i++) {
            (uint256 sc, uint256 sp,) = ghost.suspectRawOf(a[i]);
            sum += sc + sp;
            assertLe(sc + sp, ghost.balanceOf(a[i]), "suspicion above balance");
            assertLe(ghost.effectiveSuspectOf(a[i]), ghost.balanceOf(a[i]));
        }
        assertEq(
            sum,
            ghost.totalSeeded() - ghost.totalSuspectBurned() - ghost.totalSuspectExpired()
                - ghost.totalSuspectCleared(),
            "suspicion created or lost"
        );
    }

    /// @notice (d) Chaque destruction a brûlé exactement le soupçon confirmé, sans toucher au M
    ///         ni au soupçon en attente d'un autre incident vivant.
    function invariant_d_destroyExact() public view {
        assertFalse(handler.ghost_destroyViolation(), handler.ghost_firstFailure());
    }

    /// @notice (e) supplyValue ≤ totalIssued == totalMinted ≤ Σ dépôts × taux ; réserve exacte
    ///         sans saturation ; Σ restitué ≤ Σ brûlé + Σ marges.
    function invariant_e_solvency() public view {
        uint256 issued = ghost.totalIssued();
        assertEq(issued, pm.totalMinted());
        assertLe(issued, handler.ghost_sumDepositsTimesRate());
        assertLe(ghost.supplyValue(), issued);
        assertGe(issued, ghost.supplyValue() + ghost.insuranceFund(), "reserve saturated");
        assertEq(ghost.reserve(), issued - ghost.supplyValue() - ghost.insuranceFund());
        assertLe(ghost.totalRestituted(), ghost.totalBurned() + ghost.totalFees());
        assertFalse(handler.ghost_restitutionOverReserve());
        assertEq(usdc.balanceOf(address(pm)), pm.totalDeposited());
    }

    /// @notice (f) Bornes du surveillant : extensions == modèle (monotones, séries ≤ factor × W,
    ///         séparées d'au moins W), budget, Sp jamais baissé par lui ; `extendedBalance` de
    ///         l'incident courant == Σ recalculée par le modèle ; Sp expiré sans effet.
    function invariant_f_watcherBounds() public view {
        assertFalse(handler.ghost_watcherViolation(), handler.ghost_firstFailure());
        uint256 open = ghost.openIncidentId();
        (,,, uint256 ext) = ghost.incidents(open);
        if (open != 0) assertEq(ext, handler.ghost_taggedSum(open), "extendedBalance");
        address[] memory a = _actors();
        for (uint256 i = 0; i < a.length; i++) {
            uint64 last = handler.ghost_lastEnd(a[i]);
            assertEq(ghost.extendedUntil(a[i]), last > block.timestamp ? last : 0, "extendedUntil");
            assertEq(ghost.extensionTag(a[i]), handler.ghost_tag(a[i]), "extensionTag");
            (, uint256 pValid,) = ghost.suspectComponentsOf(a[i]);
            uint256 tag = ghost.pendingTag(a[i]);
            (, uint64 exp, bool conf,) = ghost.incidents(tag);
            if (!conf && block.timestamp >= exp) assertEq(pValid, 0, "expired pending still counts");
        }
    }

    /// @notice Vivacité : aucune action « doit réussir » n'a revert, aucune action « doit
    ///         échouer » (dont les actions interdites au surveillant) n'a réussi.
    function invariant_liveness() public view {
        assertFalse(handler.ghost_unexpectedRevert(), handler.ghost_firstFailure());
        assertFalse(handler.ghost_unexpectedSuccess(), handler.ghost_firstFailure());
    }

    /// @notice Test de fumée déterministe du handler : chaque chemin utile réussit au moins une
    ///         fois avec des graines fixées (le résumé d'une campagne aléatoire ne le garantit pas).
    function test_handlerExercisesEveryPath() public {
        handler.mint(0, 500e6);
        handler.mint(1, 500e6);
        handler.mint(2, 500e6);
        handler.transferGhost(0, 1, 100e18);
        handler.warp(2 * W);
        handler.convert(0, 50e18);
        handler.transferM(0, 2, 10e18);
        handler.watcherDelay(0, 7, W);
        handler.watcherChainIncident(); // incident 1 expire : son Sp tombe, incident 2 re-marque
        handler.watcherDelay(0, 9, W); // rejoint l'incident 2 et sème
        handler.convertSuspectPart(0);
        handler.guardianDestroy(2, 1, 0);
        handler.guardianRestitute(3, 1, 0);
        handler.sweep(0);
        handler.guardianExtend(1, 3, W, 1);
        handler.guardianClear(0, 2);
        for (uint256 i = 0; i < 10; i++) {
            handler.watcherForbidden(i);
        }
        for (uint256 i = 0; i < 3; i++) {
            handler.guardianPause(i);
        }
        assertTrue(ghost.paused());
        handler.transferGhost(1, 2, 1e18); // doit échouer (pause) : classé, pas de drapeau
        for (uint256 i = 0; i < 3; i++) {
            handler.guardianPause(i);
        }
        assertFalse(ghost.paused());

        assertFalse(handler.ghost_unexpectedRevert(), handler.ghost_firstFailure());
        assertFalse(handler.ghost_unexpectedSuccess(), handler.ghost_firstFailure());
        string[12] memory k = [
            "mint_ok",
            "transferGhost_ok",
            "transferM_ok",
            "convert_ok",
            "watcherDelay_ok",
            "watcherChain",
            "guardianDestroy_ok",
            "guardianRestitute_ok",
            "sweep_ok",
            "guardianExtend_ok",
            "guardianClear_ok",
            "guardianPause_ok"
        ];
        for (uint256 i = 0; i < k.length; i++) {
            assertGt(handler.calls(bytes32(bytes(k[i]))), 0, k[i]);
        }
        invariant_a_nothingOutBeforeW();
        invariant_b_bucketsMatchShadow();
        invariant_c_suspicionConserved();
        invariant_e_solvency();
        invariant_f_watcherBounds();
    }

    /// @notice Résumé des appels (affichage seulement, `-vv`) : prouve que les chemins utiles
    ///         sont réellement explorés.
    function invariant_callSummary() public view {
        string[16] memory k = [
            "mint_ok",
            "transferGhost_ok",
            "transferM_ok",
            "convert_ok",
            "convertSuspectPart",
            "watcherDelay_ok",
            "watcherDelay_refused",
            "watcherChain",
            "watcherForbidden",
            "guardianDestroy_ok",
            "guardianExtend_ok",
            "guardianClear_ok",
            "guardianRestitute_ok",
            "sweep_ok",
            "guardianPause_ok",
            "guardianPause_ko"
        ];
        for (uint256 i = 0; i < k.length; i++) {
            console.log(k[i], handler.calls(bytes32(bytes(k[i]))));
        }
    }
}

/// forge-config: default.invariant.runs = 48
/// forge-config: default.invariant.depth = 128
contract GhostInvariantTest is GhostInvariantBase {
    function _cfg() internal pure override returns (GhostConfig memory) {
        return _ghostConfig();
    }
}

/// forge-config: default.invariant.runs = 48
/// forge-config: default.invariant.depth = 128
contract GhostThresholdsInvariantTest is GhostInvariantBase {
    function _cfg() internal pure override returns (GhostConfig memory) {
        return _ghostConfigThresholds();
    }
}
