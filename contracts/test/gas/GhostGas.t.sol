// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {console} from "forge-std/console.sol";
import {GhostBase} from "../utils/GhostBase.sol";

/// @notice Mesures de gas du M-Ghost (design §8.4, #124). Chiffres AFFICHÉS, jamais assertés en dur
///         (`docs/CLAIMS.md`). Méthode : `vm.cool` sur les contrats touchés juste avant l'appel
///         mesuré (stockage froid, comme une transaction isolée), puis delta de `gasleft()`.
///         Gas d'exécution de l'appel, HORS coût intrinsèque de transaction (21 000) et avant
///         remboursements. Fixtures : W = 600 s, créneau 60 s (N = 10, anneau de 11).
contract GhostGasTest is GhostBase {
    address internal whale = makeAddr("whale");
    uint64 internal constant LIFE = 3600;

    function setUp() public {
        _setUpGhost();
        _mintGhost(whale, 1_000_000e6); // offre de fond : budget de quarantaine large
    }

    function _cool() internal {
        vm.cool(address(ghost));
        vm.cool(address(m));
        vm.cool(address(pm));
    }

    /// @dev Refroidit le stockage puis renvoie gasleft() : la mesure est le delta autour de l'appel
    ///      (inclut le surcoût d'appel, quelques milliers de gas).
    function _start() internal returns (uint256) {
        _cool();
        return gasleft();
    }

    /// @dev `who` reçoit 11 tranches vivantes distinctes (une par créneau, instant non aligné).
    function _fillRing(address who) internal {
        for (uint256 k = 0; k < W / SLOT + 1; k++) {
            _mintGhost(who, 1e6);
            if (k < W / SLOT) _skip(SLOT);
        }
    }

    /// @notice Référence : transfert ERC-20 OpenZeppelin simple (MockUSDC), même méthode.
    function test_gas_baselineErc20Transfer() public {
        usdc.mint(alice, 100e6);
        uint256 g = _start();
        vm.cool(address(usdc));
        vm.prank(alice);
        usdc.transfer(bob, 10e6);
        console.log("gas reference ERC-20, destinataire vide", g - gasleft());
        g = _start();
        vm.cool(address(usdc));
        vm.prank(alice);
        usdc.transfer(bob, 10e6);
        console.log("gas reference ERC-20, destinataire deja credite", g - gasleft());
    }

    function test_gas_transferCommon_oneBucket() public {
        _mintGhost(alice, 100e6);
        uint256 g = _start();
        _transferGhost(alice, bob, 10e18);
        console.log("gas transfer Ghost, 1 tranche, destinataire vide", g - gasleft());

        g = _start();
        _transferGhost(alice, bob, 10e18);
        console.log("gas transfer Ghost, 1 tranche, tranche deja presente", g - gasleft());
    }

    /// @notice Cas courant avec propagation du soupçon et `extendedBalance` des deux côtés.
    function test_gas_transferCommon_suspectBothTagged() public {
        _mintGhost(alice, 100e6);
        _mintGhost(bob, 100e6);
        _delayMany(_two(alice, bob), _amounts2(10e18, 0), LIFE);
        uint256 g = _start();
        _transferGhost(alice, bob, 10e18);
        console.log("gas transfer Ghost, soupcon + 2 comptes dans l'incident", g - gasleft());
    }

    /// @notice Pire cas : expéditeur avec N + 1 tranches vivantes distinctes, soupçon, comptes
    ///         dans l'incident ; destinataire vide (11 premiers remplissages de slots).
    function test_gas_transferWorst_freshRecipient() public {
        vm.warp(T0 + 7);
        _fillRing(alice);
        (uint64[] memory mats,) = ghost.bucketsOf(alice);
        assertEq(mats.length, W / SLOT + 1, "ring not full");
        _delayMany(_two(alice, bob), _amounts2(5e18, 0), LIFE);
        uint256 bal = ghost.balanceOf(alice);
        uint256 g = _start();
        _transferGhost(alice, bob, bal);
        console.log("gas transfer Ghost, PIRE cas (11 tranches -> destinataire vide)", g - gasleft());
    }

    /// @notice Pire cas bis : le destinataire a 11 tranches échues non réglées (réglage + remplissage).
    function test_gas_transferWorst_recipientFullRing() public {
        vm.warp(T0 + 7);
        _fillRing(bob);
        _skip(W + SLOT); // les 11 tranches de bob sont échues, non réglées
        _fillRing(alice);
        _delayMany(_two(alice, bob), _amounts2(5e18, 0), LIFE);
        uint256 bal = ghost.balanceOf(alice);
        uint256 g = _start();
        _transferGhost(alice, bob, bal);
        console.log("gas transfer Ghost, PIRE cas bis (11 -> 11 echues a regler)", g - gasleft());
    }

    function test_gas_transferM_hook() public {
        _mintMatured(alice, 100e6);
        _convert(alice, 100e18);
        uint256 g = _start();
        vm.prank(alice);
        m.transfer(bob, 10e18);
        console.log("gas transfer M (burn + Ghost frais)", g - gasleft());
    }

    function test_gas_convert() public {
        vm.warp(T0 + 7);
        _fillRing(alice);
        _warpPastWindow();
        uint256 c = ghost.convertibleOf(alice);
        uint256 g = _start();
        _convert(alice, c);
        console.log("gas convert (11 tranches echues a regler)", g - gasleft());
    }

    function test_gas_delay_1_and_64() public {
        _mintGhost(alice, 100e6);
        uint256 g = _start();
        _delay(alice, 1e18, LIFE);
        console.log("gas delay, 1 compte (ouvre l'incident)", g - gasleft());

        (address[] memory acc, uint256[] memory amts) = _sixtyFour();
        g = _start();
        _delayMany(acc, amts, LIFE);
        console.log("gas delay, 64 comptes (rejoint l'incident)", g - gasleft());
    }

    function test_gas_destroy_64() public {
        (address[] memory acc, uint256[] memory amts) = _sixtyFour();
        uint256 id = _delayMany(acc, amts, LIFE);
        vm.prank(guardian1);
        uint256 pid = ghost.proposeDestroy(id, acc);
        uint256 g = _start();
        vm.prank(guardian2);
        ghost.approveAction(pid);
        console.log("gas destruction 2/3, 64 cibles (approbation qui execute)", g - gasleft());
        assertEq(ghost.totalSuspectBurned(), 64 * 1e18);
    }

    // ---------------------------------------------------------------- utilitaires

    function _amounts2(uint256 a, uint256 b) internal pure returns (uint256[] memory arr) {
        arr = new uint256[](2);
        (arr[0], arr[1]) = (a, b);
    }

    /// @dev 64 comptes distincts avec 10 Ghost chacun et 1 Ghost suspect à semer.
    function _sixtyFour() internal returns (address[] memory acc, uint256[] memory amts) {
        acc = new address[](64);
        amts = new uint256[](64);
        for (uint256 i = 0; i < 64; i++) {
            acc[i] = address(uint160(0x10000 + i));
            _mintGhost(acc[i], 10e6);
            amts[i] = 1e18;
        }
    }
}
