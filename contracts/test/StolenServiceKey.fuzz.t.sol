// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {BaseTest} from "./utils/BaseTest.sol";
import {GuardianPausable} from "../src/GuardianPausable.sol";
import {ProtectedMinter} from "../src/ProtectedMinter.sol";
import {GhostedStable} from "../src/GhostedStable.sol";
import {GhostToken} from "../src/GhostToken.sol";

/// @notice Fuzz : un attaquant détenant la clé `SERVICE_ROLE` volée contre le ProtectedMinter.
///         Hypothèses : clés admin/taux et guardians NON compromises (H1, H2 du README).
contract StolenServiceKeyFuzzTest is BaseTest {
    ProtectedMinter internal minter;
    GhostedStable internal stable;
    GhostToken internal ghost;

    function setUp() public {
        _deployUsdc();
        (minter, stable, ghost) = _deployProtected();
    }

    /// @notice Quels que soient le montant et le destinataire voulus, la clé volée obtient
    ///         exactement dépôt × taux, versé au déposant.
    function testFuzz_stolenKey_cannotInflate(uint256 deposit, uint256 rate_, uint256 fakeAmount, address fakeRecipient)
        public
    {
        deposit = bound(deposit, 1, 1e18);
        rate_ = bound(rate_, 1e6, 1e24);
        uint256 expected = deposit * SCALE * rate_ / 1e18; // recalculé par le test
        vm.assume(expected > 0);
        vm.prank(admin);
        minter.setRate(rate_);

        uint256 id = _requestProtected(minter, attacker, deposit);
        vm.prank(attacker);
        (bool ok,) = address(minter)
            .call(abi.encodeWithSignature("completeSwap(uint256,address,uint256)", id, fakeRecipient, fakeAmount));
        assertFalse(ok);

        vm.prank(attacker);
        minter.completeSwap(id);
        assertEq(ghost.supplyValue(), expected);
        assertEq(ghost.balanceOf(attacker), expected);
    }

    /// @notice La demande d'une victime traitée par la clé volée va à la victime.
    function testFuzz_stolenKey_cannotRedirect(uint256 victimSeed, uint256 deposit) public {
        address victim = address(uint160(bound(victimSeed, 1, type(uint160).max)));
        vm.assume(victim != attacker && victim != address(minter) && victim != address(usdc));
        vm.assume(victim.code.length == 0);
        deposit = bound(deposit, 1, 1e18);

        uint256 id = _requestProtected(minter, victim, deposit);
        vm.prank(attacker);
        minter.completeSwap(id);
        assertEq(ghost.balanceOf(victim), deposit * SCALE);
        assertEq(ghost.balanceOf(attacker), 0);
    }

    /// @notice Rejouer une demande déjà traitée échoue à chaque tentative.
    function testFuzz_stolenKey_cannotReplay(uint256 deposit, uint8 tries) public {
        deposit = bound(deposit, 1, 1e18);
        uint256 n = bound(tries, 1, 20);
        uint256 id = _requestProtected(minter, attacker, deposit);
        vm.prank(attacker);
        minter.completeSwap(id);
        for (uint256 i = 0; i < n; i++) {
            vm.prank(attacker);
            vm.expectRevert(abi.encodeWithSelector(ProtectedMinter.RequestNotPending.selector, id));
            minter.completeSwap(id);
        }
        assertEq(ghost.supplyValue(), deposit * SCALE);
    }

    function testFuzz_stolenKey_cannotMintDirectly(uint256 amount) public {
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(GhostedStable.NotMinter.selector, attacker));
        stable.mint(attacker, amount);
    }

    /// @notice I4 révisé (#8) : la clé volée ne peut pas non plus émettre de Ghost directement.
    function testFuzz_stolenKey_cannotIssueGhost(uint256 amount, uint256 requestId) public {
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.NotMinter.selector, attacker));
        ghost.issueFromMinter(attacker, amount, requestId);
        assertEq(ghost.supplyValue(), 0);
    }

    function testFuzz_stolenKey_cannotChangeRate(uint256 newRate) public {
        bytes32 role = minter.RATE_ADMIN_ROLE();
        vm.prank(attacker);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, attacker, role)
        );
        minter.setRate(newRate);
        assertEq(minter.rate(), INITIAL_RATE);
    }

    /// @notice La clé volée n'est pas guardian : elle ne peut ni pauser ni dépauser.
    function testFuzz_stolenKey_cannotPause(bool tryUnpause) public {
        if (tryUnpause) _pauseAll(minter);
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.NotGuardian.selector, attacker));
        if (tryUnpause) minter.approveUnpause();
        else minter.approvePause();
        assertEq(minter.paused(), tryUnpause);
    }
}
