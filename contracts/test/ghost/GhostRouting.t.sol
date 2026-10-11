// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {GhostBase} from "../utils/GhostBase.sol";
import {GhostToken} from "../../src/GhostToken.sol";
import {SettlementRouter} from "../../src/SettlementRouter.sol";
import {ISettlementTypes} from "../../src/interfaces/ISettlementTypes.sol";

/// @notice Routage du M' (OPEN_ANSWERS §10bis point 2, option b′, #145) : une fois `initRouting`
///         appelé, un M' NON ÉCHU ne bouge que si l'appelant du token est autorisé (routeur, marché
///         de prêt). Le contrôle porte sur l'APPELANT (le routeur livre au wallet de l'acheteur).
///         Données FICTIVES ; `market` et `dex` sont de simples adresses qui jouent l'appelant.
contract GhostRoutingTest is GhostBase {
    SettlementRouter internal router;

    address internal thief = makeAddr("thief");
    address internal buyer = makeAddr("buyer");
    address internal market = makeAddr("market"); // marché de prêt autorisé (#7)
    address internal dex = makeAddr("dex"); // DEX tiers, non autorisé

    function setUp() public {
        _setUpGhost();
        router = new SettlementRouter(address(ghost));
    }

    function _activate() internal {
        address[] memory movers = new address[](2);
        movers[0] = address(router);
        movers[1] = market;
        vm.prank(admin);
        ghost.initRouting(movers);
    }

    function _fundAsset(address who, uint256 amount) internal {
        usdc.mint(who, amount);
        vm.prank(who);
        usdc.approve(address(router), amount);
    }

    // ---------------------------------------------------------------- avant activation

    function test_beforeInit_directTransferStillFree() public {
        uint256 amt = _mintGhost(alice, 100e6);
        _transferGhost(alice, bob, amt);
        assertEq(ghost.balanceOf(bob), amt);
        assertFalse(ghost.routingActive());
    }

    // ---------------------------------------------------------------- refus hors routeur

    function test_afterInit_directTransferOfFreshMprime_reverts() public {
        _activate();
        uint256 amt = _mintGhost(thief, 100e6);
        uint64 mat = ghost.nextOutgoingMaturity(thief, amt);
        assertGt(mat, block.timestamp);
        vm.prank(thief);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.UnroutedTransfer.selector, thief, mat));
        ghost.transfer(bob, amt);
    }

    /// @dev Le cas du voleur qui encaisse via un DEX : la paire tire le M' par `transferFrom`.
    function test_afterInit_thirdPartySpender_reverts() public {
        _activate();
        uint256 amt = _mintGhost(thief, 100e6);
        vm.prank(thief);
        ghost.approve(dex, amt);
        uint64 mat = ghost.nextOutgoingMaturity(thief, amt);
        vm.prank(dex);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.UnroutedTransfer.selector, dex, mat));
        ghost.transferFrom(thief, dex, amt);
        assertEq(ghost.balanceOf(thief), amt, "le M' n'a pas bouge");
    }

    function test_afterInit_maturedMprimeMovesFreely() public {
        _activate();
        uint256 amt = _mintMatured(alice, 100e6);
        assertEq(ghost.nextOutgoingMaturity(alice, amt), 0);
        _transferGhost(alice, bob, amt);
        assertEq(ghost.balanceOf(bob), amt);
    }

    // ---------------------------------------------------------------- appelants autorisés

    function test_afterInit_routerSalesStillWork() public {
        _activate();
        uint256 amt = _mintGhost(thief, 100e6);
        vm.prank(thief);
        ghost.approve(address(router), amt);
        _fundAsset(buyer, 60e6);

        // Achat protégé : le routeur livre le M' au wallet de l'acheteur.
        vm.prank(buyer);
        router.buyWithAsset(thief, 60e18, address(usdc), 60e6);
        assertEq(ghost.balanceOf(buyer), 60e18);
        assertEq(usdc.balanceOf(router.vaultOf(address(usdc))), 60e6, "paiement bloque au coffre");

        // Don / revente pure sans paiement on-chain : passe aussi par le routeur.
        vm.prank(buyer);
        router.sellPure(thief, 40e18, address(0), 0);
        assertEq(ghost.balanceOf(buyer), 100e18);
        assertEq(ghost.balanceOf(thief), 0);
        assertEq(
            uint8(router.statusOf(buyer, uint64(T0 + W))), uint8(ISettlementTypes.TrancheStatus.PUR)
        );
    }

    function test_afterInit_allowedMarketPullsAndReturnsCollateral() public {
        _activate();
        uint256 amt = _mintGhost(alice, 100e6);
        vm.prank(alice);
        ghost.approve(market, amt);
        vm.prank(market);
        ghost.transferFrom(alice, market, amt); // dépôt de garantie
        assertEq(ghost.balanceOf(market), amt);
        vm.prank(market);
        ghost.transfer(alice, amt); // retrait
        assertEq(ghost.balanceOf(alice), amt);
    }

    // ---------------------------------------------------------------- gouvernance de la liste

    function test_initRouting_onlyAdmin_onlyOnce() public {
        address[] memory movers = new address[](1);
        movers[0] = address(router);
        vm.prank(alice);
        vm.expectRevert();
        ghost.initRouting(movers);

        vm.prank(admin);
        ghost.initRouting(movers);
        assertTrue(ghost.routingActive());
        assertTrue(ghost.isAllowedMover(address(router)));

        vm.prank(admin);
        vm.expectRevert(GhostToken.RoutingAlreadyActive.selector);
        ghost.initRouting(movers);
    }

    function test_initRouting_rejectsZeroAddressAndEmptyList() public {
        address[] memory empty = new address[](0);
        vm.prank(admin);
        vm.expectRevert();
        ghost.initRouting(empty);

        address[] memory zero = new address[](1);
        vm.prank(admin);
        vm.expectRevert(GhostToken.ZeroAddress.selector);
        ghost.initRouting(zero);
        assertFalse(ghost.routingActive());
    }

    function test_proposeAllowedMover_beforeInit_reverts() public {
        vm.prank(guardian1);
        vm.expectRevert(GhostToken.RoutingNotActive.selector);
        ghost.proposeAllowedMover(dex, true);
    }

    /// @dev Une seule clé (admin ou guardian) ne suffit jamais à autoriser un DEX.
    function test_addingMover_needs2of3() public {
        _activate();
        vm.prank(alice);
        vm.expectRevert();
        ghost.proposeAllowedMover(dex, true);

        vm.prank(guardian1);
        uint256 pid = ghost.proposeAllowedMover(dex, true);
        assertFalse(ghost.isAllowedMover(dex), "1 signature ne suffit pas");

        vm.prank(guardian2);
        ghost.approveAction(pid);
        assertTrue(ghost.isAllowedMover(dex));

        uint256 amt = _mintGhost(alice, 10e6);
        vm.prank(alice);
        ghost.approve(dex, amt);
        vm.prank(dex);
        ghost.transferFrom(alice, dex, amt);
        assertEq(ghost.balanceOf(dex), amt);
    }

    function test_removingMover_needs2of3() public {
        _activate();
        vm.prank(guardian1);
        uint256 pid = ghost.proposeAllowedMover(market, false);
        vm.prank(guardian3);
        ghost.approveAction(pid);
        assertFalse(ghost.isAllowedMover(market));

        uint256 amt = _mintGhost(alice, 10e6);
        vm.prank(alice);
        ghost.approve(market, amt);
        vm.prank(market);
        vm.expectRevert();
        ghost.transferFrom(alice, market, amt);
    }
}
