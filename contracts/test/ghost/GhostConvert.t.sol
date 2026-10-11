// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {console} from "forge-std/console.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {GhostBase} from "../utils/GhostBase.sol";
import {GhostConfig, GhostToken} from "../../src/GhostToken.sol";

/// @notice Conversion Ghost -> M (design §3.5) : chacune des conditions isolément, verrou partiel
///         de la part suspecte, marge base + pente, M jamais repris.
contract GhostConvertTest is GhostBase {
    address internal dave = makeAddr("dave");
    uint64 internal constant LIFE = 3600;

    function setUp() public {
        _setUpGhost();
    }

    /// @dev Redéploie avec `cfg`, offre de fond chez dave (budget de quarantaine), puis `bob`
    ///      détient `bobUsdc` Ghost échu ENTIÈREMENT suspect (incident vivant de durée LIFE).
    function _world(GhostConfig memory cfg, uint256 bobUsdc) internal returns (uint256 id) {
        _setUpGhostWith(cfg);
        _mintGhost(dave, 100_000e6);
        _mintMatured(bob, bobUsdc);
        id = _delay(bob, type(uint128).max, LIFE); // plafonné au solde : Sp(bob) = balanceOf(bob)
        assertEq(ghost.effectiveSuspectOf(bob), ghost.balanceOf(bob));
    }

    /// @dev `who` reçoit exactement `v` Ghost suspect (bob est 100 % suspect) sans être retardé.
    function _taint(address who, uint256 v) internal {
        _transferGhost(bob, who, v);
    }

    // ---------------------------------------------------------------- conditions une à une

    function test_zeroAmount_reverts() public {
        _mintMatured(alice, 100e6);
        vm.prank(alice);
        vm.expectRevert(GhostToken.ZeroAmount.selector);
        ghost.convert(0);
    }

    /// @notice Solde nul : `NotMatured(amount, 0)` avant tout calcul de ratio (pas de division par 0).
    function test_zeroBalance_revertsNotMatured() public {
        vm.prank(carol);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.NotMatured.selector, 1e18, 0));
        ghost.convert(1e18);
    }

    function test_onlyMaturedPart() public {
        _mintMatured(alice, 100e6);
        _mintGhost(alice, 50e6);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.NotMatured.selector, 120e18, 100e18));
        ghost.convert(120e18);
        assertEq(_convert(alice, 100e18), 100e18);
    }

    /// @notice Adresse retardée par le surveillant (sans soupçon) : rien ne se convertit pendant
    ///         le retard ; silence = retour automatique.
    function test_windowExtended_blocksThenExpires() public {
        _mintGhost(dave, 10_000e6);
        _mintMatured(alice, 100e6);
        uint256 id = _delay(alice, 0, W);
        (, uint64 until,,) = ghost.incidents(id);
        assertEq(ghost.extendedUntil(alice), until);
        assertEq(ghost.convertibleOf(alice), 0);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.WindowExtended.selector, until));
        ghost.convert(1e18);

        vm.warp(until);
        assertEq(ghost.extendedUntil(alice), 0);
        assertEq(_convert(alice, 100e18), 100e18);
    }

    /// @notice Seuils à 0 (fixture par défaut) : 1 wei suspect reçu bloque la conversion. C'est la
    ///         limite « poussière » documentée au README : mesurée ici, pas estimée.
    function test_dustGriefing_thresholdsZero() public {
        _world(_ghostConfig(), 100e6);
        _mintMatured(alice, 10_000e6);
        _taint(alice, 1);
        assertEq(ghost.extendedUntil(alice), 0, "alice herself is not delayed");
        assertEq(ghost.convertibleOf(alice), 0);
        uint256 ratioUp = (1 * ONE + ghost.balanceOf(alice) - 1) / ghost.balanceOf(alice);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.SuspicionAboveThreshold.selector, ratioUp, 1));
        ghost.convert(1e18);
        console.log("thresholds = 0: Ghost blocked by 1 wei of suspicion", ghost.balanceOf(alice));

        // Le blocage dure jusqu'à l'expiration de l'incident (silence), pas plus.
        _skip(LIFE);
        assertEq(ghost.convertibleOf(alice), ghost.balanceOf(alice));
    }

    /// @notice Le ratio comparé au seuil est arrondi vers le HAUT : un reste non nul juste
    ///         au-dessus de 1 % revert, exactement 1 % passe.
    function test_threshold_ratioRoundedUp() public {
        _world(_ghostConfigThresholds(), 200e6);
        _mintMatured(alice, 99e6);
        _transferGhost(alice, dave, 1); // alice : 99e18 − 1 propre
        _taint(alice, 1e18 + 1); // B = 100e18, S = 1e18 + 1 : ratio bas = 1 %, ratio haut > 1 %
        assertEq(ghost.ratioOf(alice), 0.01e18);
        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(GhostToken.SuspicionAboveThreshold.selector, 0.01e18 + 1, 1e18 + 1)
        );
        ghost.convert(1e18);

        _mintMatured(carol, 99e6);
        _taint(carol, 1e18); // exactement 1 %
        assertEq(_convert(carol, 99e18), 99e18);
    }

    /// @notice Seuil en montant absolu : petit ratio mais S > maxConvertSuspect ⇒ refus.
    function test_threshold_absoluteSuspect() public {
        _world(_ghostConfigThresholds(), 200e6);
        _mintMatured(alice, 50_000e6);
        _taint(alice, 101e18); // ratio ≈ 0,2 % < 1 %, mais 101 > 100
        assertLt(ghost.ratioOf(alice), 0.01e18);
        vm.prank(alice);
        vm.expectRevert();
        ghost.convert(1e18);
        assertEq(ghost.convertibleOf(alice), 0);
    }

    // ---------------------------------------------------------------- verrou partiel

    /// @notice Gros porteur avec 1 wei suspect (seuils > 0) : convertit tout sauf 1 wei ; la part
    ///         suspecte ne sort jamais et le soupçon ne bouge pas à la conversion.
    function test_partialLock_bigHolderConvertsAllButSuspect() public {
        _world(_ghostConfigThresholds(), 100e6);
        _mintMatured(alice, 10_000e6);
        _taint(alice, 1);
        uint256 bal = ghost.balanceOf(alice);
        assertEq(ghost.convertibleOf(alice), bal - 1);

        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.SuspectPartLocked.selector, bal, bal - 1));
        ghost.convert(bal);

        assertEq(_convert(alice, bal - 1), bal - 1);
        assertEq(ghost.balanceOf(alice), 1);
        assertEq(ghost.effectiveSuspectOf(alice), 1, "suspicion moved on conversion");
        assertEq(ghost.ratioOf(alice), ONE);
        assertEq(ghost.convertibleOf(alice), 0);
    }

    /// @notice Dispersion d'un Ghost 100 % suspect : rien ne sort, quels que soient les seuils.
    function test_partialLock_fullySuspectFanOutConvertsNothing() public {
        _world(_ghostConfigThresholds(), 100e6);
        address[8] memory sinks;
        for (uint256 i = 0; i < 8; i++) {
            sinks[i] = makeAddr(string(abi.encodePacked("sink", i)));
            _taint(sinks[i], 0.5e18); // 0,5 Ghost chacun, ratio 100 %
        }
        _warpPastWindow();
        for (uint256 i = 0; i < 8; i++) {
            assertEq(ghost.convertibleOf(sinks[i]), 0);
        }
    }

    // ---------------------------------------------------------------- marges et réserve

    /// @notice Marge = amount × (base + pente × ratio) ; M minté = amount − marge ; la réserve
    ///         augmente exactement de la marge.
    function test_fee_basePlusSlope_toReserve() public {
        GhostConfig memory cfg = _ghostConfigThresholds();
        cfg.maxConvertRatio = 0.5e18;
        cfg.convertFeeBaseBps = 50;
        cfg.convertFeeSlopeBps = 1_000;
        _world(cfg, 100e6);
        _mintMatured(alice, 90e6);
        _taint(alice, 10e18); // ratio 10 %
        uint256 reserveBefore = ghost.reserve();

        uint256 out = _convert(alice, 90e18);
        uint256 fee = 90e18 * (50 + 1_000 * 0.1e18 / ONE) / 10_000; // 150 bps
        assertEq(fee, 1.35e18);
        assertEq(out, 90e18 - fee);
        assertEq(m.balanceOf(alice), out);
        assertEq(ghost.totalFees(), fee);
        assertEq(ghost.reserve() - reserveBefore, fee);
        assertEq(ghost.lastReserveInflowAt(), block.timestamp);
        assertEq(ghost.totalConverted(), 90e18);
    }

    /// @notice Le M obtenu avant le gel n'est jamais repris : la destruction ne touche que le Ghost.
    function test_destroyAfterConversion_neverTakesM() public {
        uint256 id = _world(_ghostConfigThresholds(), 100e6);
        _mintMatured(alice, 99e6);
        _taint(alice, 1e18);
        _convert(alice, 99e18);
        uint256 mBefore = m.balanceOf(alice);

        _destroy(id, _one(alice));
        assertEq(m.balanceOf(alice), mBefore, "M taken back");
        assertEq(ghost.balanceOf(alice), 0);
        assertEq(ghost.totalSuspectBurned(), 1e18);
    }

    function test_convert_revertsWhenPaused() public {
        _mintMatured(alice, 100e6);
        _pauseGhost();
        vm.prank(alice);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        ghost.convert(1e18);
    }
}
