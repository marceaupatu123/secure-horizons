// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {GhostBase} from "../utils/GhostBase.sol";
import {GhostToken} from "../../src/GhostToken.sol";
import {GuardianActions} from "../../src/GuardianActions.sol";
import {GuardianPausable} from "../../src/GuardianPausable.sol";

/// @notice Actions humaines 2/3 (destruction, restitution, extension hors budget, blanchiment),
///         fonds d'assurance et pause globale 3/3 du Ghost (design §3.6 à §3.8, §3.10).
contract GhostGuardianTest is GhostBase {
    address internal dave = makeAddr("dave");
    uint64 internal constant LIFE = 3600;

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
        _mintGhost(dave, 10_000e6);
        _mintGhost(alice, 100e6);
        _mintGhost(bob, 100e6);
        _mintGhost(carol, 100e6);
        _warpPastWindow();
    }

    function _expiresAt(uint256 id) internal view returns (uint64 e) {
        (, e,,) = ghost.incidents(id);
    }

    function _proposal(uint256 pid) internal view returns (bool executed, uint8 approvals) {
        (, executed, approvals,) = ghost.proposals(pid);
    }

    // ---------------------------------------------------------------- quorum 2/3

    function test_destroy_needsTwoOfThree() public {
        uint256 id = _delay(alice, 10e18, W);
        vm.prank(guardian1);
        uint256 pid = ghost.proposeDestroy(id, _one(alice));
        assertEq(ghost.balanceOf(alice), 100e18, "one approval was enough");
        (bool executed, uint8 approvals) = _proposal(pid);
        assertFalse(executed);
        assertEq(approvals, 1);

        vm.prank(guardian2);
        ghost.approveAction(pid);
        assertEq(ghost.balanceOf(alice), 90e18);
        (executed, approvals) = _proposal(pid);
        assertTrue(executed);
        assertEq(approvals, 2);
    }

    function test_onlyGuardians() public {
        uint256 id = _delay(alice, 10e18, W);
        address[3] memory outsiders = [watcher, admin, attacker];
        for (uint256 i = 0; i < 3; i++) {
            vm.prank(outsiders[i]);
            vm.expectRevert(abi.encodeWithSelector(GuardianPausable.NotGuardian.selector, outsiders[i]));
            ghost.proposeDestroy(id, _one(alice));
        }
        vm.prank(guardian1);
        uint256 pid = ghost.proposeDestroy(id, _one(alice));
        vm.prank(watcher);
        vm.expectRevert(abi.encodeWithSelector(GuardianPausable.NotGuardian.selector, watcher));
        ghost.approveAction(pid);
    }

    /// @notice `approve` (ERC-20) n'est PAS `approveAction` : il ne fait qu'une allowance.
    function test_erc20Approve_doesNotExecuteProposal() public {
        uint256 id = _delay(alice, 10e18, W);
        vm.prank(guardian1);
        uint256 pid = ghost.proposeDestroy(id, _one(alice));
        vm.prank(guardian2);
        ghost.approve(address(ghost), pid);
        (bool executed,) = _proposal(pid);
        assertFalse(executed);
        assertEq(ghost.balanceOf(alice), 100e18);
    }

    function test_approvalErrors() public {
        uint256 id = _delay(alice, 10e18, W);
        vm.prank(guardian1);
        uint256 pid = ghost.proposeDestroy(id, _one(alice));
        vm.prank(guardian1);
        vm.expectRevert(abi.encodeWithSelector(GuardianActions.ActionAlreadyApproved.selector, guardian1, pid));
        ghost.approveAction(pid);
        vm.prank(guardian2);
        ghost.approveAction(pid);
        vm.prank(guardian3);
        vm.expectRevert(abi.encodeWithSelector(GuardianActions.AlreadyExecuted.selector, pid));
        ghost.approveAction(pid);
        vm.prank(guardian3);
        vm.expectRevert(abi.encodeWithSelector(GuardianActions.UnknownProposal.selector, 99));
        ghost.approveAction(99);
    }

    /// @notice Les rounds 2/3 sont indépendants des rounds de pause 3/3.
    function test_actionRounds_independentOfPauseRounds() public {
        vm.prank(guardian1);
        ghost.approvePause();
        uint256 id = _delay(alice, 10e18, W);
        _destroy(id, _one(alice));
        assertEq(ghost.approvals(), 1, "action touched the pause round");
        assertEq(ghost.pauseRound(), 0);
        assertFalse(ghost.paused());
    }

    function test_proposalValidation() public {
        vm.startPrank(guardian1);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.UnknownIncident.selector, 0));
        ghost.proposeDestroy(0, new address[](0));
        vm.expectRevert(abi.encodeWithSelector(GhostToken.UnknownIncident.selector, 1));
        ghost.proposeDestroy(1, new address[](0));
        vm.expectRevert(abi.encodeWithSelector(GhostToken.BatchTooLarge.selector, 65));
        ghost.proposeDestroy(1, new address[](65));
        vm.expectRevert(GhostToken.ZeroAddress.selector);
        ghost.proposeDestroy(1, _one(address(0)));
        vm.expectRevert(GhostToken.ZeroAddress.selector);
        ghost.proposeRestitution(address(0), 1);
        vm.expectRevert(GhostToken.ZeroAmount.selector);
        ghost.proposeRestitution(carol, 0);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.BatchTooLarge.selector, 0));
        ghost.proposeClear(new address[](0));
        vm.expectRevert(GhostToken.LengthMismatch.selector);
        ghost.proposeExtend(_two(alice, bob), _oneAmount(0), W);
        vm.expectRevert(GhostToken.InvalidDuration.selector);
        ghost.proposeExtend(_one(alice), _oneAmount(0), 0);
        vm.expectRevert(
            abi.encodeWithSelector(GhostToken.ExtensionTooLong.selector, address(0), uint64(block.timestamp + LIFE + 1))
        );
        ghost.proposeExtend(_one(alice), _oneAmount(0), LIFE + 1);
        vm.stopPrank();
    }

    // ---------------------------------------------------------------- destruction

    function test_emptyList_confirmsOnly() public {
        uint256 id = _delay(alice, 10e18, W);
        _confirm(id);
        (,, bool confirmed,) = ghost.incidents(id);
        assertTrue(confirmed);
        assertEq(ghost.balanceOf(alice), 100e18);
        // Confirmé : le soupçon ne s'éteint plus à expiresAt.
        _skip(10 * LIFE);
        assertEq(ghost.effectiveSuspectOf(alice), 10e18);
    }

    /// @notice Pas de résurrection : confirmer un incident expiré revert, la proposition reste ouverte.
    function test_destroy_expiredIncident_reverts() public {
        uint256 id = _delay(alice, 10e18, W);
        vm.warp(_expiresAt(id));
        vm.prank(guardian1);
        uint256 pid = ghost.proposeDestroy(id, _one(alice));
        vm.prank(guardian2);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.IncidentExpired.selector, id));
        ghost.approveAction(pid);
        (bool executed, uint8 approvals) = _proposal(pid);
        assertFalse(executed);
        assertEq(approvals, 1);
        assertEq(ghost.balanceOf(alice), 100e18);
    }

    /// @notice Brûle exactement Sc, en vidant d'abord les tranches les plus récentes (la part
    ///         échue du porteur de bonne foi est préservée au maximum) ; M intact.
    function test_destroy_burnsExactConfirmed_newestFirst() public {
        _mintGhost(alice, 50e6); // tranche fraîche
        uint256 id = _delay(alice, 60e18, W);
        uint256 supplyBefore = ghost.totalSupply();
        _destroy(id, _one(alice));

        assertEq(ghost.balanceOf(alice), 90e18);
        assertEq(ghost.totalSupply(), supplyBefore - 60e18);
        (uint64[] memory mats,) = ghost.bucketsOf(alice);
        assertEq(mats.length, 0, "fresh bucket not burned first");
        assertEq(ghost.maturedEffectiveOf(alice), 90e18);
        assertEq(ghost.effectiveSuspectOf(alice), 0);
        assertEq(ghost.destroyedAt(alice), block.timestamp);
        assertEq(ghost.destroyedIncident(alice), id);
        assertEq(ghost.totalBurned(), 60e18);
        assertEq(ghost.totalSuspectBurned(), 60e18);
        assertEq(ghost.reserve(), 60e18);
        _assertStorage(alice);
    }

    /// @notice Re-destruction sous l'incident 1 confirmé pendant que l'incident 2 est vivant :
    ///         seul Sc brûle, le Sp de l'incident 2 (sans quorum) est intact ; doublons tolérés.
    function test_redestroy_keepsOtherLiveIncidentPending() public {
        uint256 id1 = _delay(alice, 10e18, W);
        _confirm(id1);
        uint256 id2 = _delay(alice, 30e18, W);
        assertEq(id2, id1 + 1);

        address[] memory twice = _two(alice, alice);
        _destroy(id1, twice);
        assertEq(ghost.balanceOf(alice), 90e18);
        (uint256 sc, uint256 sp, uint256 tag) = ghost.suspectRawOf(alice);
        assertEq(sc, 0);
        assertEq(sp, 30e18, "pending suspicion of another live incident burned");
        assertEq(tag, id2);
        assertEq(ghost.totalSuspectBurned(), 10e18);
    }

    // ---------------------------------------------------------------- extension 2/3

    /// @notice Hors budget : refusé au surveillant, accepté en 2/3, toujours borné et
    ///         auto-expirant ; l'acteur des événements est le Ghost lui-même.
    function test_extend2of3_overBudget() public {
        vm.prank(watcher);
        vm.expectRevert();
        ghost.delay(_one(dave), _oneAmount(0), W);

        uint64 end = uint64(block.timestamp + W);
        vm.prank(guardian1);
        uint256 pid = ghost.proposeExtend(_one(dave), _oneAmount(0), W);
        vm.expectEmit(true, true, false, true, address(ghost));
        emit IncidentOpened(1, address(ghost), end);
        vm.expectEmit(true, true, true, true, address(ghost));
        emit PerimeterDelayed(1, dave, address(ghost), 0, end);
        vm.prank(guardian2);
        ghost.approveAction(pid);

        assertEq(ghost.extendedUntil(dave), end);
        vm.warp(end);
        assertEq(ghost.extendedUntil(dave), 0, "2/3 extension does not expire");
    }

    /// @notice `Extend` rejoint l'incident vivant (durée ignorée) ; le budget étant dépassé, tout
    ///         `delay` du surveillant revert jusqu'à `expiresAt`, puis passe.
    function test_extendOverBudget_blocksWatcherUntilExpiry() public {
        uint256 id = _delay(alice, 0, W);
        uint64 expiresAt = _expiresAt(id);
        _skip(100);
        _extend2of3(_one(dave), _oneAmount(0), LIFE);
        assertEq(_expiresAt(id), expiresAt, "Extend prolonged the incident");
        assertEq(ghost.extendedUntil(dave), expiresAt);

        vm.prank(watcher);
        vm.expectRevert();
        ghost.delay(_one(bob), _oneAmount(0), W);

        vm.warp(expiresAt);
        assertEq(_delay(bob, 0, W), id + 1);
    }

    /// @notice La borne cumulée vaut aussi pour la voie 2/3.
    function test_extend2of3_respectsCumulativeCap() public {
        uint256 t = block.timestamp;
        _extend2of3(_one(alice), _oneAmount(0), LIFE);
        vm.warp(t + LIFE);
        vm.prank(guardian1);
        uint256 pid = ghost.proposeExtend(_one(alice), _oneAmount(0), W);
        vm.prank(guardian2);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.ExtensionTooLong.selector, alice, uint64(t + LIFE + W)));
        ghost.approveAction(pid);
    }

    // ---------------------------------------------------------------- blanchiment

    /// @notice `Clear` 2/3 : Sc et Sp remis à 0, compté dans `totalSuspectCleared` ; l'extension
    ///         d'adresse n'est pas levée (elle expire seule).
    function test_clear_resetsSuspicionKeepsExtension() public {
        uint256 id1 = _delay(alice, 10e18, W);
        _confirm(id1);
        _delay(alice, 30e18, W); // Sc 10 + Sp 30 (incident 2)
        uint64 until = ghost.extendedUntil(alice);
        _clear(_one(alice));
        assertEq(ghost.effectiveSuspectOf(alice), 0);
        (uint256 sc, uint256 sp, uint256 tag) = ghost.suspectRawOf(alice);
        assertEq(sc + sp + tag, 0);
        assertEq(ghost.totalSuspectCleared(), 40e18);
        assertEq(ghost.clearedAt(alice), block.timestamp);
        assertEq(ghost.extendedUntil(alice), until, "Clear lifted the extension");
        assertEq(ghost.balanceOf(alice), 100e18, "Clear moved value");
    }

    // ---------------------------------------------------------------- restitution et assurance

    /// @notice Restitution plafonnée par la réserve : proposée avant que la réserve existe, elle
    ///         revert sans se fermer, puis s'exécute après une destruction.
    function test_restitution_proposedBeforeReserve_executesLater() public {
        address victim = makeAddr("victim");
        vm.prank(guardian1);
        uint256 pid = ghost.proposeRestitution(victim, 10e18);
        vm.prank(guardian2);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.ExceedsReserve.selector, 10e18, 0));
        ghost.approveAction(pid);
        (bool executed, uint8 approvals) = _proposal(pid);
        assertFalse(executed);
        assertEq(approvals, 1);

        uint256 id = _delay(alice, 10e18, W);
        _destroy(id, _one(alice));
        assertEq(ghost.reserve(), 10e18);

        vm.prank(guardian2);
        ghost.approveAction(pid);
        assertEq(ghost.balanceOf(victim), 10e18);
        (uint64[] memory mats,) = ghost.bucketsOf(victim);
        assertEq(mats[0], _maturityAt(block.timestamp), "restitution is not fresh Ghost");
        assertEq(ghost.totalRestituted(), 10e18);
        assertEq(ghost.reserve(), 0);
        assertLe(ghost.supplyValue(), ghost.totalIssued());
    }

    function test_sweepToInsurance_afterDelay() public {
        uint256 id = _delay(alice, 10e18, W);
        _destroy(id, _one(alice));
        uint64 availableAt = uint64(block.timestamp + 1 days);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.ClaimDelayNotElapsed.selector, availableAt));
        ghost.sweepToInsurance();

        vm.warp(availableAt);
        vm.prank(attacker); // permissionless
        assertEq(ghost.sweepToInsurance(), 10e18);
        assertEq(ghost.insuranceFund(), 10e18);
        assertEq(ghost.reserve(), 0);
        vm.expectRevert(GhostToken.NothingToSweep.selector);
        ghost.sweepToInsurance();

        vm.prank(guardian1);
        uint256 pid = ghost.proposeRestitution(carol, 1);
        vm.prank(guardian2);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.ExceedsReserve.selector, 1, 0));
        ghost.approveAction(pid);
    }

    // ---------------------------------------------------------------- pause 3/3

    /// @notice La pause bloque transferts, conversion, M, minter, surveillant, Extend et
    ///         restitution ; PAS la destruction ni le blanchiment (récupération humaine).
    function test_pause_blocksAllButDestroyAndClear() public {
        uint256 id = _delay(alice, 10e18, W);
        _convert(carol, 50e18); // carol détient du M
        uint256 req = _requestProtected(pm, bob, 1e6);
        vm.prank(guardian1);
        uint256 pidExtend = ghost.proposeExtend(_one(bob), _oneAmount(0), W);
        vm.prank(guardian1);
        uint256 pidRestitute = ghost.proposeRestitution(carol, 1);

        _pauseGhost();
        assertTrue(ghost.paused());

        vm.prank(bob);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        ghost.transfer(carol, 1);
        vm.prank(bob);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        ghost.convert(1);
        vm.prank(carol);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        m.transfer(bob, 1);
        vm.prank(service);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        pm.completeSwap(req);
        vm.prank(watcher);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        ghost.delay(_one(bob), _oneAmount(0), W);
        vm.prank(guardian2);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        ghost.approveAction(pidExtend);
        vm.prank(guardian2);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        ghost.approveAction(pidRestitute);

        _destroy(id, _one(alice)); // permis
        assertEq(ghost.balanceOf(alice), 90e18);
        _clear(_one(bob)); // permis
        assertEq(ghost.clearedAt(bob), block.timestamp);
    }
}
