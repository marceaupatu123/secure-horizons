// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20Errors} from "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";
import {GhostBase} from "../utils/GhostBase.sol";
import {GhostToken} from "../../src/GhostToken.sol";

/// @notice Tranches d'échéance du M-Ghost (`MaturityBuckets`, OPEN_ANSWERS §0bis-b, design §3.2).
///         Fixtures : W = 600 s, créneau 60 s (N = 10, anneau de 11). Seuils de conversion à 0.
contract GhostBucketsTest is GhostBase {
    uint256 internal constant U = 100e6; // 100 USDC fictifs -> 100e18 Ghost

    function setUp() public {
        _setUpGhost();
    }

    // ---------------------------------------------------------------- échéance fraîche

    function test_freshMaturity_alignedIsExactlyW() public {
        uint256 g = _mintGhost(alice, U);
        (uint64[] memory mats, uint256[] memory amts) = ghost.bucketsOf(alice);
        assertEq(mats.length, 1);
        assertEq(mats[0], T0 + W);
        assertEq(amts[0], g);
        _assertStorage(alice);
    }

    /// @notice Arrondi au créneau SUPÉRIEUR (sens sûr) : jamais d'échéance avant t + W.
    function test_freshMaturity_roundsUpToSlot() public {
        vm.warp(T0 + 1);
        _mintGhost(alice, U);
        (uint64[] memory mats,) = ghost.bucketsOf(alice);
        assertEq(mats[0], T0 + W + SLOT);
        assertGe(mats[0], block.timestamp + W);

        vm.warp(T0 + SLOT - 1);
        _mintGhost(bob, U);
        (mats,) = ghost.bucketsOf(bob);
        assertEq(mats[0], T0 + W + SLOT);
    }

    function testFuzz_freshMaturity_neverBeforeW(uint256 dt) public {
        dt = bound(dt, 0, 10 days);
        vm.warp(T0 + dt);
        _mintGhost(alice, U);
        (uint64[] memory mats,) = ghost.bucketsOf(alice);
        assertGe(mats[0], block.timestamp + W, "maturity before t + W");
        assertLt(mats[0], block.timestamp + W + SLOT, "more than one slot of rounding");
        assertEq(mats[0] % SLOT, 0, "maturity not on a slot boundary");
    }

    // ---------------------------------------------------------------- rien avant W

    function test_nothingConvertibleBeforeW() public {
        uint256 g = _mintGhost(alice, U);
        vm.warp(T0 + W - 1);
        assertEq(ghost.convertibleOf(alice), 0);
        assertEq(ghost.maturedEffectiveOf(alice), 0);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.NotMatured.selector, g, 0));
        ghost.convert(g);

        vm.warp(T0 + W);
        assertEq(ghost.convertibleOf(alice), g);
        assertEq(_convert(alice, g), g); // marges à 0
        assertEq(m.balanceOf(alice), g);
        assertEq(ghost.balanceOf(alice), 0);
        _assertStorage(alice);
    }

    // ---------------------------------------------------------------- transfert garde l'échéance

    /// @notice La circulation ne remet jamais le compteur à zéro (ni ne l'avance).
    function test_transferKeepsOriginalMaturity() public {
        _mintGhost(alice, U);
        vm.warp(T0 + 300);
        _transferGhost(alice, bob, 40e18);

        (uint64[] memory mats, uint256[] memory amts) = ghost.bucketsOf(bob);
        assertEq(mats.length, 1);
        assertEq(mats[0], T0 + W, "recipient got a new maturity");
        assertEq(amts[0], 40e18);

        vm.warp(T0 + W - 1);
        assertEq(ghost.convertibleOf(bob), 0, "transfer advanced maturity");
        vm.warp(T0 + W);
        assertEq(ghost.convertibleOf(bob), 40e18);
        assertEq(ghost.convertibleOf(alice), 60e18);
        _assertStorage(alice);
        _assertStorage(bob);
    }

    function test_transferFromKeepsOriginalMaturity() public {
        _mintGhost(alice, U);
        vm.prank(alice);
        ghost.approve(carol, 30e18);
        vm.warp(T0 + 120);
        vm.prank(carol);
        ghost.transferFrom(alice, bob, 30e18);
        (uint64[] memory mats,) = ghost.bucketsOf(bob);
        assertEq(mats[0], T0 + W);
        assertEq(ghost.allowance(alice, carol), 0);
    }

    // ---------------------------------------------------------------- plus anciennes d'abord

    function test_transferTakesOldestFirst() public {
        _mintGhost(alice, U); // échéance T0 + 600
        vm.warp(T0 + 120);
        _mintGhost(alice, 50e6); // échéance T0 + 720
        vm.warp(T0 + 180);

        assertEq(ghost.nextOutgoingMaturity(alice, 100e18), T0 + W);
        assertEq(ghost.nextOutgoingMaturity(alice, 120e18), T0 + 720);
        _transferGhost(alice, bob, 120e18);

        (uint64[] memory mats, uint256[] memory amts) = ghost.bucketsOf(bob);
        assertEq(mats.length, 2);
        assertEq(mats[0], T0 + W);
        assertEq(amts[0], 100e18);
        assertEq(mats[1], T0 + 720);
        assertEq(amts[1], 20e18);

        (mats, amts) = ghost.bucketsOf(alice);
        assertEq(mats.length, 1);
        assertEq(mats[0], T0 + 720);
        assertEq(amts[0], 30e18);
        _assertStorage(alice);
        _assertStorage(bob);
    }

    /// @notice La part échue part en premier : le destinataire peut convertir tout de suite.
    function test_transferTakesMaturedBeforeBuckets() public {
        _mintGhost(alice, U); // T0 + 600
        vm.warp(T0 + W);
        _mintGhost(alice, U); // T0 + 1200
        _transferGhost(alice, bob, 100e18);
        assertEq(ghost.convertibleOf(bob), 100e18);
        assertEq(ghost.maturedOf(bob), 100e18);
        assertEq(ghost.convertibleOf(alice), 0);
        _assertStorage(alice);
        _assertStorage(bob);
    }

    // ---------------------------------------------------------------- poussière

    /// @notice Recevoir 1 wei frais ne retarde pas le solde déjà échu du destinataire.
    function test_incomingDustDoesNotDelayExistingBalance() public {
        _mintMatured(alice, U);
        assertEq(ghost.convertibleOf(alice), 100e18);
        _mintGhost(bob, 1e6);
        _transferGhost(bob, alice, 1);
        assertEq(ghost.convertibleOf(alice), 100e18, "dust delayed the matured balance");
        assertEq(ghost.balanceOf(alice), 100e18 + 1);
        assertEq(_convert(alice, 100e18), 100e18);
        _assertStorage(alice);
    }

    // ---------------------------------------------------------------- anneau N + 1

    /// @notice 3 fenêtres d'émissions, une par créneau, à un instant non aligné : l'anneau de
    ///         N + 1 tranches boucle sans collision et la part échue reste exacte.
    function test_ringWrapsAroundOverSeveralWindows() public {
        vm.warp(T0 + 7); // non aligné : jusqu'à N + 1 tranches vivantes
        uint256 steps = 3 * (W / SLOT);
        uint256[] memory mintedAt = new uint256[](steps);
        for (uint256 i = 0; i < steps; i++) {
            mintedAt[i] = block.timestamp;
            _mintGhost(alice, 1e6);
            uint256 expected;
            for (uint256 j = 0; j <= i; j++) {
                if (_maturityAt(mintedAt[j]) <= block.timestamp) expected += 1e18;
            }
            assertEq(ghost.maturedEffectiveOf(alice), expected, "matured part");
            (uint64[] memory mats,) = ghost.bucketsOf(alice);
            assertLe(mats.length, W / SLOT + 1, "more live buckets than the ring");
            _assertStorage(alice);
            _skip(SLOT);
        }
        // Tout transférer : bob reçoit exactement les mêmes échéances (part échue comprise).
        (uint64[] memory aMats, uint256[] memory aAmts) = ghost.bucketsOf(alice);
        uint256 aMatured = ghost.maturedEffectiveOf(alice);
        _transferGhost(alice, bob, ghost.balanceOf(alice));
        (uint64[] memory bMats, uint256[] memory bAmts) = ghost.bucketsOf(bob);
        assertEq(ghost.maturedEffectiveOf(bob), aMatured);
        uint256 k;
        for (uint256 i = 0; i < aMats.length; i++) {
            if (aMats[i] <= block.timestamp) continue; // déjà dans la part échue
            assertEq(bMats[k], aMats[i]);
            assertEq(bAmts[k], aAmts[i]);
            k++;
        }
        assertEq(bMats.length, k);
        _assertStorage(alice);
        _assertStorage(bob);
    }

    // ---------------------------------------------------------------- invariant de stockage

    /// @notice `balanceOf == matured + Σ tranches` après une suite aléatoire de mints,
    ///         transferts, conversions et attentes ; Σ soldes conservé.
    function testFuzz_storageInvariant(uint256 seed) public {
        address[3] memory who = [alice, bob, carol];
        _mintGhost(alice, U);
        _mintGhost(bob, U);
        for (uint256 i = 0; i < 24; i++) {
            uint256 r = uint256(keccak256(abi.encode(seed, i)));
            address from = who[r % 3];
            address to = who[(r >> 8) % 3];
            uint256 op = (r >> 16) % 4;
            if (op == 0) {
                _mintGhost(from, ((r >> 24) % 50 + 1) * 1e6);
            } else if (op == 1) {
                uint256 bal = ghost.balanceOf(from);
                if (bal != 0) _transferGhost(from, to, (r >> 32) % bal + 1);
            } else if (op == 2) {
                uint256 c = ghost.convertibleOf(from);
                if (c != 0) _convert(from, (r >> 32) % c + 1);
            } else {
                _skip((r >> 32) % (2 * W));
            }
            for (uint256 j = 0; j < 3; j++) {
                _assertStorage(who[j]);
                assertLe(ghost.maturedEffectiveOf(who[j]), ghost.balanceOf(who[j]));
            }
        }
        assertEq(
            ghost.balanceOf(alice) + ghost.balanceOf(bob) + ghost.balanceOf(carol), ghost.totalSupply(), "sum"
        );
        assertEq(ghost.supplyValue(), ghost.totalIssued(), "value created or lost (no fee, no burn)");
    }

    // ---------------------------------------------------------------- cas neutres et erreurs

    function test_selfTransferIsNeutral() public {
        _mintGhost(alice, U);
        vm.warp(T0 + 60);
        _mintGhost(alice, U);
        (uint64[] memory m0, uint256[] memory a0) = ghost.bucketsOf(alice);
        _transferGhost(alice, alice, 150e18);
        (uint64[] memory m1, uint256[] memory a1) = ghost.bucketsOf(alice);
        assertEq(abi.encode(m0, a0), abi.encode(m1, a1));
        assertEq(ghost.balanceOf(alice), 200e18);
        _assertStorage(alice);
    }

    function test_zeroTransferIsNeutral() public {
        _mintGhost(alice, U);
        _transferGhost(alice, bob, 0);
        (uint64[] memory mats,) = ghost.bucketsOf(bob);
        assertEq(mats.length, 0);
        assertEq(ghost.balanceOf(bob), 0);
        _assertStorage(alice);
        _assertStorage(bob);
    }

    /// @notice Envoi > solde : erreur ERC-20 standard, pas une panique arithmétique.
    function test_transferAboveBalance_revertsInsufficientBalance() public {
        _mintGhost(alice, U);
        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(IERC20Errors.ERC20InsufficientBalance.selector, alice, 100e18, 100e18 + 1)
        );
        ghost.transfer(bob, 100e18 + 1);
    }

    // ---------------------------------------------------------------- règlement virtuel

    /// @notice Les vues comptent les tranches échues non encore réglées dans la part échue.
    function test_nextOutgoingMaturity_virtualSettle() public {
        _mintGhost(alice, U); // T0 + 600
        vm.warp(T0 + 60);
        _mintGhost(alice, 50e6); // T0 + 660
        vm.warp(T0 + W); // 1re tranche échue, pas encore réglée en stockage
        assertEq(ghost.maturedOf(alice), 0, "raw aggregate settled without a write");
        assertEq(ghost.maturedEffectiveOf(alice), 100e18);
        assertEq(ghost.nextOutgoingMaturity(alice, 100e18), 0);
        assertEq(ghost.nextOutgoingMaturity(alice, 120e18), T0 + 660);
        _transferGhost(alice, bob, 100e18);
        assertEq(ghost.maturedOf(bob), 100e18);
        assertEq(ghost.convertibleOf(bob), 100e18);
    }
}
