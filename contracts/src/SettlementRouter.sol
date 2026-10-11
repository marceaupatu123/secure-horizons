// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ISettlementRouter} from "./interfaces/ISettlementRouter.sol";
import {IGhostRisk} from "./interfaces/IGhostRisk.sol";
import {AssetVault} from "./AssetVault.sol";

/// @dev Vue minimale : les 3 guardians du M-Ghost (hérités de `GuardianPausable`), repris par
///      chaque coffre pour sa propre destruction 2/3 (§10bis point 4).
interface IGuardianSet {
    function guardians() external view returns (address[3] memory);
}

/// @title SettlementRouter — routeur de règlement du M' (#84, OPEN_ANSWERS §10bis). FICTIF.
/// @notice Voir `ISettlementRouter`. Itération 3 : `buyWithAsset` (PROTEGE), `sellPure` (PUR),
///         `statusOf`, un coffre par actif. Le M' est le M-Ghost (#8) ; le routeur le déplace par
///         `transferFrom` (allowance du vendeur). L'enforcement « le M' non échu ne bouge que par
///         un appelant autorisé » est porté par `GhostToken` (§10bis b′, #145) une fois
///         `initRouting` appelé avec ce routeur dans la liste ; avant, le routeur ne fait
///         qu'ÉTIQUETER les ventes.
contract SettlementRouter is ISettlementRouter, ReentrancyGuard {
    using SafeERC20 for IERC20;

    /// @notice Le M' (M-Ghost #8), déplacé par le routeur.
    address public immutable mGhost;

    mapping(address => address) internal _vaultOf;
    /// @dev Statut de la tranche d'échéance acquise, par (compte, échéance).
    mapping(address => mapping(uint64 => TrancheStatus)) internal _status;

    constructor(address mGhost_) {
        if (mGhost_ == address(0)) revert ZeroAddress();
        mGhost = mGhost_;
    }

    // ------------------------------------------------------------------ vues

    function vaultOf(address asset) external view returns (address) {
        return _vaultOf[asset];
    }

    function statusOf(address account, uint64 maturity) external view returns (TrancheStatus) {
        return _status[account][maturity];
    }

    // ------------------------------------------------------------------ achat protégé

    /// @inheritdoc ISettlementRouter
    function buyWithAsset(address seller, uint256 mGhostAmount, address asset, uint256 assetAmount)
        external
        nonReentrant
    {
        if (mGhostAmount == 0 || assetAmount == 0) revert ZeroAmount();
        if (seller == address(0) || asset == address(0)) revert ZeroAddress();
        address vault = _ensureVault(asset);
        uint64 maturity = _soldMaturity(seller, mGhostAmount);

        // L'acheteur paie le VRAI actif, bloqué au coffre ; le vendeur reçoit le Ghost de paiement.
        IERC20(asset).safeTransferFrom(msg.sender, vault, assetAmount);
        AssetVault(vault).lockAndIssue(seller, assetAmount, maturity);
        // Le M' passe du vendeur à l'acheteur, étiqueté PROTEGE à son échéance.
        IERC20(mGhost).safeTransferFrom(seller, msg.sender, mGhostAmount);
        _mark(msg.sender, maturity, TrancheStatus.PROTEGE);
        emit Settled(seller, msg.sender, mGhostAmount, maturity, TrancheStatus.PROTEGE);
    }

    // ------------------------------------------------------------------ revente pure

    /// @inheritdoc ISettlementRouter
    function sellPure(address seller, uint256 mGhostAmount, address paymentGhost, uint256 paymentAmount)
        external
        nonReentrant
    {
        if (mGhostAmount == 0) revert ZeroAmount();
        if (seller == address(0)) revert ZeroAddress();
        uint64 maturity = _soldMaturity(seller, mGhostAmount);
        // Paiement éventuel en Ghost de paiement EXISTANT (jamais du vrai actif frais).
        if (paymentAmount != 0) {
            if (paymentGhost == address(0)) revert ZeroAddress();
            IERC20(paymentGhost).safeTransferFrom(msg.sender, seller, paymentAmount);
        }
        IERC20(mGhost).safeTransferFrom(seller, msg.sender, mGhostAmount);
        _mark(msg.sender, maturity, TrancheStatus.PUR);
        emit Settled(seller, msg.sender, mGhostAmount, maturity, TrancheStatus.PUR);
    }

    // ------------------------------------------------------------------ interne

    function _ensureVault(address asset) internal returns (address vault) {
        vault = _vaultOf[asset];
        if (vault == address(0)) {
            vault = address(new AssetVault(asset, address(this), IGuardianSet(mGhost).guardians()));
            _vaultOf[asset] = vault;
            emit VaultCreated(asset, vault);
        }
    }

    /// @dev Échéance du M' vendu : la plus tardive des tranches qui partent (règlement virtuel) ;
    ///      `now` si tout le M' vendu est déjà échu.
    function _soldMaturity(address seller, uint256 mGhostAmount) internal view returns (uint64) {
        uint64 m = IGhostRisk(mGhost).nextOutgoingMaturity(seller, mGhostAmount);
        return m == 0 ? uint64(block.timestamp) : m;
    }

    /// @dev Un don (sans paiement on-chain, hors routeur) ne passe jamais ici : il ne peut donc
    ///      jamais obtenir PROTEGE. Revendre un PROTEGE/CHEQUE via `sellPure` donne PUR (règle §10bis).
    function _mark(address buyer, uint64 maturity, TrancheStatus status) internal {
        TrancheStatus prev = _status[buyer][maturity];
        // PUR l'emporte sur PROTEGE pour une même échéance mélangée (sens sûr : on ne surclasse
        // jamais une tranche déjà pure en protégée).
        if (status == TrancheStatus.PROTEGE && prev == TrancheStatus.PUR) return;
        _status[buyer][maturity] = status;
    }
}
