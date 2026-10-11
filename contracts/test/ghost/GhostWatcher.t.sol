// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {console} from "forge-std/console.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {GhostBase} from "../utils/GhostBase.sol";
import {GhostToken} from "../../src/GhostToken.sol";

/// @notice Surveillant (`WATCHER_ROLE`, design §3.4) : il ne peut que RETARDER, borné par
///         `maxExtensionFactor × W` par incident et par série d'un compte, et par le budget de
///         quarantaine ; silence = retour automatique à la normale.
contract GhostWatcherTest is GhostBase {
    address internal dave = makeAddr("dave");
    uint64 internal constant LIFE = 3600; // FACTOR × W

    event IncidentOpened(uint256 indexed incidentId, address indexed actor, uint64 expiresAt);
    event PerimeterDelayed(
        uint256 indexed incidentId,
        address indexed account,
        address indexed actor,
        uint256 suspectAmount,
        uint64 extendedUntil
    );

    function setUp() public {
        _setUpGhost();
        _mintGhost(dave, 10_000e6); // offre de fond : budget 20 % ≈ 2 060 Ghost
        _mintGhost(alice, 100e6);
        _mintGhost(bob, 100e6);
        _mintGhost(carol, 100e6);
        _warpPastWindow();
    }

    function _expiresAt(uint256 id) internal view returns (uint64 e) {
        (, e,,) = ghost.incidents(id);
    }

    function _extBalance(uint256 id) internal view returns (uint256 b) {
        (,,, b) = ghost.incidents(id);
    }

    // ---------------------------------------------------------------- droits et validation

    function test_onlyWatcher() public {
        bytes32 role = ghost.WATCHER_ROLE();
        address[2] memory notWatchers = [alice, guardian1];
        for (uint256 i = 0; i < 2; i++) {
            vm.prank(notWatchers[i]);
            vm.expectRevert(
                abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, notWatchers[i], role)
            );
            ghost.delay(_one(alice), _oneAmount(1), W);
        }
    }

    function test_validation() public {
        vm.startPrank(watcher);
        vm.expectRevert(GhostToken.LengthMismatch.selector);
        ghost.delay(_two(alice, bob), _oneAmount(1), W);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.BatchTooLarge.selector, 0));
        ghost.delay(new address[](0), new uint256[](0), W);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.BatchTooLarge.selector, 65));
        ghost.delay(new address[](65), new uint256[](65), W);
        vm.expectRevert(GhostToken.ZeroAddress.selector);
        ghost.delay(_one(address(0)), _oneAmount(1), W);
        vm.expectRevert(GhostToken.InvalidDuration.selector);
        ghost.delay(_one(alice), _oneAmount(1), 0);
        vm.expectRevert(
            abi.encodeWithSelector(GhostToken.ExtensionTooLong.selector, address(0), uint64(block.timestamp + LIFE + 1))
        );
        ghost.delay(_one(alice), _oneAmount(1), LIFE + 1);
        vm.stopPrank();
    }

    function test_delay_revertsWhenPaused() public {
        _pauseGhost();
        vm.prank(watcher);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        ghost.delay(_one(alice), _oneAmount(1), W);
    }

    // ---------------------------------------------------------------- incidents

    /// @notice Ouverture puis ajout : rejoindre n'allonge jamais l'incident (`duration` ignorée).
    function test_openThenJoin_doesNotProlong() public {
        uint256 t = block.timestamp;
        uint256 id = _delay(alice, 1e18, W);
        assertEq(id, 1);
        assertEq(ghost.openIncidentId(), 1);
        assertEq(_expiresAt(1), t + W);

        _skip(100);
        uint256 id2 = _delay(bob, 1e18, LIFE);
        assertEq(id2, 1, "joined a new incident");
        assertEq(_expiresAt(1), t + W, "join prolonged the incident");
        assertEq(ghost.extendedUntil(bob), t + W);
        assertEq(ghost.pendingTag(bob), 1);
    }

    function test_confirmedIncident_opensNewOne() public {
        uint256 id1 = _delay(alice, 1e18, W);
        _confirm(id1);
        uint256 id2 = _delay(bob, 1e18, W);
        assertEq(id2, id1 + 1);
    }

    function test_expiredIncident_opensNewOne() public {
        uint256 id1 = _delay(alice, 1e18, W);
        vm.warp(_expiresAt(id1));
        assertEq(_delay(bob, 1e18, W), id1 + 1);
    }

    /// @notice Le semis ne fait que monter.
    function test_seed_onlyIncreases() public {
        _delay(alice, 10e18, W);
        _delay(alice, 5e18, W);
        assertEq(ghost.effectiveSuspectOf(alice), 10e18, "watcher lowered suspicion");
        _delay(alice, 20e18, W);
        assertEq(ghost.effectiveSuspectOf(alice), 20e18);
        assertEq(ghost.totalSeeded(), 20e18);
    }

    /// @notice Retard sans soupçon : seule la conversion est suspendue, la circulation continue.
    function test_circulationAllowed_conversionSuspended() public {
        _delay(alice, 0, W);
        assertEq(ghost.effectiveSuspectOf(alice), 0);
        assertEq(ghost.pendingTag(alice), 0);
        assertEq(ghost.convertibleOf(alice), 0);
        _transferGhost(alice, bob, 50e18);
        assertEq(ghost.convertibleOf(bob), 150e18, "clean recipient delayed");
    }

    // ---------------------------------------------------------------- budget de quarantaine

    /// @notice Budget dépassé : tout le lot revert, rien n'est écrit.
    function test_budgetExceeded_revertsWholeBatch() public {
        uint256 supply = ghost.supplyValue();
        vm.prank(watcher);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.QuarantineBudgetExceeded.selector, 10_100e18, supply));
        ghost.delay(_two(alice, dave), new uint256[](2), W);
        assertEq(ghost.openIncidentId(), 0);
        assertEq(ghost.extendedUntil(alice), 0);
    }

    /// @notice `extendedBalance` == Σ soldes des comptes comptés, après transfert, mint, transfert
    ///         de M et destruction.
    function test_extendedBalance_tracksSum() public {
        uint256 id = _delayMany(_two(alice, bob), new uint256[](2), W);
        assertEq(_extBalance(id), 200e18);

        _transferGhost(alice, carol, 30e18); // sortie du périmètre
        assertEq(_extBalance(id), ghost.balanceOf(alice) + ghost.balanceOf(bob));
        _transferGhost(carol, bob, 10e18); // entrée
        assertEq(_extBalance(id), ghost.balanceOf(alice) + ghost.balanceOf(bob));
        _mintGhost(alice, 50e6); // mint
        assertEq(_extBalance(id), ghost.balanceOf(alice) + ghost.balanceOf(bob));
        _convert(carol, 20e18);
        vm.prank(carol);
        m.transfer(bob, 20e18); // transfert de M -> Ghost frais
        assertEq(_extBalance(id), ghost.balanceOf(alice) + ghost.balanceOf(bob));

        _delay(alice, 40e18, W); // rejoint, semis sans double comptage
        assertEq(_extBalance(id), ghost.balanceOf(alice) + ghost.balanceOf(bob));
        _destroy(id, _one(alice)); // burn
        assertEq(ghost.balanceOf(alice), 80e18);
        assertEq(_extBalance(id), ghost.balanceOf(alice) + ghost.balanceOf(bob));
    }

    // ---------------------------------------------------------------- bornes de durée

    /// @notice Un second incident plus court ne raccourcit jamais une extension en cours.
    function test_shorterSecondIncident_doesNotShorten() public {
        uint256 t = block.timestamp;
        uint256 id1 = _delay(alice, 1e18, LIFE);
        _skip(100);
        _confirm(id1);
        _skip(100);
        uint256 id2 = _delay(alice, 1e18, 60);
        assertEq(id2, id1 + 1);
        assertEq(ghost.extendedUntil(alice), t + LIFE, "extension shortened");
        vm.warp(_expiresAt(id2));
        assertEq(ghost.extendedUntil(alice), t + LIFE);
        assertEq(ghost.convertibleOf(alice), 0);
    }

    /// @notice Incidents enchaînés au bloc d'expiration : la série d'un compte est bornée à
    ///         factor × W ; une nouvelle série n'est acceptée qu'après W sans extension.
    function test_chainedIncidents_cumulativeCap() public {
        uint256 t = block.timestamp;
        uint256 id;
        for (uint256 i = 0; i < FACTOR; i++) {
            id = _delay(alice, 0, W);
            assertEq(ghost.extendedUntil(alice), t + (i + 1) * W);
            vm.warp(_expiresAt(id));
        }
        assertEq(ghost.extensionRunStart(alice), t);
        vm.prank(watcher);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.ExtensionTooLong.selector, alice, uint64(t + LIFE + W)));
        ghost.delay(_one(alice), _oneAmount(0), W);

        vm.warp(t + LIFE + W - 1); // cooldown pas encore écoulé
        vm.prank(watcher);
        vm.expectRevert();
        ghost.delay(_one(alice), _oneAmount(0), W);

        vm.warp(t + LIFE + W); // W sans extension : nouvelle série
        _delay(alice, 0, W);
        assertEq(ghost.extensionRunStart(alice), t + LIFE + W);
    }

    /// @notice La vue `maxExtensionEnd` donne la borne exacte, avant et après le cooldown.
    function test_maxExtensionEnd_predictsRevert() public {
        uint256 t = block.timestamp;
        assertEq(ghost.maxExtensionEnd(alice), t + LIFE);
        uint256 id1 = _delay(alice, 0, W);
        _skip(300);
        _confirm(id1);
        uint64 maxEnd = ghost.maxExtensionEnd(alice);
        assertEq(maxEnd, t + LIFE);

        uint64 d = uint64(maxEnd - block.timestamp);
        vm.prank(watcher);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.ExtensionTooLong.selector, alice, maxEnd + 1));
        ghost.delay(_one(alice), _oneAmount(0), d + 1);
        _delay(alice, 0, d); // exactement la borne : accepté
        assertEq(ghost.extendedUntil(alice), maxEnd);

        vm.warp(uint256(maxEnd) + W - 1);
        assertEq(ghost.maxExtensionEnd(alice), t + LIFE, "cooldown not respected by the view");
        vm.warp(uint256(maxEnd) + W);
        assertEq(ghost.maxExtensionEnd(alice), block.timestamp + LIFE);
    }

    /// @notice Surveillant compromis qui ré-allonge au plus tôt pendant 10 périodes : la fraction
    ///         du temps retardé est bornée en TAUX (≤ factor / (factor + 1)), pas en durée totale.
    function test_frictionDutyCycle() public {
        uint256 start = block.timestamp;
        uint256 delayed;
        for (uint256 i = 0; i < 10; i++) {
            _delay(alice, 0, LIFE);
            uint256 until = ghost.extendedUntil(alice);
            delayed += until - block.timestamp;
            vm.warp(until + W); // premier instant où une nouvelle série est permise
        }
        uint256 elapsed = block.timestamp - start;
        uint256 dutyE18 = delayed * 1e18 / elapsed;
        console.log("watcher friction duty cycle (1e18)", dutyE18);
        assertLe(dutyE18, uint256(FACTOR) * 1e18 / (FACTOR + 1));
    }

    // ---------------------------------------------------------------- compte détecté tard

    /// @notice Un compte qui rejoint l'incident vivant n'est retenu que jusqu'à `expiresAt` :
    ///         la marge est la durée de vie restante (mesurée, limite écrite au README).
    function test_lateJoin_marginIsRemainingLifetime() public {
        uint256 id = _delay(alice, 1e18, W);
        _skip(W - 50);
        _transferGhost(alice, bob, 10e18); // le soupçon voyage déjà
        _delay(carol, 5e18, LIFE); // détecté tard : rejoint
        uint256 margin = ghost.extendedUntil(carol) - block.timestamp;
        console.log("late join margin (s)", margin);
        assertEq(margin, _expiresAt(id) - block.timestamp);
        vm.warp(_expiresAt(id));
        assertEq(ghost.effectiveSuspectOf(carol), 0);
        assertEq(ghost.extendedUntil(carol), 0);
    }

    // ---------------------------------------------------------------- dispersion (seuils > 0)

    /// @notice Compte marqué qui disperse vers 16 adresses diluées par du Ghost propre : aucune
    ///         ne convertit sa part suspecte avant `expiresAt`, Σ converti ≤ Σ propre.
    function test_fanOut16_noSuspectConversionBeforeExpiry() public {
        _setUpGhostWith(_ghostConfigThresholds());
        _mintGhost(dave, 10_000e6);
        address[16] memory sinks;
        for (uint256 i = 0; i < 16; i++) {
            sinks[i] = makeAddr(string(abi.encodePacked("sink", i)));
            _mintGhost(sinks[i], 1_000e6);
        }
        _mintGhost(alice, 100e6);
        _warpPastWindow();
        uint256 id = _delay(alice, 50e18, LIFE);

        uint256 converted;
        for (uint256 i = 0; i < 16; i++) {
            _transferGhost(alice, sinks[i], 6.25e18);
            uint256 c = ghost.convertibleOf(sinks[i]);
            assertEq(c, ghost.balanceOf(sinks[i]) - ghost.effectiveSuspectOf(sinks[i]));
            if (c != 0) converted += _convert(sinks[i], c);
        }
        uint256 suspectLeft = ghost.effectiveSuspectOf(alice);
        for (uint256 i = 0; i < 16; i++) {
            suspectLeft += ghost.effectiveSuspectOf(sinks[i]);
            assertEq(ghost.convertibleOf(sinks[i]), 0);
        }
        assertLt(block.timestamp, _expiresAt(id));
        assertEq(suspectLeft, 50e18, "suspect value left through conversion");
        assertLe(converted, 16 * 1_000e18 + 50e18, "converted more than the clean value");
    }

    // ---------------------------------------------------------------- événements et silence

    function test_events_actorIsWatcher() public {
        uint64 end = uint64(block.timestamp + W);
        vm.expectEmit(true, true, false, true, address(ghost));
        emit IncidentOpened(1, watcher, end);
        vm.expectEmit(true, true, true, true, address(ghost));
        emit PerimeterDelayed(1, alice, watcher, 7e18, end);
        _delay(alice, 7e18, W);
    }

    /// @notice Silence (aucune confirmation) : tout revient à la normale tout seul.
    function test_silence_returnsToNormal() public {
        uint256 id = _delay(alice, 30e18, W);
        vm.warp(_expiresAt(id));
        assertEq(ghost.extendedUntil(alice), 0);
        assertEq(ghost.effectiveSuspectOf(alice), 0);
        assertEq(ghost.convertibleOf(alice), 100e18);
        assertEq(_convert(alice, 100e18), 100e18);
    }
}
