// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ISettlementTypes} from "./ISettlementTypes.sol";

/// @title ISettlementRouter — routeur de règlement du M' (#84, OPEN_ANSWERS §10bis). Interface
///         FIGÉE (itération 1) ; toute modification sera annoncée sur l'issue #84. FICTIF.
///
/// @notice Pendant la fenêtre, le M' ne bouge QUE par ce routeur (DEX tiers et transfert direct
///         exclus — enforcement côté `GhostToken` différé tant que #123 n'est pas mergé, voir
///         OPEN_QUESTIONS §16). Le routeur attribue le statut de la tranche acquise (point 1) :
///         - `buyWithAsset` : l'acheteur paie un VRAI actif (bloqué au coffre), le vendeur reçoit
///           le Ghost de paiement 1:1, le M' passe vendeur -> acheteur en **PROTEGE** ;
///         - `sellPure` : revente de M' contre un Ghost de paiement déjà existant (ou don) -> la
///           tranche acquise est **PUR** chez l'acheteur ;
///         - une réception sans paiement on-chain enregistrée hors routeur est **CHEQUE**.
///         Le routeur ne garde jamais d'actif : il ne fait que router vers le coffre et le M'.
interface ISettlementRouter is ISettlementTypes {
    /// @notice Coffre déployé pour `asset` (adresse 0 si aucun). Un coffre par actif.
    function vaultOf(address asset) external view returns (address);

    /// @notice Statut de la tranche d'échéance `maturity` détenue par `account` (porté par le
    ///         routeur, pas par le Ghost). `NONE` si le routeur ne la suit pas.
    function statusOf(address account, uint64 maturity) external view returns (TrancheStatus);

    /// @notice Achat PROTÉGÉ : `msg.sender` paie `assetAmount` de `asset` (bloqué au coffre), le
    ///         `seller` reçoit autant de Ghost de paiement, et `mGhostAmount` de M' passe du
    ///         vendeur à l'acheteur, étiqueté `PROTEGE` à l'échéance vendue. Prix libre (décote du
    ///         marché, pas de prix plancher). Requiert l'allowance M' du vendeur au routeur.
    /// @dev Émet `Settled(..., PROTEGE)`.
    function buyWithAsset(address seller, uint256 mGhostAmount, address asset, uint256 assetAmount) external;

    /// @notice Revente PURE : `mGhostAmount` de M' passe du vendeur à `msg.sender`, étiqueté `PUR`.
    ///         Le paiement éventuel est un Ghost de paiement existant (jamais du vrai actif frais).
    /// @dev Émet `Settled(..., PUR)`.
    function sellPure(address seller, uint256 mGhostAmount, address paymentGhost, uint256 paymentAmount)
        external;

    event VaultCreated(address indexed asset, address indexed vault);
    event Settled(
        address indexed seller,
        address indexed buyer,
        uint256 mGhostAmount,
        uint64 maturity,
        TrancheStatus status
    );

    error NotMovableOutsideRouter();
    error UnknownAsset(address asset);
    error ZeroAmount();
    error ZeroAddress();
}
