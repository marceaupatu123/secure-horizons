// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IGhostToken — points d'entrée du M-Ghost appelés par M et par le minter.
/// @notice Interface figée (design §3.9). Toute modification sera annoncée sur l'issue #7.
///         Données fictives uniquement.
interface IGhostToken {
    /// @notice Hook de `GhostedStable._update` : un transfert de `amount` M de `from` vers `to`
    ///         a brûlé le M de `from` ; émet du Ghost frais (moins la marge d'entrée) à `to`.
    /// @dev Seul appelant : `underlying()` (`NotUnderlying` sinon) ; revert `EnforcedPause` en pause.
    function onUnderlyingTransfer(address from, address to, uint256 amount) external;

    /// @notice Émet `amount` Ghost frais à `to` pour la demande `requestId` traitée par
    ///         `ProtectedMinter.completeSwap`.
    /// @dev Seul appelant : le minter (`NotMinter` sinon) ; revert `EnforcedPause` en pause.
    function issueFromMinter(address to, uint256 amount, uint256 requestId) external;

    /// @notice Adresse du vrai token M (`GhostedStable`) adossé à ce Ghost.
    function underlying() external view returns (address);
}
