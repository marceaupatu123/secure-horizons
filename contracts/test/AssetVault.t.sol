// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {AssetGhost} from "../src/AssetGhost.sol";
import {AssetVault} from "../src/AssetVault.sol";
import {IAssetVault} from "../src/interfaces/IAssetVault.sol";

/// @notice Coffre d'actif + Ghost de paiement (#84 §10bis, itération 2). Vérifie les invariants
///         exigés qui ne dépendent que du coffre : aucun actif ne sort avant l'échéance, le coffre
///         couvre toujours le Ghost de paiement émis, et il n'existe aucune sortie vers le
///         protocole/multisig. Données FICTIVES (`MockUSDC`).
contract AssetVaultTest is Test {
    uint64 internal constant MATURITY = 1_000_000; // échéance du M' vendu (secondes Unix fictives)

    MockUSDC internal usdc;
    AssetVault internal vault;
    AssetGhost internal ghost;

    address internal router = makeAddr("router");
    address internal seller = makeAddr("seller");
    address internal buyer2 = makeAddr("buyer2");
    address internal carol = makeAddr("carol");

    function setUp() public {
        vm.warp(500_000); // avant l'échéance
        usdc = new MockUSDC();
        vault = new AssetVault(address(usdc), router);
        ghost = AssetGhost(vault.assetGhost());
    }

    /// @dev Le routeur bloque `amount` d'USDC et fait émettre autant de Ghost de paiement à `to`.
    function _lock(address to, uint256 amount, uint64 maturity) internal {
        usdc.mint(router, amount);
        vm.prank(router);
        usdc.transfer(address(vault), amount); // le routeur dépose l'actif
        vm.prank(router);
        vault.lockAndIssue(to, amount, maturity);
    }

    function _assertCoffreInvariant() internal view {
        assertGe(usdc.balanceOf(address(vault)), ghost.totalSupply(), "coffre < Ghost de paiement");
    }

    function _assertStorage(address a) internal view {
        (, uint256[] memory amts) = ghost.bucketsOf(a);
        uint256 s;
        for (uint256 i = 0; i < amts.length; i++) {
            s += amts[i];
        }
        assertEq(ghost.balanceOf(a), s, "balance != somme des tranches");
    }

    // ---------------------------------------------------------------- câblage

    function test_wiring() public view {
        assertEq(vault.asset(), address(usdc));
        assertEq(ghost.vault(), address(vault));
        assertEq(ghost.decimals(), usdc.decimals()); // 1:1, mêmes décimales
        assertEq(vault.router(), router);
    }

    function test_lockAndIssue_onlyRouter() public {
        usdc.mint(address(vault), 100e6);
        vm.prank(seller);
        vm.expectRevert(abi.encodeWithSelector(IAssetVault.NotRouter.selector, seller));
        vault.lockAndIssue(seller, 100e6, MATURITY);
    }

    function test_issueTo_onlyVault() public {
        vm.prank(seller);
        vm.expectRevert(abi.encodeWithSelector(AssetGhost.NotVault.selector, seller));
        ghost.issueTo(seller, 1, MATURITY);
    }

    // ---------------------------------------------------------------- invariant (1) : rien avant l'échéance

    function test_noAssetOutBeforeMaturity() public {
        _lock(seller, 100e6, MATURITY);
        assertEq(ghost.balanceOf(seller), 100e6);
        assertEq(ghost.maturedOf(seller), 0);

        vm.warp(MATURITY - 1);
        vm.prank(seller);
        vm.expectRevert(abi.encodeWithSelector(IAssetVault.NotMatured.selector, 0));
        vault.redeem(100e6);
        assertEq(usdc.balanceOf(seller), 0, "actif sorti avant l'echeance");

        vm.warp(MATURITY);
        assertEq(ghost.maturedOf(seller), 100e6);
        vm.prank(seller);
        assertEq(vault.redeem(100e6), 100e6);
        assertEq(usdc.balanceOf(seller), 100e6);
        assertEq(ghost.totalSupply(), 0);
        _assertCoffreInvariant();
    }

    // ---------------------------------------------------------------- invariant (2) : coffre >= Ghost

    function test_coffreCoversGhost_throughTransfersAndRedeems() public {
        _lock(seller, 100e6, MATURITY);
        _lock(buyer2, 40e6, MATURITY + 120);
        _assertCoffreInvariant();

        // Le Ghost de paiement circule librement, gardant son échéance.
        vm.prank(seller);
        ghost.transfer(carol, 30e6);
        _assertCoffreInvariant();
        _assertStorage(seller);
        _assertStorage(carol);
        (uint64[] memory mats,) = ghost.bucketsOf(carol);
        assertEq(mats[0], MATURITY, "echeance perdue au transfert");

        vm.warp(MATURITY);
        vm.prank(carol);
        vault.redeem(30e6);
        assertEq(usdc.balanceOf(carol), 30e6);
        _assertCoffreInvariant();

        // buyer2 n'est pas encore échu.
        assertEq(ghost.maturedOf(buyer2), 0);
        vm.warp(MATURITY + 120);
        vm.prank(buyer2);
        vault.redeem(40e6);
        _assertCoffreInvariant();
    }

    // ---------------------------------------------------------------- invariant (3) : pas de sortie (b) sans racine

    function test_restitute_revertsWithoutRoot() public {
        _lock(seller, 100e6, MATURITY);
        bytes32[] memory proof = new bytes32[](0);
        vm.expectRevert(IAssetVault.InvalidProof.selector);
        vault.restitute(carol, 10e6, 0, proof);
        assertEq(usdc.balanceOf(carol), 0);
        _assertCoffreInvariant();
    }

    // ---------------------------------------------------------------- échéances multiples, oldest-first

    function test_transfer_oldestFirst_keepsMaturities() public {
        _lock(seller, 100e6, MATURITY);
        _lock(seller, 50e6, MATURITY + 300);
        vm.prank(seller);
        ghost.transfer(carol, 120e6); // 100 @MATURITY puis 20 @MATURITY+300

        (uint64[] memory cm, uint256[] memory ca) = ghost.bucketsOf(carol);
        assertEq(cm.length, 2);
        assertEq(cm[0], MATURITY);
        assertEq(ca[0], 100e6);
        assertEq(cm[1], MATURITY + 300);
        assertEq(ca[1], 20e6);
        (uint64[] memory sm, uint256[] memory sa) = ghost.bucketsOf(seller);
        assertEq(sm.length, 1);
        assertEq(sm[0], MATURITY + 300);
        assertEq(sa[0], 30e6);
        _assertStorage(seller);
        _assertStorage(carol);

        vm.warp(MATURITY); // seul le lot @MATURITY est échu
        assertEq(ghost.maturedOf(carol), 100e6);
        vm.prank(carol);
        vault.redeem(100e6);
        assertEq(ghost.maturedOf(carol), 0);
        _assertCoffreInvariant();
    }

    // ---------------------------------------------------------------- fuzz : invariant du coffre

    function testFuzz_coffreInvariant(uint256 seed) public {
        address[3] memory who = [seller, buyer2, carol];
        for (uint256 i = 0; i < 20; i++) {
            uint256 r = uint256(keccak256(abi.encode(seed, i)));
            uint256 op = r % 3;
            address a = who[r % 3];
            address b = who[(r >> 8) % 3];
            if (op == 0) {
                _lock(a, (r >> 16) % 1_000e6 + 1, uint64(MATURITY + (r >> 32) % 1000));
            } else if (op == 1) {
                uint256 bal = ghost.balanceOf(a);
                if (bal != 0) {
                    vm.prank(a);
                    ghost.transfer(b, (r >> 16) % bal + 1);
                }
            } else {
                vm.warp(block.timestamp + (r >> 16) % 500);
                uint256 mat = ghost.maturedOf(a);
                if (mat != 0) {
                    vm.prank(a);
                    vault.redeem((r >> 48) % mat + 1);
                }
            }
            for (uint256 j = 0; j < 3; j++) {
                _assertStorage(who[j]);
            }
            _assertCoffreInvariant();
        }
    }
}
