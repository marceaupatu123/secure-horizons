// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {RiskBeacon} from "../src/RiskBeacon.sol";
import {MockLendingMarket} from "../src/MockLendingMarket.sol";
import {IGhostRisk} from "../src/interfaces/IGhostRisk.sol";
import {MockGhostRisk} from "./utils/MockGhostRisk.sol";

/// @notice Balise de risque + faux marché de prêt (#7). Données FICTIVES, seuils = paramètres.
contract RiskBeaconTest is Test {
    uint256 internal constant SCALE = 1e12; // M 18 déc. / mUSDC 6 déc.
    uint256 internal constant LIQUIDITY = 10_000_000e6;

    MockGhostRisk internal ghost;
    RiskBeacon internal beacon;
    MockUSDC internal usdc;

    address internal alice = makeAddr("alice");
    address internal attacker = makeAddr("attacker");

    function setUp() public {
        vm.warp(1_000_000);
        ghost = new MockGhostRisk();
        beacon = new RiskBeacon(IGhostRisk(address(ghost)));
        usdc = new MockUSDC();
    }

    function _cfg(bool useBeacon) internal pure returns (MockLendingMarket.MarketConfig memory) {
        return MockLendingMarket.MarketConfig({
            useBeacon: useBeacon,
            ltvBps: 8_000,
            baseHaircutBps: 500,
            slopeHaircutBps: 9_500,
            maxBorrowRatio: 0.1e18,
            maxBorrowSuspect: 1_000e18
        });
    }

    function _market(bool useBeacon) internal returns (MockLendingMarket m) {
        m = new MockLendingMarket(
            IERC20(address(ghost)), IERC20(address(usdc)), IGhostRisk(address(ghost)), beacon, SCALE, _cfg(useBeacon)
        );
        usdc.mint(address(m), LIQUIDITY);
    }

    function _deposit(MockLendingMarket m, address who, uint256 amount) internal {
        vm.startPrank(who);
        ghost.approve(address(m), amount);
        m.deposit(amount);
        vm.stopPrank();
    }

    // ------------------------------------------------------------ RiskBeacon

    function test_beacon_rejectsZeroGhost() public {
        vm.expectRevert(RiskBeacon.ZeroAddress.selector);
        new RiskBeacon(IGhostRisk(address(0)));
    }

    function test_state_normal() public {
        ghost.mint(alice, 100e18, 0);
        ghost.setPendingTag(alice, 0);
        RiskBeacon.Risk memory r = beacon.riskOf(alice);
        assertEq(uint256(r.state), uint256(RiskBeacon.State.NORMAL));
        assertEq(r.ratio, 0);
    }

    function test_state_priority_pause_over_destroyed_over_delayed() public {
        ghost.mint(alice, 100e18, 50e18);
        ghost.setExtended(alice, uint64(block.timestamp + 600), 7);
        RiskBeacon.Risk memory r = beacon.riskOf(alice);
        assertEq(uint256(r.state), uint256(RiskBeacon.State.RETARDE));
        assertEq(r.incidentId, 7);
        assertEq(r.ratio, 0.5e18);
        assertEq(r.suspectAmount, 50e18);

        ghost.destroy(alice, 9);
        r = beacon.riskOf(alice);
        assertEq(uint256(r.state), uint256(RiskBeacon.State.DETRUIT));
        assertEq(r.incidentId, 9);

        ghost.setPaused(true);
        assertEq(uint256(beacon.riskOf(alice).state), uint256(RiskBeacon.State.PAUSE_GLOBALE));
    }

    function test_clearing_after_destruction_returns_to_normal() public {
        ghost.mint(alice, 100e18, 10e18);
        ghost.destroy(alice, 3);
        vm.warp(block.timestamp + 1);
        ghost.setCleared(alice, uint64(block.timestamp));
        assertEq(uint256(beacon.riskOf(alice).state), uint256(RiskBeacon.State.NORMAL));
    }

    function test_publish_emits_and_is_bounded() public {
        ghost.mint(alice, 100e18, 25e18);
        address[] memory one = new address[](1);
        one[0] = alice;
        vm.expectEmit(true, false, false, true, address(beacon));
        emit RiskBeacon.RiskPublished(alice, 0.25e18, 25e18, 0, RiskBeacon.State.NORMAL, 0);
        beacon.publish(one);

        address[] memory many = new address[](beacon.MAX_PUBLISH() + 1);
        vm.expectRevert(abi.encodeWithSelector(RiskBeacon.TooManyAccounts.selector, many.length, beacon.MAX_PUBLISH()));
        beacon.publish(many);
    }

    // ------------------------------------------------------------ MockLendingMarket

    function test_market_constructor_checks() public {
        vm.expectRevert(MockLendingMarket.ZeroAddress.selector);
        new MockLendingMarket(
            IERC20(address(ghost)), IERC20(address(usdc)), IGhostRisk(address(ghost)), RiskBeacon(address(0)), SCALE, _cfg(true)
        );
        RiskBeacon other = new RiskBeacon(IGhostRisk(address(new MockGhostRisk())));
        vm.expectRevert(MockLendingMarket.InvalidConfig.selector);
        new MockLendingMarket(
            IERC20(address(ghost)), IERC20(address(usdc)), IGhostRisk(address(ghost)), other, SCALE, _cfg(true)
        );
    }

    function test_clean_borrow_with_beacon() public {
        MockLendingMarket m = _market(true);
        ghost.mint(alice, 1_000e18, 0);
        _deposit(m, alice, 1_000e18);
        // capacité = 1000 × (1 − 5 %) × 80 % = 760 mUSDC
        assertEq(m.capacityOf(alice), 760e6);
        vm.prank(alice);
        m.borrow(760e6);
        assertEq(usdc.balanceOf(alice), 760e6);
        vm.prank(alice);
        vm.expectRevert();
        m.borrow(1);
    }

    function test_haircut_grows_with_imported_ratio() public {
        MockLendingMarket m = _market(true);
        ghost.mint(alice, 1_000e18, 50e18); // ratio 5 %
        _deposit(m, alice, 1_000e18);
        (, uint256 imported,,) = m.positions(alice);
        assertEq(imported, 50e18);
        // 500 + 9500 × 5 % = 975 bps
        assertEq(m.haircutBps(alice), 975);
    }

    function test_borrow_refused_when_not_normal() public {
        MockLendingMarket m = _market(true);
        ghost.mint(alice, 1_000e18, 0);
        _deposit(m, alice, 1_000e18);
        ghost.setExtended(alice, uint64(block.timestamp + 600), 1);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(MockLendingMarket.BorrowRefused.selector, RiskBeacon.State.RETARDE, 0, 0));
        m.borrow(1e6);
    }

    function test_withdraw_locked_for_window_plus_slot() public {
        MockLendingMarket m = _market(false);
        ghost.mint(alice, 100e18, 0);
        _deposit(m, alice, 100e18);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(MockLendingMarket.Locked.selector, uint64(block.timestamp + 660)));
        m.withdraw(100e18);
        vm.warp(block.timestamp + 660);
        vm.prank(alice);
        m.withdraw(100e18);
        assertEq(ghost.balanceOf(alice), 100e18);
    }

    function test_withdraw_cannot_leave_debt_uncovered() public {
        MockLendingMarket m = _market(false);
        ghost.mint(alice, 100e18, 0);
        _deposit(m, alice, 100e18);
        vm.prank(alice);
        m.borrow(50e6);
        vm.warp(block.timestamp + 660);
        vm.prank(alice);
        vm.expectRevert();
        m.withdraw(90e18);
    }

    function test_no_bank_run_after_destruction() public {
        MockLendingMarket m = _market(false);
        ghost.mint(alice, 100e18, 0);
        ghost.mint(attacker, 100e18, 100e18);
        _deposit(m, alice, 100e18);
        _deposit(m, attacker, 100e18);
        ghost.destroy(address(m), 1); // brûle 100 (le soupçon importé)
        vm.warp(block.timestamp + 660);
        vm.prank(attacker);
        m.withdraw(100e18);
        // L'attaquant ne peut pas vider la part d'alice : chacun touche 50 %.
        assertEq(ghost.balanceOf(attacker), 50e18);
        vm.prank(alice);
        m.withdraw(100e18);
        assertEq(ghost.balanceOf(alice), 50e18);
        assertEq(ghost.balanceOf(address(m)), 0);
    }

    function test_repay_more_than_debt_reverts() public {
        MockLendingMarket m = _market(false);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(MockLendingMarket.RepayTooMuch.selector, 1, 0));
        m.repay(1);
    }

    function testFuzz_borrow_never_exceeds_capacity(uint96 collateral, uint96 ask) public {
        MockLendingMarket m = _market(true);
        uint256 c = bound(uint256(collateral), 1, 1_000_000e18);
        ghost.mint(alice, c, 0);
        _deposit(m, alice, c);
        uint256 cap = m.capacityOf(alice);
        uint256 a = bound(uint256(ask), 1, cap + 1e6);
        vm.prank(alice);
        if (a > cap) {
            vm.expectRevert();
            m.borrow(a);
        } else {
            m.borrow(a);
            (,, uint256 debt,) = m.positions(alice);
            assertLe(debt, cap);
        }
    }

    // ------------------------------------------------------------ Scénario C (mesuré, pas inventé)

    /// @dev Attaquant avec du Ghost entièrement suspect (alerte posée, ratio 100 %, pas encore
    ///      retardé), dépose en garantie, emprunte, puis destruction 2/3 de la garantie.
    ///      Mauvaise créance mesurée sur le SOLDE RÉEL du marché (point bloquant de la relecture
    ///      de #8) : dette non remboursée vs valeur de garantie restante.
    function _scenarioC(bool useBeacon) internal returns (uint256 badDebt, uint256 imported) {
        MockLendingMarket m = _market(useBeacon);
        uint256 amount = 100_000e18;
        ghost.mint(attacker, amount, amount);
        uint256 before = ghost.effectiveSuspectOf(address(m));
        _deposit(m, attacker, amount);
        imported = ghost.effectiveSuspectOf(address(m)) - before;

        uint256 cap = m.capacityOf(attacker);
        vm.prank(attacker);
        try m.borrow(cap) {} catch {}

        ghost.destroy(address(m), 1);
        (, , uint256 debt,) = m.positions(attacker);
        uint256 collateralValue = ghost.balanceOf(address(m)) / SCALE; // 1:1 PROVISOIRE
        badDebt = debt > collateralValue ? debt - collateralValue : 0;
    }

    function test_scenarioC_bad_debt_with_vs_without_beacon() public {
        (uint256 withoutBeacon, uint256 importedA) = _scenarioC(false);
        (uint256 withBeacon, uint256 importedB) = _scenarioC(true);
        assertEq(importedA, 100_000e18);
        assertEq(importedB, 100_000e18);
        // Sans balise : prêt accordé (95 % × 80 % de 100 000), garantie détruite → créance perdue.
        assertEq(withoutBeacon, 76_000e6);
        // Avec balise : emprunt refusé (ratio 100 % > seuil) → aucune créance.
        assertEq(withBeacon, 0);
        emit log_named_uint("scenario C - mauvaise creance sans balise (mUSDC base units)", withoutBeacon);
        emit log_named_uint("scenario C - mauvaise creance avec balise (mUSDC base units)", withBeacon);
    }
}
