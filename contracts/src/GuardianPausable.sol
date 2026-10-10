// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

/// @title GuardianPausable — pause globale gardée par un multisig SIMULÉ 3/3.
/// @notice 3 guardians figés au déploiement. Pause ET dépause exigent les 3 approbations
///         (même multisig). Aucun acteur seul (admin compris) ne peut pauser ni dépauser.
///         Les approbations sont comptées par « round » : `pauseRound` est incrémenté à chaque
///         action exécutée, ce qui remet les approbations à zéro.
///         Simplifications assumées : pas de révocation d'approbation, pas de rotation des guardians.
abstract contract GuardianPausable is Pausable {
    uint256 public constant GUARDIAN_COUNT = 3;
    uint256 public constant QUORUM = 3;

    mapping(address => bool) public isGuardian;
    address[3] internal _guardians;

    uint256 public pauseRound;
    uint256 public approvals;
    mapping(uint256 => mapping(address => bool)) public hasApproved;

    event GuardianApproval(address indexed guardian, uint256 indexed round, bool indexed pauseAction, uint256 approvals);

    error NotGuardian(address caller);
    error AlreadyApproved(address guardian, uint256 round);
    error InvalidGuardian(address guardian);

    modifier onlyGuardian() {
        if (!isGuardian[msg.sender]) revert NotGuardian(msg.sender);
        _;
    }

    constructor(address[3] memory guardians_) {
        for (uint256 i = 0; i < GUARDIAN_COUNT; i++) {
            address g = guardians_[i];
            if (g == address(0) || isGuardian[g]) revert InvalidGuardian(g);
            isGuardian[g] = true;
            _guardians[i] = g;
        }
    }

    /// @notice Approuve la pause ; la 3e approbation du round met le contrat en pause.
    function approvePause() external onlyGuardian whenNotPaused {
        if (_approve(true)) _pause();
    }

    /// @notice Approuve la dépause ; la 3e approbation du round lève la pause.
    function approveUnpause() external onlyGuardian whenPaused {
        if (_approve(false)) _unpause();
    }

    function guardians() external view returns (address[3] memory) {
        return _guardians;
    }

    /// @dev Enregistre l'approbation de `msg.sender` pour le round courant.
    ///      Retourne true si le quorum est atteint (round clos, approbations remises à zéro).
    function _approve(bool pauseAction) private returns (bool quorumReached) {
        uint256 round = pauseRound;
        if (hasApproved[round][msg.sender]) revert AlreadyApproved(msg.sender, round);
        hasApproved[round][msg.sender] = true;
        uint256 count = ++approvals;
        emit GuardianApproval(msg.sender, round, pauseAction, count);
        if (count == QUORUM) {
            pauseRound = round + 1;
            approvals = 0;
            return true;
        }
        return false;
    }
}
