// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {GhostBase} from "./utils/GhostBase.sol";
import {SettlementRouter} from "../src/SettlementRouter.sol";
import {AssetVault} from "../src/AssetVault.sol";
import {AssetGhost} from "../src/AssetGhost.sol";
import {ISettlementTypes} from "../src/interfaces/ISettlementTypes.sol";
import {ISettlementRouter} from "../src/interfaces/ISettlementRouter.sol";

/// @notice Routeur de règlement (#84 §10bis, itération 3) : achat protégé, revente pure, statut.
///         Le M' est le M-Ghost (#8) déployé par `GhostBase`. Le vrai actif de paiement est un
///         second `MockUSDC` (données FICTIVES).
contract SettlementRouterTest is GhostBase {
    SettlementRouter internal router;
    // On réutilise `usdc` (MockUSDC de BaseTest) comme actif de paiement réel.

    address internal thief = makeAddr("thief"); // vendeur de M'
    address internal buyer = makeAddr("buyer");

    function setUp() public {
        _setUpGhost();
        router = new SettlementRouter(address(ghost));
    }

    function _giveMprime(address who, uint256 usdcAmount) internal returns (uint256 amount) {
        amount = _mintGhost(who, usdcAmount); // M' = M-Ghost frais, échéance T0 + W
    }

    function _fundAsset(address who, uint256 amount) internal {
        usdc.mint(who, amount);
        vm.prank(who);
        usdc.approve(address(router), amount);
    }

    // ---------------------------------------------------------------- achat protégé

    function test_buyWithAsset_protege_thenRedeemAtMaturity() public {
        uint256 mAmt = _giveMprime(thief, 100e6); // 100e18 M', échéance T0 + W
        vm.prank(thief);
        ghost.approve(address(router), mAmt);
        _fundAsset(buyer, 100e6);

        vm.prank(buyer);
        router.buyWithAsset(thief, mAmt, address(usdc), 100e6);

        // Coffre créé, actif bloqué, vendeur payé en Ghost de paiement 1:1.
        address vaultAddr = router.vaultOf(address(usdc));
        assertTrue(vaultAddr != address(0));
        AssetVault vault = AssetVault(vaultAddr);
        AssetGhost pay = AssetGhost(vault.assetGhost());
        assertEq(usdc.balanceOf(vaultAddr), 100e6, "actif non bloque");
        assertEq(pay.balanceOf(thief), 100e6, "vendeur non paye en Ghost de paiement");

        // L'acheteur a le M', étiqueté PROTEGE à l'échéance du M' vendu (T0 + W).
        assertEq(ghost.balanceOf(buyer), mAmt);
        assertEq(ghost.balanceOf(thief), 0);
        assertEq(
            uint8(router.statusOf(buyer, uint64(T0 + W))), uint8(ISettlementTypes.TrancheStatus.PROTEGE)
        );

        // Le Ghost de paiement du vendeur porte l'échéance du M' vendu : pas de sortie avant.
        (uint64[] memory mats,) = pay.bucketsOf(thief);
        assertEq(mats[0], uint64(T0 + W));
        vm.warp(T0 + W - 1);
        vm.prank(thief);
        vm.expectRevert();
        vault.redeem(100e6);

        // À l'échéance, le vendeur convertit son Ghost de paiement contre le vrai actif.
        vm.warp(T0 + W);
        vm.prank(thief);
        assertEq(vault.redeem(100e6), 100e6);
        assertEq(usdc.balanceOf(thief), 100e6);
        assertEq(usdc.balanceOf(vaultAddr), 0);
        assertGe(usdc.balanceOf(vaultAddr), pay.totalSupply()); // invariant coffre
    }

    function test_buyWithAsset_reusesVaultPerAsset() public {
        uint256 mAmt = _giveMprime(thief, 100e6);
        vm.prank(thief);
        ghost.approve(address(router), mAmt);
        _fundAsset(buyer, 100e6);
        vm.prank(buyer);
        router.buyWithAsset(thief, 40e18, address(usdc), 40e6);
        address v1 = router.vaultOf(address(usdc));
        vm.prank(buyer);
        router.buyWithAsset(thief, 10e18, address(usdc), 10e6);
        assertEq(router.vaultOf(address(usdc)), v1, "un coffre par actif");
    }

    function test_buyWithAsset_validation() public {
        vm.startPrank(buyer);
        vm.expectRevert(ISettlementRouter.ZeroAmount.selector);
        router.buyWithAsset(thief, 0, address(usdc), 1e6);
        vm.expectRevert(ISettlementRouter.ZeroAmount.selector);
        router.buyWithAsset(thief, 1e18, address(usdc), 0);
        vm.expectRevert(ISettlementRouter.ZeroAddress.selector);
        router.buyWithAsset(address(0), 1e18, address(usdc), 1e6);
        vm.stopPrank();
    }

    // ---------------------------------------------------------------- revente pure

    /// @notice Revente d'un M' (déjà protégé chez le vendeur) : l'acheteur devient PUR.
    function test_sellPure_marksBuyerPure() public {
        uint256 mAmt = _giveMprime(thief, 100e6);
        vm.prank(thief);
        ghost.approve(address(router), mAmt);
        _fundAsset(buyer, 100e6);
        vm.prank(buyer);
        router.buyWithAsset(thief, mAmt, address(usdc), 100e6); // buyer: PROTEGE

        // buyer revend 60 à carol, sans paiement on-chain (don simulé) -> carol PUR.
        vm.prank(buyer);
        ghost.approve(address(router), 60e18);
        vm.prank(carol);
        router.sellPure(buyer, 60e18, address(0), 0);
        assertEq(ghost.balanceOf(carol), 60e18);
        assertEq(uint8(router.statusOf(carol, uint64(T0 + W))), uint8(ISettlementTypes.TrancheStatus.PUR));
        // buyer reste PROTEGE sur sa part.
        assertEq(uint8(router.statusOf(buyer, uint64(T0 + W))), uint8(ISettlementTypes.TrancheStatus.PROTEGE));
    }

    /// @notice PUR ne se fait jamais surclasser en PROTEGE pour une même échéance (sens sûr).
    function test_pureNotUpgradedToProtege() public {
        uint256 mAmt = _giveMprime(thief, 200e6);
        vm.prank(thief);
        ghost.approve(address(router), mAmt);

        // carol devient PUR via une revente.
        vm.prank(carol);
        router.sellPure(thief, 50e18, address(0), 0);
        assertEq(uint8(router.statusOf(carol, uint64(T0 + W))), uint8(ISettlementTypes.TrancheStatus.PUR));

        // Un achat protégé ultérieur à la même échéance ne la repasse pas PROTEGE.
        _fundAsset(carol, 50e6);
        vm.prank(carol);
        router.buyWithAsset(thief, 50e18, address(usdc), 50e6);
        assertEq(uint8(router.statusOf(carol, uint64(T0 + W))), uint8(ISettlementTypes.TrancheStatus.PUR));
    }
}
