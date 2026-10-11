// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {StdInvariant} from "forge-std/StdInvariant.sol";
import {console} from "forge-std/console.sol";
import {BaseTest} from "../utils/BaseTest.sol";
import {ProtectedMinter} from "../../src/ProtectedMinter.sol";
import {GhostedStable} from "../../src/GhostedStable.sol";
import {GhostToken} from "../../src/GhostToken.sol";
import {ProtectedMinterHandler} from "./ProtectedMinterHandler.sol";

/// @notice Volet 2 : perte maximale bornée de la clé de service volée, vérifiée par tests
///         d'invariants (pas prouvée). Hypothèses H1–H5 : voir contracts/README.md.
contract ProtectedMinterInvariantTest is StdInvariant, BaseTest {
    ProtectedMinter internal minter;
    GhostedStable internal stable;
    GhostToken internal ghost;
    ProtectedMinterHandler internal handler;

    function setUp() public {
        _deployUsdc();
        (minter, stable, ghost) = _deployProtected();
        handler = new ProtectedMinterHandler(minter, usdc, service, admin, _guardians());

        bytes4[] memory selectors = new bytes4[](8);
        selectors[0] = ProtectedMinterHandler.requestSwap.selector;
        selectors[1] = ProtectedMinterHandler.completeSwap.selector;
        selectors[2] = ProtectedMinterHandler.completeUnknown.selector;
        selectors[3] = ProtectedMinterHandler.stolenKeyMintDirect.selector;
        selectors[4] = ProtectedMinterHandler.stolenKeyInflatedCall.selector;
        selectors[5] = ProtectedMinterHandler.stolenKeySetRate.selector;
        selectors[6] = ProtectedMinterHandler.adminSetRate.selector;
        selectors[7] = ProtectedMinterHandler.guardianApprove.selector;
        targetSelector(FuzzSelector({addr: address(handler), selectors: selectors}));
        targetContract(address(handler));
    }

    /// @notice Solvabilité : totalSupply ≤ Σ (dépôt × taux) de toutes les demandes créées.
    function invariant_solvency() public view {
        assertLe(ghost.supplyValue(), handler.ghost_sumExpectedAll());
    }

    /// @notice totalSupply == Σ (dépôt × taux) des demandes complétées == totalMinted.
    function invariant_supplyEqualsCompletedQuotes() public view {
        assertEq(ghost.supplyValue(), handler.ghost_sumMintedCompleted());
        assertEq(ghost.supplyValue(), minter.totalMinted());
    }

    /// @notice Tout le collatéral déposé est détenu par le minter.
    function invariant_collateralBacking() public view {
        assertEq(usdc.balanceOf(address(minter)), handler.ghost_sumDeposits());
        assertEq(minter.totalDeposited(), handler.ghost_sumDeposits());
    }

    /// @notice Chaque demande est complétée au plus une fois, et le statut on-chain est cohérent.
    function invariant_eachRequestCompletedAtMostOnce() public view {
        uint256 n = handler.requestCount();
        for (uint256 i = 0; i < n; i++) {
            uint256 id = handler.requestIds(i);
            uint256 c = handler.completions(id);
            assertLe(c, 1);
            ProtectedMinter.RequestStatus s = minter.getRequest(id).status;
            if (c == 1) assertEq(uint8(s), uint8(ProtectedMinter.RequestStatus.Completed));
            else assertEq(uint8(s), uint8(ProtectedMinter.RequestStatus.Pending));
        }
    }

    /// @notice Pour chaque demande complétée : minté == dépôt × taux (recalculé par le test).
    function invariant_mintedPerRequestEqualsQuote() public view {
        uint256 n = handler.requestCount();
        for (uint256 i = 0; i < n; i++) {
            uint256 id = handler.requestIds(i);
            ProtectedMinter.SwapRequest memory r = minter.getRequest(id);
            assertEq(r.depositor, handler.depositorOf(id));
            assertEq(r.depositAmount, handler.depositOf(id));
            assertEq(r.rate, handler.rateOf(id));
            if (handler.completions(id) == 1) {
                uint256 expected = handler.depositOf(id) * SCALE * handler.rateOf(id) / 1e18;
                assertEq(handler.expectedMint(id), expected);
                assertEq(handler.mintedObserved(id), expected);
                assertEq(handler.supplyDelta(id), expected);
            }
        }
    }

    /// @notice Destinataire == déposant : chaque acteur détient exactement ce que ses propres
    ///         demandes complétées lui doivent (aucun transfert entre acteurs dans le handler).
    function invariant_recipientIsDepositor() public view {
        uint256 n = handler.actorCount();
        for (uint256 i = 0; i < n; i++) {
            address a = handler.actors(i);
            assertEq(ghost.balanceOf(a), handler.ghost_expectedBalance(a));
        }
    }

    /// @notice Borne de la clé de service volée : son solde stable ≤ Σ (dépôt × taux) de SES
    ///         PROPRES dépôts, et aucune action interdite n'a jamais réussi.
    function invariant_stolenKeyBound() public view {
        assertLe(ghost.balanceOf(service), handler.ghost_expectedFromDepositsOf(service));
        assertFalse(handler.ghost_unexpectedSuccess());
    }

    /// @notice Vivacité : aucune action « doit réussir » n'a revert (le handler n'avale pas en
    ///         silence les reverts, `fail_on_revert = false`) et aucune action « doit échouer »
    ///         n'a réussi.
    function invariant_liveness() public view {
        assertFalse(handler.ghost_unexpectedRevert());
        assertFalse(handler.ghost_unexpectedSuccess());
    }

    /// @notice Résumé des appels (affichage seulement, `-vv`).
    function invariant_callSummary() public view {
        console.log("requestSwap", handler.calls("requestSwap"));
        console.log("requestSwap_ok", handler.calls("requestSwap_ok"));
        console.log("completeSwap", handler.calls("completeSwap"));
        console.log("completeSwap_ok", handler.calls("completeSwap_ok"));
        console.log("completeSwap_rejected", handler.calls("completeSwap_rejected"));
        console.log("completeUnknown", handler.calls("completeUnknown"));
        console.log("stolenKeyMintDirect", handler.calls("stolenKeyMintDirect"));
        console.log("stolenKeyInflatedCall", handler.calls("stolenKeyInflatedCall"));
        console.log("stolenKeySetRate", handler.calls("stolenKeySetRate"));
        console.log("adminSetRate", handler.calls("adminSetRate"));
        console.log("adminSetRate_ok", handler.calls("adminSetRate_ok"));
        console.log("guardianApprove", handler.calls("guardianApprove"));
        console.log("guardianApprove_ok", handler.calls("guardianApprove_ok"));
        console.log("guardianApprove_ko", handler.calls("guardianApprove_ko"));
        console.log("requests", handler.requestCount());
    }
}
