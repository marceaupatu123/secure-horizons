// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IGhostRisk — vues de risque du M-Ghost lues par la balise (#7) et le pool (#65).
/// @notice Interface figée (design §3.11). Implémentée par `GhostToken`, ou par `GhostLens` si le
///         repli de taille n°2 est appliqué (design §1) : les consommateurs aval ne reçoivent
///         qu'une adresse `IGhostRisk`. Toute modification sera annoncée sur l'issue #7.
///         Conventions : ratios en virgule fixe 1e18 (arrondi bas) ; montants en unités du
///         token (18 décimales) ; horodatages en secondes Unix ; ids d'incident à partir de 1
///         (0 = aucun). Données fictives uniquement.
interface IGhostRisk {
    // ---------------------------------------------------------------- Soupçon (§3.3)

    /// @notice Montant absolu suspect valide `S = Sc + Sp_valide` de `account`.
    function effectiveSuspectOf(address account) external view returns (uint256);

    /// @notice Composantes du soupçon : confirmé (Sc), en attente encore valide (Sp, 0 si son
    ///         incident a expiré sans confirmation) et id d'incident portant Sp.
    function suspectComponentsOf(address account)
        external
        view
        returns (uint256 confirmed, uint256 pendingValid, uint256 pendingIncidentId);

    /// @notice Ratio suspect `S × 1e18 / balanceOf` (arrondi bas ; 0 si solde nul).
    function ratioOf(address account) external view returns (uint256);

    /// @notice Id de l'incident portant le soupçon en attente brut de `account` (0 si aucun).
    function pendingTag(address account) external view returns (uint256);

    // ---------------------------------------------------------------- Fenêtre allongée (§3.4)

    /// @notice Fin de la fenêtre allongée de `account` si elle est en cours, sinon 0.
    function extendedUntil(address account) external view returns (uint64);

    /// @notice Fin maximale qu'un nouveau retard peut donner à `account` (borne cumulée).
    function maxExtensionEnd(address account) external view returns (uint64);

    /// @notice Début de la série d'extensions contiguës de `account`.
    function extensionRunStart(address account) external view returns (uint64);

    /// @notice Dernier incident ayant compté `account` dans son budget de quarantaine.
    function extensionTag(address account) external view returns (uint256);

    // ---------------------------------------------------------------- Échéances (§3.2, §3.5)

    /// @notice Ghost convertible maintenant : 0 si fenêtre allongée ou seuils dépassés, sinon
    ///         `min(maturedEffectiveOf, balanceOf − S_valide)`.
    function convertibleOf(address account) external view returns (uint256);

    /// @notice Part temporellement échue (agrégé + tranches échues non encore réglées).
    function maturedEffectiveOf(address account) external view returns (uint256);

    /// @notice Agrégé échu brut stocké (sans règlement virtuel).
    function maturedOf(address account) external view returns (uint256);

    /// @notice Tranches non vides de `account` (échéances et montants), pour les tests.
    function bucketsOf(address account)
        external
        view
        returns (uint64[] memory maturities, uint256[] memory amounts);

    /// @notice Échéance la plus tardive parmi les tranches qui partiraient pour un envoi de
    ///         `amount` (règlement virtuel) ; 0 si tout vient de la part échue.
    function nextOutgoingMaturity(address account, uint256 amount) external view returns (uint64);

    // ---------------------------------------------------------------- Incidents, destruction, blanchiment

    /// @notice Incident `incidentId` (getter du mapping public `incidents`).
    function incidents(uint256 incidentId)
        external
        view
        returns (uint64 openedAt, uint64 expiresAt, bool confirmed, uint256 extendedBalance);

    /// @notice Dernier incident ouvert (0 si aucun).
    function openIncidentId() external view returns (uint256);

    /// @notice Horodatage de la dernière destruction exécutée sur `account` (0 si jamais).
    function destroyedAt(address account) external view returns (uint64);

    /// @notice Incident de la dernière destruction exécutée sur `account` (0 si jamais).
    function destroyedIncident(address account) external view returns (uint256);

    /// @notice Horodatage du dernier blanchiment 2/3 de `account` (0 si jamais).
    function clearedAt(address account) external view returns (uint64);

    // ---------------------------------------------------------------- Solvabilité (§3.7)

    /// @notice Réserve de restitution `totalIssued − supplyValue − insuranceFund`, saturée à 0.
    function reserve() external view returns (uint256);

    /// @notice Valeur de l'offre `M.totalSupply + Ghost.totalSupply`.
    function supplyValue() external view returns (uint256);

    /// @notice Ghost émis adossé au collatéral (== `ProtectedMinter.totalMinted`).
    function totalIssued() external view returns (uint256);

    // ---------------------------------------------------------------- Configuration immuable (§3.1)

    /// @notice Fenêtre W en secondes.
    function window() external view returns (uint64);

    /// @notice Durée d'un créneau d'échéance en secondes.
    function slot() external view returns (uint64);

    /// @notice Durée max d'une série de retards = `maxExtensionFactor × W`.
    function maxExtensionFactor() external view returns (uint32);

    /// @notice Part max de l'offre sous fenêtre allongée pour l'incident courant (bps).
    function quarantineBudgetBps() external view returns (uint16);

    /// @notice Ratio max (1e18, inclus) autorisant la conversion.
    function maxConvertRatio() external view returns (uint256);

    /// @notice Montant suspect absolu max (inclus) autorisant la conversion.
    function maxConvertSuspect() external view returns (uint256);

    /// @notice Marge Ghost -> M, partie fixe (bps).
    function convertFeeBaseBps() external view returns (uint16);

    /// @notice Marge Ghost -> M, partie indexée sur le ratio (bps).
    function convertFeeSlopeBps() external view returns (uint16);

    /// @notice Marge M -> Ghost sur un transfert de M (bps).
    function entryFeeBps() external view returns (uint16);

    /// @notice Délai avant bascule de la réserve au fonds d'assurance (secondes).
    function restitutionClaimDelay() external view returns (uint64);

    // ---------------------------------------------------------------- Pause (§3.8)

    /// @notice Pause globale 3/3 du Ghost.
    function paused() external view returns (bool);
}
