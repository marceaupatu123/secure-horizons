// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {GuardianPausable} from "./GuardianPausable.sol";

/// @title GuardianActions — actions humaines 2/3 (multisig SIMULÉ), rounds séparés de la pause 3/3.
/// @notice Même jeu de 3 guardians que `GuardianPausable`. Chaque `propose*` du contrat dérivé
///         compte comme 1re approbation du proposeur ; la 2e approbation (`approveAction`) exécute.
///         `executed` est posé AVANT l'exécution ; si l'exécution revert, toute la transaction
///         revert et la proposition reste ouverte à 1 approbation (design §3.10).
///         Simplifications assumées (comme `GuardianPausable`) : pas d'expiration ni de
///         révocation de proposition, pas de rotation des guardians.
abstract contract GuardianActions is GuardianPausable {
    enum ActionKind {
        Destroy,
        Restitution,
        Extend,
        Clear
    }

    struct Proposal {
        ActionKind kind;
        bool executed;
        uint8 approvals;
        bytes params;
    }

    uint256 public constant ACTION_QUORUM = 2;

    /// @notice Propositions, ids à partir de 1.
    mapping(uint256 => Proposal) public proposals;
    mapping(uint256 => mapping(address => bool)) public hasApprovedAction;
    uint256 public proposalCount;

    event ActionProposed(uint256 indexed proposalId, ActionKind indexed kind, address indexed proposer);
    event ActionApproved(uint256 indexed proposalId, address indexed guardian, uint256 approvals);
    event ActionExecuted(uint256 indexed proposalId, ActionKind indexed kind);

    error UnknownProposal(uint256 proposalId);
    error AlreadyExecuted(uint256 proposalId);
    /// @dev `AlreadyApproved` existe déjà dans `GuardianPausable` (rounds de pause).
    error ActionAlreadyApproved(address guardian, uint256 proposalId);

    constructor(address[3] memory guardians_) GuardianPausable(guardians_) {}

    /// @notice 2e approbation d'une proposition 2/3 ; exécute au quorum. Nom distinct de
    ///         `ERC20.approve(address,uint256)` pour ne pas piéger les clients (ethers, monitor).
    function approveAction(uint256 proposalId) external onlyGuardian {
        Proposal storage p = proposals[proposalId];
        if (p.approvals == 0) revert UnknownProposal(proposalId);
        if (p.executed) revert AlreadyExecuted(proposalId);
        if (hasApprovedAction[proposalId][msg.sender]) revert ActionAlreadyApproved(msg.sender, proposalId);
        hasApprovedAction[proposalId][msg.sender] = true;
        uint8 count = ++p.approvals;
        emit ActionApproved(proposalId, msg.sender, count);
        if (count >= ACTION_QUORUM) {
            p.executed = true;
            ActionKind kind = p.kind;
            _executeAction(proposalId, kind, p.params);
            emit ActionExecuted(proposalId, kind);
        }
    }

    /// @dev Enregistre une proposition ; le proposeur compte comme 1re approbation. Les fonctions
    ///      `propose*` du contrat dérivé portent `onlyGuardian` (vérifié avant tout autre contrôle).
    function _propose(ActionKind kind, bytes memory params) internal returns (uint256 proposalId) {
        proposalId = ++proposalCount;
        Proposal storage p = proposals[proposalId];
        p.kind = kind;
        p.approvals = 1;
        p.params = params;
        hasApprovedAction[proposalId][msg.sender] = true;
        emit ActionProposed(proposalId, kind, msg.sender);
        emit ActionApproved(proposalId, msg.sender, 1);
    }

    /// @dev Exécute l'action au quorum (implémenté par le contrat dérivé). Tous les contrôles
    ///      dépendant de l'état (réserve, vie de l'incident, borne cumulée, pause) sont faits ici.
    function _executeAction(uint256 proposalId, ActionKind kind, bytes memory params) internal virtual;
}
