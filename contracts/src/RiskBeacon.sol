// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IGhostRisk} from "./interfaces/IGhostRisk.sol";

/// @title RiskBeacon — balise de risque (volet 3, #7) : façade de LECTURE du M-Ghost.
/// @notice Aucune écriture de risque propre : tout le risque vit dans le Ghost (#8), avec les
///         permissions de §3 (OPEN_ANSWERS). La balise traduit ces vues en un état lisible par
///         les protocoles tiers (ex. `MockLendingMarket`) et publie des événements pour le
///         monitor. Ratios en 1e18, montants en 18 décimales, horodatages en secondes Unix.
///         Données FICTIVES uniquement.
contract RiskBeacon {
    /// @notice État publié, par priorité décroissante : PAUSE_GLOBALE, DETRUIT, RETARDE, NORMAL.
    enum State {
        NORMAL,
        RETARDE,
        DETRUIT,
        PAUSE_GLOBALE
    }

    struct Risk {
        uint256 ratio;
        uint256 suspectAmount;
        uint64 windowExpiresAt;
        State state;
        uint256 incidentId;
    }

    /// @notice Taille max d'un `publish` (borne le gaz d'un appel permissionless).
    uint256 public constant MAX_PUBLISH = 64;

    IGhostRisk public immutable ghost;

    event RiskPublished(
        address indexed account,
        uint256 ratio,
        uint256 suspectAmount,
        uint64 windowExpiresAt,
        State state,
        uint256 incidentId
    );

    error ZeroAddress();
    error TooManyAccounts(uint256 count, uint256 max);

    constructor(IGhostRisk ghost_) {
        if (address(ghost_) == address(0)) revert ZeroAddress();
        ghost = ghost_;
    }

    /// @notice Risque courant de `account`, lu dans le Ghost.
    /// @dev DETRUIT = une destruction a eu lieu et n'a pas été suivie d'un blanchiment 2/3
    ///      (`destroyedAt > clearedAt`) — règle PROVISOIRE, voir OPEN_QUESTIONS §14.
    ///      incidentId : incident de la destruction (DETRUIT), du retard (RETARDE, `extensionTag`
    ///      ou à défaut `pendingTag`), sinon `pendingTag` (0 si aucun).
    function riskOf(address account) public view returns (Risk memory risk) {
        risk.ratio = ghost.ratioOf(account);
        risk.suspectAmount = ghost.effectiveSuspectOf(account);
        risk.windowExpiresAt = ghost.extendedUntil(account);
        uint256 pending = ghost.pendingTag(account);
        uint64 destroyed = ghost.destroyedAt(account);

        if (ghost.paused()) {
            risk.state = State.PAUSE_GLOBALE;
            risk.incidentId = pending;
        } else if (destroyed != 0 && destroyed > ghost.clearedAt(account)) {
            risk.state = State.DETRUIT;
            risk.incidentId = ghost.destroyedIncident(account);
        } else if (risk.windowExpiresAt != 0) {
            risk.state = State.RETARDE;
            uint256 tag = ghost.extensionTag(account);
            risk.incidentId = tag != 0 ? tag : pending;
        } else {
            risk.state = State.NORMAL;
            risk.incidentId = pending;
        }
    }

    /// @notice Publie le risque courant de `accounts` en événements (permissionless, borné).
    /// @dev N'écrit aucun état : un appelant malveillant ne peut que dépenser son propre gaz.
    function publish(address[] calldata accounts) external {
        if (accounts.length > MAX_PUBLISH) revert TooManyAccounts(accounts.length, MAX_PUBLISH);
        for (uint256 i = 0; i < accounts.length; i++) {
            Risk memory r = riskOf(accounts[i]);
            emit RiskPublished(accounts[i], r.ratio, r.suspectAmount, r.windowExpiresAt, r.state, r.incidentId);
        }
    }
}
