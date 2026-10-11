// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {BaseTest} from "./utils/BaseTest.sol";
import {ProtectedMinter} from "../src/ProtectedMinter.sol";
import {GhostedStable} from "../src/GhostedStable.sol";
import {GhostToken} from "../src/GhostToken.sol";
import {GuardianPausable} from "../src/GuardianPausable.sol";

/// @notice Garde-fou du taux (#131) : une clé `RATE_ADMIN_ROLE` volée ne peut plus mint sans
///         limite. `proposeRate` est borné à `MAX_RATE_STEP_BPS` de variation et temporisé par
///         `RATE_DELAY` (fenêtre de réaction), un guardian peut annuler. Données FICTIVES.
contract RateGuardTest is BaseTest {
    ProtectedMinter internal minter;
    GhostToken internal ghost;

    event RateProposed(uint256 currentRate, uint256 newRate, uint64 effectiveAt, address indexed proposer);
    event RateChanged(uint256 oldRate, uint256 newRate, address indexed changedBy);
    event RateCancelled(uint256 cancelledRate, address indexed guardian);

    function setUp() public {
        _deployUsdc();
        (minter,, ghost) = _deployProtected();
    }

    function _maxStep() internal view returns (uint256) {
        return minter.rate() * minter.MAX_RATE_STEP_BPS() / 10_000;
    }

    // ---------------------------------------------------------------- droits

    function test_proposeRate_onlyRateAdmin() public {
        bytes32 role = minter.RATE_ADMIN_ROLE();
        vm.prank(service);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, service, role)
        );
        minter.proposeRate(1.01e18);
    }

    // ---------------------------------------------------------------- borne de variation

    function test_proposeRate_stepBoundEnforced() public {
        uint256 maxStep = _maxStep(); // 5 % de 1e18 = 0.05e18
        // Juste au-dessus de la borne : refusé.
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(ProtectedMinter.RateStepTooLarge.selector, 1e18 + maxStep + 1, maxStep));
        minter.proposeRate(1e18 + maxStep + 1);
        // L'attaque de #131 (taux × 1e18) est refusée d'emblée.
        vm.prank(admin);
        vm.expectRevert();
        minter.proposeRate(1e36);
        // Exactement la borne (hausse ET baisse) : accepté.
        vm.prank(admin);
        minter.proposeRate(1e18 + maxStep);
        assertEq(minter.pendingRate(), 1.05e18);
    }

    function test_proposeRate_zeroRejected() public {
        vm.prank(admin);
        vm.expectRevert(ProtectedMinter.InvalidRate.selector);
        minter.proposeRate(0);
    }

    // ---------------------------------------------------------------- timelock

    function test_executeRate_respectsDelay() public {
        vm.expectRevert(ProtectedMinter.NoPendingRate.selector);
        minter.executeRate();

        vm.prank(admin);
        minter.proposeRate(1.05e18);
        uint64 eff = minter.pendingRateEffectiveAt();
        assertEq(minter.rate(), 1e18, "le taux a change avant l'echeance");

        vm.warp(eff - 1);
        vm.expectRevert(abi.encodeWithSelector(ProtectedMinter.RateDelayNotElapsed.selector, eff));
        minter.executeRate();

        vm.warp(eff);
        vm.expectEmit(true, false, false, true, address(minter));
        emit RateChanged(1e18, 1.05e18, address(this));
        minter.executeRate();
        assertEq(minter.rate(), 1.05e18);
        assertEq(minter.pendingRateEffectiveAt(), 0);
    }

    /// @notice Une proposition en attente ne change pas le taux appliqué aux demandes.
    function test_pendingRate_doesNotApplyUntilExecuted() public {
        vm.prank(admin);
        minter.proposeRate(1.05e18);
        uint256 id = _requestProtected(minter, alice, 1_000e6);
        assertEq(minter.getRequest(id).rate, 1e18, "la demande a pris le taux en attente");
    }

    // ---------------------------------------------------------------- annulation par guardian

    function test_cancelRate_byGuardian() public {
        vm.prank(admin);
        minter.proposeRate(1.05e18);
        // Non-guardian refusé.
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.NotGuardian.selector, alice));
        minter.cancelRate();
        // Un guardian suffit.
        vm.prank(guardian1);
        vm.expectEmit(true, false, false, true, address(minter));
        emit RateCancelled(1.05e18, guardian1);
        minter.cancelRate();
        assertEq(minter.pendingRateEffectiveAt(), 0);
        assertEq(minter.pendingRate(), 0);
        // Plus rien à exécuter.
        vm.warp(block.timestamp + minter.RATE_DELAY() + 1);
        vm.expectRevert(ProtectedMinter.NoPendingRate.selector);
        minter.executeRate();
        assertEq(minter.rate(), 1e18);
    }

    // ---------------------------------------------------------------- clé de taux volée bornée

    /// @notice Scénario exact de #131 : avant, `setRate(1e36)` puis `requestSwap(1)` donnait 1e24
    ///         stables. Désormais le taux ne peut bouger que de 5 % par période `RATE_DELAY`, donc
    ///         un dépôt de 1 wei mint au plus `quoteMint(1, rate × 1.05)` — borné, pas 1e24.
    function test_stolenRateKey_cannotMintUnbounded() public {
        // La « clé volée » EST l'admin ici (pire cas : le rôle taux est compromis).
        vm.prank(admin);
        vm.expectRevert(); // 1e36 refusé par la borne
        minter.proposeRate(1e36);

        // Au mieux l'attaquant pousse +5 % puis exécute après le délai.
        _proposeExecuteRate(minter, 1.05e18);
        uint256 id = _requestProtected(minter, attacker, 1); // 1 wei de collatéral
        vm.prank(service);
        minter.completeSwap(id);
        uint256 minted = ghost.balanceOf(attacker);
        assertEq(minted, minter.quoteMint(1, 1.05e18));
        assertLe(minted, 1.05e12, "mint pour 1 wei non borne"); // vs 1e24 avant #131
    }

    /// @notice Toute proposition acceptée laisse le taux à au plus +5 % du courant : borne par pas.
    function testFuzz_proposeRate_withinStepOrReverts(uint256 newRate) public {
        newRate = bound(newRate, 1, 1e30);
        uint256 cur = minter.rate();
        uint256 maxStep = _maxStep();
        vm.prank(admin);
        try minter.proposeRate(newRate) {
            uint256 diff = newRate > cur ? newRate - cur : cur - newRate;
            assertLe(diff, maxStep, "pas accepte au-dela de la borne");
            assertEq(minter.pendingRate(), newRate);
        } catch {
            uint256 diff = newRate > cur ? newRate - cur : cur - newRate;
            assertTrue(diff > maxStep || newRate == 0, "revert hors borne attendu");
        }
    }
}
