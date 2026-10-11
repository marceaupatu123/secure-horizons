// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {GhostBase} from "../utils/GhostBase.sol";

/// @notice Soupçon par adresse (design §3.3, OPEN_QUESTIONS §9) : montant absolu en deux
///         composantes (confirmé Sc, en attente Sp), porté par le ratio de l'EXPÉDITEUR, arrondi
///         vers le haut, conservé exactement, auto-expirant avec son incident.
contract GhostSuspicionTest is GhostBase {
    address internal dave = makeAddr("dave");
    uint64 internal constant LIFE = 3600; // = FACTOR × W, durée max d'un incident

    function setUp() public {
        _setUpGhost();
        // Offre légitime de fond : le budget de quarantaine (20 %) laisse marquer alice.
        _mintGhost(dave, 10_000e6);
        _mintMatured(alice, 100e6);
    }

    function _seedAlice(uint256 suspect) internal returns (uint256 id) {
        id = _delay(alice, suspect, LIFE);
    }

    function _sumSuspect() internal view returns (uint256) {
        return ghost.effectiveSuspectOf(alice) + ghost.effectiveSuspectOf(bob) + ghost.effectiveSuspectOf(carol)
            + ghost.effectiveSuspectOf(dave);
    }

    // ---------------------------------------------------------------- semis

    function test_seed_isPendingAndTagged() public {
        uint256 id = _seedAlice(10e18);
        (uint256 c, uint256 p, uint256 tag) = ghost.suspectComponentsOf(alice);
        assertEq(c, 0);
        assertEq(p, 10e18);
        assertEq(tag, id);
        assertEq(ghost.ratioOf(alice), 0.1e18);
        assertEq(ghost.totalSeeded(), 10e18);
    }

    /// @notice Le semis est plafonné au solde (part non confirmée).
    function test_seed_cappedAtBalance() public {
        _seedAlice(1_000e18);
        assertEq(ghost.effectiveSuspectOf(alice), 100e18);
        assertEq(ghost.totalSeeded(), 100e18);
    }

    // ---------------------------------------------------------------- propagation

    /// @notice Ratio de l'expéditeur emporté, moyenne pondérée chez le destinataire ; le ratio de
    ///         l'expéditeur ne change pas.
    function test_senderRatioCarried_weightedAverageAtRecipient() public {
        _mintMatured(bob, 50e6);
        _seedAlice(10e18); // ratio 10 %
        _transferGhost(alice, bob, 50e18);
        assertEq(ghost.effectiveSuspectOf(bob), 5e18);
        assertEq(ghost.effectiveSuspectOf(alice), 5e18);
        assertEq(ghost.ratioOf(alice), 0.1e18, "sender ratio changed");
        assertEq(ghost.ratioOf(bob), 0.05e18); // 5 / 100
    }

    /// @notice Arrondi vers le HAUT : 1 wei suspect sur 100 Ghost part entièrement avec 1 Ghost.
    function test_roundingUp_safeDirection() public {
        _seedAlice(1);
        _transferGhost(alice, bob, 1e18);
        assertEq(ghost.effectiveSuspectOf(bob), 1);
        assertEq(ghost.effectiveSuspectOf(alice), 0);
    }

    function testFuzz_moved_isCeilOfSenderRatio(uint256 suspect, uint256 v) public {
        suspect = bound(suspect, 1, 100e18);
        v = bound(v, 1, 100e18);
        _seedAlice(suspect);
        _transferGhost(alice, bob, v);
        uint256 expected = (v * suspect + 100e18 - 1) / 100e18;
        assertEq(ghost.effectiveSuspectOf(bob), expected);
        assertEq(ghost.effectiveSuspectOf(alice), suspect - expected);
        assertLe(ghost.effectiveSuspectOf(alice), ghost.balanceOf(alice), "S > balance");
    }

    /// @notice Conservation exacte le long d'une suite aléatoire de transferts (sans expiration,
    ///         destruction ni blanchiment) ; jamais plus de soupçon que de solde.
    function testFuzz_conservation_randomTransfers(uint256 seed, uint256 suspect) public {
        suspect = bound(suspect, 1, 100e18);
        _seedAlice(suspect);
        address[4] memory who = [alice, bob, carol, dave];
        for (uint256 i = 0; i < 20; i++) {
            uint256 r = uint256(keccak256(abi.encode(seed, i)));
            address from = who[r % 4];
            address to = who[(r >> 8) % 4];
            uint256 bal = ghost.balanceOf(from);
            if (bal != 0) _transferGhost(from, to, (r >> 16) % bal + 1);
            _skip((r >> 128) % 60); // reste dans la vie de l'incident (20 × 60 < LIFE)
            for (uint256 j = 0; j < 4; j++) {
                assertLe(ghost.effectiveSuspectOf(who[j]), ghost.balanceOf(who[j]), "S > balance");
            }
        }
        assertEq(_sumSuspect(), suspect, "suspicion not conserved");
    }

    /// @notice La dilution baisse le ratio, jamais le montant absolu.
    function test_dilution_keepsAbsoluteAmount() public {
        _seedAlice(10e18);
        _transferGhost(alice, bob, 50e18); // bob : 5 suspects sur 50
        assertEq(ghost.ratioOf(bob), 0.1e18);
        _transferGhost(dave, bob, 950e18);
        assertEq(ghost.effectiveSuspectOf(bob), 5e18, "dilution lowered the absolute amount");
        assertEq(ghost.ratioOf(bob), 0.005e18);
    }

    // ---------------------------------------------------------------- Sc / Sp

    /// @notice La confirmation fait basculer Sp en Sc (paresseusement, au prochain contact) ;
    ///         la valeur effective ne change pas.
    function test_confirm_movesPendingToConfirmed() public {
        uint256 id = _seedAlice(10e18);
        _confirm(id);
        (uint256 c, uint256 p, uint256 tag) = ghost.suspectComponentsOf(alice);
        assertEq(c + p, 10e18);
        assertEq(tag, p == 0 ? 0 : id);

        _transferGhost(alice, bob, 50e18); // normalise alice et bob
        (uint256 sc, uint256 sp, uint256 rawTag) = ghost.suspectRawOf(alice);
        assertEq(sc, 5e18);
        assertEq(sp, 0);
        assertEq(rawTag, 0);
        (sc, sp,) = ghost.suspectRawOf(bob);
        assertEq(sc, 5e18, "confirmed suspicion did not travel as confirmed");
        assertEq(sp, 0);

        // Le soupçon confirmé ne s'éteint plus avec le temps.
        _skip(10 * LIFE);
        assertEq(ghost.effectiveSuspectOf(alice), 5e18);
        assertEq(ghost.effectiveSuspectOf(bob), 5e18);
    }

    /// @notice Sc (incident 1 confirmé) et Sp (incident 2 vivant) voyagent chacun dans sa
    ///         composante ; le destinataire hérite de l'étiquette de l'incident vivant.
    function test_confirmedAndPending_travelSeparately() public {
        uint256 id1 = _seedAlice(10e18);
        _confirm(id1);
        _transferGhost(alice, dave, 1); // normalise : Sc(alice) = 10e18 - 1 wei au plus
        (uint256 sc0,,) = ghost.suspectRawOf(alice);
        uint256 id2 = _delay(alice, 30e18, LIFE);
        assertEq(id2, id1 + 1);
        (uint256 sc, uint256 sp, uint256 tag) = ghost.suspectRawOf(alice);
        assertEq(sc, sc0);
        assertEq(sp, 30e18);
        assertEq(tag, id2);

        uint256 bal = ghost.balanceOf(alice);
        _transferGhost(alice, bob, bal / 2);
        (uint256 bsc, uint256 bsp, uint256 btag) = ghost.suspectRawOf(bob);
        assertGt(bsc, 0);
        assertGt(bsp, 0);
        assertEq(btag, id2);
        assertEq(_sumSuspect(), sc0 + 30e18 + (10e18 - sc0), "not conserved");

        // L'incident 2 expire sans confirmation : seule la part confirmée reste.
        _skip(LIFE);
        assertEq(ghost.effectiveSuspectOf(bob), bsc);
    }

    // ---------------------------------------------------------------- expiration paresseuse

    /// @notice Silence = retour à la normale : après `expiresAt` sans confirmation, Sp ne compte
    ///         plus (vue), puis est effacé et compté expiré au prochain contact.
    function test_lazyExpiration() public {
        uint256 id = _delay(alice, 10e18, W);
        _transferGhost(alice, bob, 50e18); // bob hérite de 5e18 sous l'incident `id`
        (, uint64 expiresAt,,) = ghost.incidents(id);
        vm.warp(expiresAt - 1);
        assertEq(ghost.effectiveSuspectOf(alice), 5e18);
        vm.warp(expiresAt);
        assertEq(ghost.effectiveSuspectOf(alice), 0);
        assertEq(ghost.effectiveSuspectOf(bob), 0);
        (, uint256 p, uint256 tag) = ghost.suspectComponentsOf(alice);
        assertEq(p, 0);
        assertEq(tag, 0);
        (, uint256 rawSp, uint256 rawTag) = ghost.suspectRawOf(alice);
        assertEq(rawSp, 5e18, "raw pending erased without a write");
        assertEq(rawTag, id);

        _transferGhost(alice, carol, 1e18);
        (, rawSp, rawTag) = ghost.suspectRawOf(alice);
        assertEq(rawSp, 0);
        assertEq(rawTag, 0);
        assertEq(ghost.effectiveSuspectOf(carol), 0, "expired suspicion travelled");
        assertEq(ghost.totalSuspectExpired(), 5e18);
    }
}
