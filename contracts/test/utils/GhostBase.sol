// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {BaseTest} from "./BaseTest.sol";
import {ProtectedMinter} from "../../src/ProtectedMinter.sol";
import {GhostedStable} from "../../src/GhostedStable.sol";
import {GhostConfig, GhostToken} from "../../src/GhostToken.sol";

/// @notice Base des tests du M-Ghost (#8, design §8.0) : déploiement complet (USDC fictif ->
///         ProtectedMinter -> GhostToken -> GhostedStable) et helpers d'actions.
///         Les valeurs de config sont des FIXTURES (W = 600 s, créneau 60 s), pas des mesures.
abstract contract GhostBase is BaseTest {
    /// @dev Instant de départ aligné sur un créneau : une émission à T0 échoit exactement à T0 + W.
    uint256 internal constant T0 = 1_200_000;
    uint256 internal constant ONE = 1e18;

    ProtectedMinter internal pm;
    GhostedStable internal m;
    GhostToken internal ghost;

    function _setUpGhost() internal {
        _setUpGhostWith(_ghostConfig());
    }

    function _setUpGhostWith(GhostConfig memory cfg) internal {
        vm.warp(T0);
        _deployUsdc();
        (pm, m, ghost) = _deployProtectedWith(cfg);
    }

    // ---------------------------------------------------------------- émission

    /// @dev Dépôt de `usdcAmount` (6 déc.) par `who` puis traitement par la clé de service :
    ///      `who` reçoit `usdcAmount × 1e12` Ghost frais. Retourne le montant Ghost émis.
    function _mintGhost(address who, uint256 usdcAmount) internal returns (uint256 amount) {
        uint256 id = _requestProtected(pm, who, usdcAmount);
        vm.prank(service);
        pm.completeSwap(id);
        amount = usdcAmount * SCALE;
    }

    /// @dev Émet du Ghost puis attend W + un créneau : tout est échu.
    function _mintMatured(address who, uint256 usdcAmount) internal returns (uint256 amount) {
        amount = _mintGhost(who, usdcAmount);
        _warpPastWindow();
    }

    /// @dev Avance au-delà de toute échéance fraîche émise maintenant (W + 1 créneau).
    function _warpPastWindow() internal {
        vm.warp(block.timestamp + W + SLOT);
    }

    function _skip(uint256 dt) internal {
        vm.warp(block.timestamp + dt);
    }

    /// @dev Échéance attendue d'une valeur entrée à `t` : ceil((t + W) / SLOT) * SLOT.
    function _maturityAt(uint256 t) internal pure returns (uint64) {
        return uint64(((t + W + SLOT - 1) / SLOT) * SLOT);
    }

    function _transferGhost(address from, address to, uint256 amount) internal {
        vm.prank(from);
        ghost.transfer(to, amount);
    }

    function _convert(address who, uint256 amount) internal returns (uint256 out) {
        vm.prank(who);
        out = ghost.convert(amount);
    }

    // ---------------------------------------------------------------- surveillant

    function _one(address a) internal pure returns (address[] memory arr) {
        arr = new address[](1);
        arr[0] = a;
    }

    function _oneAmount(uint256 v) internal pure returns (uint256[] memory arr) {
        arr = new uint256[](1);
        arr[0] = v;
    }

    function _two(address a, address b) internal pure returns (address[] memory arr) {
        arr = new address[](2);
        arr[0] = a;
        arr[1] = b;
    }

    /// @dev Le surveillant retarde un compte en semant `suspect`.
    function _delay(address a, uint256 suspect, uint64 duration) internal returns (uint256 id) {
        vm.prank(watcher);
        id = ghost.delay(_one(a), _oneAmount(suspect), duration);
    }

    function _delayMany(address[] memory accounts, uint256[] memory amounts, uint64 duration)
        internal
        returns (uint256 id)
    {
        vm.prank(watcher);
        id = ghost.delay(accounts, amounts, duration);
    }

    // ---------------------------------------------------------------- guardians 2/3

    /// @dev guardian1 propose, guardian2 approuve (exécution au quorum).
    function _destroy(uint256 incidentId, address[] memory targets) internal returns (uint256 pid) {
        vm.prank(guardian1);
        pid = ghost.proposeDestroy(incidentId, targets);
        vm.prank(guardian2);
        ghost.approveAction(pid);
    }

    /// @dev Confirmation seule (liste vide).
    function _confirm(uint256 incidentId) internal returns (uint256) {
        return _destroy(incidentId, new address[](0));
    }

    function _clear(address[] memory accounts) internal returns (uint256 pid) {
        vm.prank(guardian1);
        pid = ghost.proposeClear(accounts);
        vm.prank(guardian2);
        ghost.approveAction(pid);
    }

    function _restitute(address to, uint256 amount) internal returns (uint256 pid) {
        vm.prank(guardian1);
        pid = ghost.proposeRestitution(to, amount);
        vm.prank(guardian2);
        ghost.approveAction(pid);
    }

    function _extend2of3(address[] memory accounts, uint256[] memory amounts, uint64 duration)
        internal
        returns (uint256 pid)
    {
        vm.prank(guardian1);
        pid = ghost.proposeExtend(accounts, amounts, duration);
        vm.prank(guardian2);
        ghost.approveAction(pid);
    }

    /// @dev Pause 3/3 du Ghost (rounds de pause, distincts des actions 2/3).
    function _pauseGhost() internal {
        vm.prank(guardian1);
        ghost.approvePause();
        vm.prank(guardian2);
        ghost.approvePause();
        vm.prank(guardian3);
        ghost.approvePause();
    }

    // ---------------------------------------------------------------- vues

    /// @dev Σ des tranches non vides (échues non réglées comprises).
    function _bucketSum(address a) internal view returns (uint256 s) {
        (, uint256[] memory amounts) = ghost.bucketsOf(a);
        for (uint256 i = 0; i < amounts.length; i++) {
            s += amounts[i];
        }
    }

    /// @dev Invariant de stockage : balanceOf == matured + Σ tranches.
    function _assertStorage(address a) internal view {
        assertEq(ghost.balanceOf(a), ghost.maturedOf(a) + _bucketSum(a), "balance != matured + buckets");
    }
}
