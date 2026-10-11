// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IAssetVault — coffre d'UN actif réel, à DEUX sorties codées en dur (#84, OPEN_ANSWERS
///         §10bis points 2-4). Interface FIGÉE (itération 1) ; toute modification sera annoncée
///         sur l'issue #84. Données FICTIVES uniquement, jamais sur un vrai actif.
///
/// @notice Quand un acheteur paie un M' au routeur, l'actif réel (USDC, wBTC…) est **bloqué ici**
///         et le vendeur reçoit le **Ghost de cet actif** (`assetGhost`), 1:1, sans oracle ni prix
///         plancher. Le coffre ne peut ressortir l'actif que par :
///         - **(a) `redeem`** : le porteur du Ghost de paiement, À L'ÉCHÉANCE du M' vendu, convertit
///           son Ghost de paiement contre l'actif bloqué (1:1) ;
///         - **(b) `restitute`** : à une destruction confirmée 2/3 (§3), selon la règle fixe du
///           point 4, prouvée par une **racine de Merkle** (piste b de #85, PR #102).
///         AUCUNE autre sortie : ni vers le protocole, ni vers le multisig. Une clé volée ne peut
///         pas vider un coffre (c'est tout l'objet des deux sorties).
///
///         INVARIANTS (à vérifier par tests Foundry, #84) :
///         - `balance(asset) >= assetGhost.totalSupply()` à tout instant (I-COFFRE) ;
///         - aucun actif réel ne sort vers un vendeur avant l'échéance (`redeem` refusé avant) ;
///         - aucune sortie vers le protocole ni le multisig (il n'existe pas de fonction pour) ;
///         - `Σ restitutions ≤ argent bloqué derrière le Ghost de paiement des graines` ;
///         - conservation : `Σ redeem + Σ restitutions == Σ entrées` une fois tout dénoué.
interface IAssetVault {
    /// @notice L'actif réel bloqué (ERC-20 fictif).
    function asset() external view returns (address);

    /// @notice Le Ghost de paiement adossé 1:1 à cet actif (le « USDC-Ghost »).
    function assetGhost() external view returns (address);

    /// @notice Le routeur, seul autorisé à bloquer de l'actif et émettre du Ghost de paiement.
    function router() external view returns (address);

    /// @notice Total d'actif réel actuellement bloqué dans le coffre.
    function locked() external view returns (uint256);

    /// @notice Bloque `amount` d'actif (transféré par le routeur) et émet autant de Ghost de
    ///         paiement au `seller`, d'échéance `maturity` (= celle du M' vendu). Routeur seul.
    /// @dev Émet `AssetLocked`. Le Ghost de paiement circule ensuite librement (§10bis point 2).
    function lockAndIssue(address seller, uint256 amount, uint64 maturity) external;

    /// @notice SORTIE (a) : le porteur convertit `amount` de Ghost de paiement ÉCHU contre l'actif
    ///         réel, 1:1. Refusé avant l'échéance (`NotMatured`). Brûle le Ghost de paiement.
    /// @dev Émet `AssetRedeemed`.
    function redeem(uint256 amount) external returns (uint256 assetOut);

    /// @notice SORTIE (b) : restitution à une destruction confirmée 2/3, feuille prouvée contre la
    ///         `restitutionRoot` courante (règle du point 4 : d'abord aux porteurs brûlés du lot au
    ///         prorata, plafonné par leur prix payé ; le reste à celui qui a payé le voleur ; un
    ///         `PROTEGE` récupère son propre paiement). Idempotent par feuille (`AlreadyClaimed`).
    /// @dev Émet `Restituted`. L'actif ne sort QUE vers le `to` nommé dans la feuille prouvée.
    function restitute(address to, uint256 amount, uint256 nonce, bytes32[] calldata proof) external;

    event AssetLocked(address indexed seller, uint256 amount, uint64 maturity);
    event AssetRedeemed(address indexed holder, uint256 ghostIn, uint256 assetOut);
    event Restituted(address indexed to, uint256 amount, uint256 indexed nonce);

    error NotRouter(address caller);
    error NotMatured(uint64 maturity);
    error ZeroAmount();
    error InvalidProof();
    error AlreadyClaimed(uint256 nonce);
    error ExceedsLocked(uint256 amount, uint256 locked);
}
