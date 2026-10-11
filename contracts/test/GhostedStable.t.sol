// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {GhostBase} from "./utils/GhostBase.sol";
import {GhostedStable} from "../src/GhostedStable.sol";
import {GhostConfig, GhostToken} from "../src/GhostToken.sol";

/// @notice Le vrai token M (`GhostedStable`) : minté uniquement par conversion depuis le Ghost,
///         et tout transfert de M redevient du Ghost frais chez le destinataire (OPEN_ANSWERS §0bis).
contract GhostedStableTest is GhostBase {
    event Transfer(address indexed from, address indexed to, uint256 value);

    function setUp() public {
        _setUpGhost();
    }

    /// @dev alice détient `usdcAmount × 1e12` M (Ghost échu puis converti, marges à 0).
    function _giveM(address who, uint256 usdcAmount) internal returns (uint256 amount) {
        amount = _mintMatured(who, usdcAmount);
        _convert(who, amount);
    }

    function test_wiring() public view {
        assertEq(m.ghost(), address(ghost));
        assertEq(m.minter(), address(ghost));
        assertEq(ghost.underlying(), address(m));
        assertEq(address(pm.stable()), address(m));
        assertEq(m.decimals(), 18);
    }

    function test_mint_onlyGhost() public {
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(GhostedStable.NotMinter.selector, attacker));
        m.mint(attacker, 1);
        vm.prank(address(pm));
        vm.expectRevert(abi.encodeWithSelector(GhostedStable.NotMinter.selector, address(pm)));
        m.mint(attacker, 1);
    }

    function test_hooks_onlyTheirCaller() public {
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.NotUnderlying.selector, attacker));
        ghost.onUnderlyingTransfer(alice, attacker, 1e18);
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.NotMinter.selector, attacker));
        ghost.issueFromMinter(attacker, 1e18, 0);
    }

    /// @notice Transfert de M : M brûlé chez l'expéditeur, Ghost FRAIS chez le destinataire, qui
    ///         ne reçoit jamais de M ; la valeur totale est conservée.
    function test_transferM_burnsAndIssuesFreshGhost() public {
        _giveM(alice, 100e6);
        vm.warp(block.timestamp + 7); // instant non aligné
        uint256 t = block.timestamp;

        vm.expectEmit(true, true, false, true, address(m));
        emit Transfer(alice, address(0), 40e18);
        vm.prank(alice);
        assertTrue(m.transfer(bob, 40e18));

        assertEq(m.balanceOf(alice), 60e18);
        assertEq(m.balanceOf(bob), 0, "recipient received real M");
        assertEq(m.totalSupply(), 60e18);
        assertEq(ghost.balanceOf(bob), 40e18);
        (uint64[] memory mats, uint256[] memory amts) = ghost.bucketsOf(bob);
        assertEq(mats.length, 1);
        assertEq(mats[0], _maturityAt(t));
        assertEq(amts[0], 40e18);
        assertEq(ghost.convertibleOf(bob), 0);
        assertEq(ghost.supplyValue(), ghost.totalIssued(), "value not conserved");
    }

    function test_transferFromM_consumesAllowance() public {
        _giveM(alice, 100e6);
        vm.prank(alice);
        m.approve(carol, 30e18);
        vm.prank(carol);
        assertTrue(m.transferFrom(alice, bob, 30e18));
        assertEq(m.allowance(alice, carol), 0);
        assertEq(m.balanceOf(alice), 70e18);
        assertEq(ghost.balanceOf(bob), 30e18);

        vm.prank(carol);
        vm.expectRevert(); // ERC20InsufficientAllowance
        m.transferFrom(alice, bob, 1);
    }

    /// @notice Comportement documenté : s'envoyer du M à soi-même le remet en quarantaine.
    function test_selfTransferM_requarantines() public {
        _giveM(alice, 100e6);
        vm.prank(alice);
        m.transfer(alice, 10e18);
        assertEq(m.balanceOf(alice), 90e18);
        assertEq(ghost.balanceOf(alice), 10e18);
        assertEq(ghost.convertibleOf(alice), 0);
    }

    function test_zeroTransferM_issuesNothing() public {
        _giveM(alice, 100e6);
        vm.prank(alice);
        m.transfer(bob, 0);
        assertEq(ghost.balanceOf(bob), 0);
        assertEq(m.balanceOf(alice), 100e18);
    }

    function test_transferM_revertsWhenGhostPaused() public {
        _giveM(alice, 100e6);
        _pauseGhost();
        vm.prank(alice);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        m.transfer(bob, 1e18);
    }

    /// @notice Marge d'entrée M -> Ghost : le destinataire reçoit `v − fee`, la marge part en
    ///         réserve de restitution (`reserve()` augmente exactement de la marge).
    function test_entryFee_goesToReserve() public {
        GhostConfig memory cfg = _ghostConfig();
        cfg.entryFeeBps = 100; // 1 %, fixture
        _setUpGhostWith(cfg);
        _giveM(alice, 100e6);
        assertEq(ghost.reserve(), 0);

        vm.prank(alice);
        m.transfer(bob, 100e18);
        assertEq(ghost.balanceOf(bob), 99e18);
        assertEq(ghost.totalFees(), 1e18);
        assertEq(ghost.reserve(), 1e18);
        assertEq(ghost.lastReserveInflowAt(), block.timestamp);
        assertEq(IERC20(address(m)).totalSupply(), 0);
    }
}
