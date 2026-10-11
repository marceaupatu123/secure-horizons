// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import {IAssetVault} from "./interfaces/IAssetVault.sol";
import {AssetGhost} from "./AssetGhost.sol";

/// @title AssetVault — coffre d'UN actif réel, deux sorties codées en dur (#84 §10bis). FICTIF.
/// @notice Voir `IAssetVault`. Itération 2 : `lockAndIssue` (routeur) + `redeem` (sortie a). La
///         racine de restitution (sortie b) est posée par les guardians 2/3 dans une itération
///         ultérieure (OPEN_QUESTIONS §16) ; tant qu'aucune racine n'est posée, `restitute` revert,
///         ce qui est correct (aucune destruction confirmée = aucune restitution possible).
///         INVARIANT MAÎTRE (testé) : `asset.balanceOf(this) >= assetGhost.totalSupply()`.
contract AssetVault is IAssetVault, ReentrancyGuard {
    using SafeERC20 for IERC20;

    IERC20 internal immutable _asset;
    AssetGhost internal immutable _assetGhost;
    address internal immutable _router;

    /// @notice Racine de Merkle des feuilles de restitution (0 tant qu'aucune destruction confirmée).
    bytes32 public restitutionRoot;
    /// @notice Feuilles déjà payées (idempotence par nonce).
    mapping(uint256 => bool) public claimed;

    constructor(address asset_, address router_) {
        if (asset_ == address(0) || router_ == address(0)) revert ZeroAddress();
        _asset = IERC20(asset_);
        _router = router_;
        _assetGhost = new AssetGhost(asset_, address(this));
    }

    // ------------------------------------------------------------------ vues (IAssetVault)

    function asset() external view returns (address) {
        return address(_asset);
    }

    function assetGhost() external view returns (address) {
        return address(_assetGhost);
    }

    function router() external view returns (address) {
        return _router;
    }

    function locked() public view returns (uint256) {
        return _asset.balanceOf(address(this));
    }

    // ------------------------------------------------------------------ entrée (routeur)

    /// @inheritdoc IAssetVault
    function lockAndIssue(address seller, uint256 amount, uint64 maturity) external nonReentrant {
        if (msg.sender != _router) revert NotRouter(msg.sender);
        if (amount == 0) revert ZeroAmount();
        // Le routeur a déjà transféré l'actif au coffre (mesure du reçu : token à frais).
        uint256 bal = locked();
        uint256 outstanding = _assetGhost.totalSupply();
        if (bal < outstanding + amount) revert ExceedsLocked(amount, bal - outstanding);
        _assetGhost.issueTo(seller, amount, maturity);
        emit AssetLocked(seller, amount, maturity);
    }

    // ------------------------------------------------------------------ sortie (a) : redeem

    /// @inheritdoc IAssetVault
    function redeem(uint256 amount) external nonReentrant returns (uint256 assetOut) {
        if (amount == 0) revert ZeroAmount();
        uint256 matured = _assetGhost.maturedOf(msg.sender);
        if (matured < amount) revert NotMatured(0);
        _assetGhost.burnMatured(msg.sender, amount);
        assetOut = amount; // 1:1, sans oracle
        _asset.safeTransfer(msg.sender, assetOut);
        emit AssetRedeemed(msg.sender, amount, assetOut);
    }

    // ------------------------------------------------------------------ sortie (b) : restitute

    /// @inheritdoc IAssetVault
    function restitute(address to, uint256 amount, uint256 nonce, bytes32[] calldata proof)
        external
        nonReentrant
    {
        if (amount == 0) revert ZeroAmount();
        if (claimed[nonce]) revert AlreadyClaimed(nonce);
        bytes32 leaf = keccak256(bytes.concat(keccak256(abi.encode(to, amount, nonce))));
        if (restitutionRoot == bytes32(0) || !MerkleProof.verify(proof, restitutionRoot, leaf)) {
            revert InvalidProof();
        }
        if (amount > locked()) revert ExceedsLocked(amount, locked());
        claimed[nonce] = true;
        _asset.safeTransfer(to, amount);
        emit Restituted(to, amount, nonce);
    }
}
