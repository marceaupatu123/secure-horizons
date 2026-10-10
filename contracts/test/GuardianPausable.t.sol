// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {BaseTest} from "./utils/BaseTest.sol";
import {GuardianPausable} from "../src/GuardianPausable.sol";
import {ProtectedMinter} from "../src/ProtectedMinter.sol";
import {StableToken} from "../src/StableToken.sol";

/// @notice Pause globale gardée par un multisig simulé 3/3 (docs/OPEN_ANSWERS.md §3).
contract GuardianPausableTest is BaseTest {
    ProtectedMinter internal minter;
    StableToken internal stable;

    event Paused(address account);
    event Unpaused(address account);

    function setUp() public {
        _deployUsdc();
        (minter, stable) = _deployProtected();
    }

    function test_pause_requiresThreeOfThree() public {
        vm.prank(guardian1);
        minter.approvePause();
        assertFalse(minter.paused());
        assertEq(minter.approvals(), 1);

        vm.prank(guardian2);
        minter.approvePause();
        assertFalse(minter.paused());
        assertEq(minter.approvals(), 2);

        vm.expectEmit(false, false, false, true, address(minter));
        emit Paused(guardian3);
        vm.prank(guardian3);
        minter.approvePause();
        assertTrue(minter.paused());
    }

    function test_unpause_requiresThreeOfThree() public {
        _pauseAll(minter);

        vm.prank(guardian1);
        minter.approveUnpause();
        vm.prank(guardian2);
        minter.approveUnpause();
        assertTrue(minter.paused());

        vm.expectEmit(false, false, false, true, address(minter));
        emit Unpaused(guardian3);
        vm.prank(guardian3);
        minter.approveUnpause();
        assertFalse(minter.paused());
    }

    function test_singleGuardianCannotPause() public {
        vm.prank(guardian1);
        minter.approvePause();
        assertFalse(minter.paused());
        vm.prank(guardian1);
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.AlreadyApproved.selector, guardian1, 0));
        minter.approvePause();
        assertFalse(minter.paused());
    }

    function test_nonGuardianCannotApprove() public {
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.NotGuardian.selector, admin));
        minter.approvePause();

        vm.prank(service);
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.NotGuardian.selector, service));
        minter.approvePause();

        _pauseAll(minter);
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.NotGuardian.selector, admin));
        minter.approveUnpause();
    }

    function test_guardianCannotApproveTwice() public {
        vm.prank(guardian2);
        minter.approvePause();
        vm.prank(guardian2);
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.AlreadyApproved.selector, guardian2, 0));
        minter.approvePause();
    }

    function test_approvalsResetAfterExecution() public {
        assertEq(minter.pauseRound(), 0);
        _pauseAll(minter);
        assertEq(minter.pauseRound(), 1);
        assertEq(minter.approvals(), 0);

        // Les approbations de pause (round 0) ne comptent pas pour la dépause (round 1).
        vm.prank(guardian1);
        minter.approveUnpause();
        assertEq(minter.approvals(), 1);
        assertTrue(minter.paused());
        assertTrue(minter.hasApproved(0, guardian1));
        assertTrue(minter.hasApproved(1, guardian1));
        assertFalse(minter.hasApproved(1, guardian2));
    }

    function test_approvePause_revertsWhenPaused() public {
        _pauseAll(minter);
        vm.prank(guardian1);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        minter.approvePause();
    }

    function test_approveUnpause_revertsWhenNotPaused() public {
        vm.prank(guardian1);
        vm.expectRevert(Pausable.ExpectedPause.selector);
        minter.approveUnpause();
    }

    function test_constructor_rejectsDuplicateOrZeroGuardian() public {
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.InvalidGuardian.selector, guardian1));
        new ProtectedMinter(IERC20(address(usdc)), admin, service, INITIAL_RATE, [guardian1, guardian2, guardian1]);

        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.InvalidGuardian.selector, address(0)));
        new ProtectedMinter(IERC20(address(usdc)), admin, service, INITIAL_RATE, [guardian1, address(0), guardian3]);
    }

    function test_guardians_listed() public view {
        address[3] memory g = minter.guardians();
        assertEq(g[0], guardian1);
        assertEq(g[1], guardian2);
        assertEq(g[2], guardian3);
        assertTrue(minter.isGuardian(guardian2));
        assertFalse(minter.isGuardian(admin));
    }

    function test_pause_blocksRequestAndComplete() public {
        uint256 id = _requestProtected(minter, alice, 100e6);
        _pauseAll(minter);

        _fund(bob, 100e6);
        _approve(bob, address(minter));
        vm.prank(bob);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        minter.requestSwap(100e6);

        vm.prank(service);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        minter.completeSwap(id);
    }

    function test_setRate_allowedWhilePaused() public {
        _pauseAll(minter);
        vm.prank(admin);
        minter.setRate(2e18);
        assertEq(minter.rate(), 2e18);
    }
}
