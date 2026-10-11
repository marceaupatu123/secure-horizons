// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title VaultGuardians — multisig SIMULÉ 2/3 générique pour les actions du coffre (#84).
/// @notice Mêmes 3 guardians que le `GhostToken` (#8), passés par le routeur à la création du
///         coffre. Une action est identifiée par le hash de ses arguments ; deux approbations de
///         guardians DISTINCTS l'exécutent, une fois (`AlreadyExecuted`). Simplifications assumées
///         (comme `GuardianActions` de #8) : pas d'expiration, pas de révocation, pas de rotation.
abstract contract VaultGuardians {
    uint256 public constant VAULT_QUORUM = 2;

    mapping(address => bool) public isGuardian;
    address[3] internal _guardians;

    mapping(bytes32 => uint8) public actionApprovals;
    mapping(bytes32 => mapping(address => bool)) public actionApprovedBy;
    mapping(bytes32 => bool) public actionExecuted;

    event VaultActionApproved(bytes32 indexed action, address indexed guardian, uint8 approvals);
    event VaultActionExecuted(bytes32 indexed action);

    error NotGuardian(address caller);
    error ActionAlreadyApproved(address guardian, bytes32 action);
    error ActionAlreadyExecuted(bytes32 action);
    error InvalidGuardian(address guardian);

    modifier onlyGuardian() {
        if (!isGuardian[msg.sender]) revert NotGuardian(msg.sender);
        _;
    }

    constructor(address[3] memory guardians_) {
        for (uint256 i = 0; i < 3; i++) {
            address g = guardians_[i];
            if (g == address(0) || isGuardian[g]) revert InvalidGuardian(g);
            isGuardian[g] = true;
            _guardians[i] = g;
        }
    }

    function guardians() external view returns (address[3] memory) {
        return _guardians;
    }

    /// @dev Enregistre l'approbation de `msg.sender` pour `action` ; retourne true au quorum
    ///      (l'action est alors marquée exécutée, l'appelant effectue l'effet).
    function _vote(bytes32 action) internal returns (bool reached) {
        if (actionExecuted[action]) revert ActionAlreadyExecuted(action);
        if (actionApprovedBy[action][msg.sender]) revert ActionAlreadyApproved(msg.sender, action);
        actionApprovedBy[action][msg.sender] = true;
        uint8 count = ++actionApprovals[action];
        emit VaultActionApproved(action, msg.sender, count);
        if (count >= VAULT_QUORUM) {
            actionExecuted[action] = true;
            emit VaultActionExecuted(action);
            return true;
        }
        return false;
    }
}
