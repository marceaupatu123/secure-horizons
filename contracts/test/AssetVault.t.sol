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
    address internal g1 = makeAddr("g1");
    address internal g2 = makeAddr("g2");
    address internal g3 = makeAddr("g3");

    function setUp() public {
        vm.warp(500_000); // avant l'échéance
        usdc = new MockUSDC();
        vault = new AssetVault(address(usdc), router, [g1, g2, g3]);
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

    // ---------------------------------------------------------------- destruction confirmée (2/3)

    function _leaf(address to, uint256 amount, uint256 nonce) internal pure returns (bytes32) {
        return keccak256(bytes.concat(keccak256(abi.encode(to, amount, nonce))));
    }

    function _burnSeed(address seed, uint256 amount, uint256 nonce) internal {
        vm.prank(g1);
        vault.burnSeedPayment(seed, amount, nonce);
        vm.prank(g2);
        vault.burnSeedPayment(seed, amount, nonce);
    }

    function _confirmRoot(bytes32 root) internal {
        vm.prank(g1);
        vault.confirmRestitutionRoot(root);
        vm.prank(g2);
        vault.confirmRestitutionRoot(root);
    }

    /// @notice Cas 1 §10bis : achat protégé, fraude confirmée → le Ghost de paiement du vendeur
    ///         (graine) est brûlé et l'acheteur protégé récupère la totalité de son paiement.
    ///         Vérifie l'invariant « un protégé ne perd rien » (côté argent) et la conservation.
    function test_destruction_cas1_protegeRecoversPayment() public {
        _lock(carol, 10e6, MATURITY); // le vendeur-graine (carol) reçoit 10 Ghost de paiement
        assertEq(ghost.balanceOf(carol), 10e6);

        // (1) brûler le Ghost de paiement de la graine : libère ses 10 bloqués.
        _burnSeed(carol, 10e6, 0);
        assertEq(ghost.totalSupply(), 0);
        assertGe(usdc.balanceOf(address(vault)), ghost.totalSupply());

        // (2) publier la racine payant l'acheteur protégé (buyer2) ses 10.
        bytes32 root = _leaf(buyer2, 10e6, 0);
        _confirmRoot(root);
        assertEq(vault.restitutionRoot(), root);

        bytes32[] memory proof = new bytes32[](0);
        vault.restitute(buyer2, 10e6, 0, proof);
        assertEq(usdc.balanceOf(buyer2), 10e6, "protege n'a pas recupere son paiement");
        assertEq(vault.locked(), 0);
        // Conservation : Σ redeem + Σ restitutions == Σ entrées.
        assertEq(vault.totalRedeemed() + vault.totalRestituted(), vault.totalLockedIn());
        // Restitution ≤ argent bloqué derrière le Ghost de paiement de la graine.
        assertLe(vault.totalRestituted(), 10e6);
    }

    function test_restitute_cannotExceedLocked() public {
        _lock(carol, 10e6, MATURITY);
        _burnSeed(carol, 10e6, 0);
        bytes32 root = _leaf(buyer2, 20e6, 0); // feuille abusive : plus que le bloqué
        _confirmRoot(root);
        bytes32[] memory proof = new bytes32[](0);
        vm.expectRevert(abi.encodeWithSelector(IAssetVault.ExceedsLocked.selector, 20e6, 10e6));
        vault.restitute(buyer2, 20e6, 0, proof);
    }

    function test_restitute_idempotentPerNonce() public {
        _lock(carol, 20e6, MATURITY);
        _burnSeed(carol, 20e6, 0);
        bytes32 root = _leaf(buyer2, 10e6, 7);
        _confirmRoot(root);
        bytes32[] memory proof = new bytes32[](0);
        vault.restitute(buyer2, 10e6, 7, proof);
        vm.expectRevert(abi.encodeWithSelector(IAssetVault.AlreadyClaimed.selector, 7));
        vault.restitute(buyer2, 10e6, 7, proof);
    }

    function test_destruction_requiresTwoGuardians() public {
        _lock(carol, 10e6, MATURITY);
        vm.prank(g1);
        vault.burnSeedPayment(carol, 10e6, 0); // 1 seule approbation : pas d'effet
        assertEq(ghost.balanceOf(carol), 10e6, "brule avec une seule approbation");
        vm.prank(g2);
        vault.burnSeedPayment(carol, 10e6, 0); // quorum atteint
        assertEq(ghost.balanceOf(carol), 0);
    }

    function test_burnSeed_onlyGuardian() public {
        _lock(carol, 10e6, MATURITY);
        vm.prank(seller);
        vm.expectRevert();
        vault.burnSeedPayment(carol, 10e6, 0);
    }

    /// @notice Une restitution ne peut pas puiser dans l'adossement d'un porteur de Ghost de
    ///         paiement SANS RAPPORT (autre vente) : l'invariant du coffre tient quoi que publie
    ///         le multisig. Ici seule la graine `carol` est brûlée ; le porteur honnête `buyer2`
    ///         reste intégralement adossé et peut convertir.
    function test_restitute_keepsOtherHolderBacked() public {
        _lock(carol, 10e6, MATURITY); // graine
        _lock(buyer2, 10e6, MATURITY); // vente honnête sans rapport
        assertEq(ghost.totalSupply(), 20e6);
        assertEq(vault.locked(), 20e6);

        _burnSeed(carol, 10e6, 0); // libère 10 ; offre restante = 10 (buyer2)
        assertEq(ghost.totalSupply(), 10e6);
        assertEq(vault.locked(), 20e6);

        bytes32[] memory proof = new bytes32[](0);
        // Racine abusive payant 20 au voleur : refusée (seul 10 est libéré).
        bytes32 greedy = _leaf(carol, 20e6, 0);
        _confirmRoot(greedy);
        vm.expectRevert(abi.encodeWithSelector(IAssetVault.ExceedsLocked.selector, 20e6, 10e6));
        vault.restitute(carol, 20e6, 0, proof);

        // Restitution correcte de 10 : le coffre reste adossé pour buyer2.
        bytes32 ok = _leaf(carol, 10e6, 1);
        _confirmRoot(ok);
        vault.restitute(carol, 10e6, 1, proof);
        assertEq(vault.locked(), 10e6);
        assertGe(vault.locked(), ghost.totalSupply()); // I-COFFRE préservé

        // buyer2 convertit l'intégralité à l'échéance.
        vm.warp(MATURITY);
        vm.prank(buyer2);
        assertEq(vault.redeem(10e6), 10e6);
        assertEq(usdc.balanceOf(buyer2), 10e6);
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
