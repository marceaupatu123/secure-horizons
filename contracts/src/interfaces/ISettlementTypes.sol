// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ISettlementTypes — types partagés du règlement §10bis (#84).
/// @notice Statut d'une tranche d'échéance de M' (OPEN_ANSWERS §10bis, point 1). Le statut est
///         porté PAR LE ROUTEUR, pas par le `GhostToken` (le Ghost de #8 n'est pas modifié tant
///         que la PR #123 n'est pas mergée — choix d'agent, OPEN_QUESTIONS §16). Données FICTIVES.
interface ISettlementTypes {
    enum TrancheStatus {
        /// @dev Jamais reçu / inconnu. Par défaut, une tranche non suivie par le routeur.
        NONE,
        /// @dev Acheté contre du VRAI M via le routeur, paiement bloqué au coffre : à la
        ///      destruction, le porteur récupère son propre paiement bloqué (il ne perd rien).
        PROTEGE,
        /// @dev Acheté alors que c'était encore du M' (revente avant échéance) : porte le risque
        ///      `ratio × solde` (§9), pricé par la décote, réduit par la restitution.
        PUR,
        /// @dev Reçu SANS paiement on-chain (don, salaire direct) : si annulé, rien perdu on-chain,
        ///      recours hors chaîne. Un don ne donne JAMAIS `PROTEGE` (anti-blanchiment).
        CHEQUE
    }
}
