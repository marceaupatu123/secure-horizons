// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import {IAssetVault} from "./interfaces/IAssetVault.sol";
import {AssetGhost} from "./AssetGhost.sol";
import {VaultGuardians} from "./VaultGuardians.sol";

/// @title AssetVault — coffre d'UN actif réel, deux sorties codées en dur (#84 §10bis). FICTIF.
/// @notice Voir `IAssetVault`. Sorties : `redeem` (a, à l'échéance) et `restitute` (b, racine de
///         Merkle 2/3). La destruction confirmée (§10bis point 4) se fait en deux gestes 2/3 :
///         `burnSeedPayment` brûle le Ghost de paiement des GRAINES (libère leur argent bloqué),
///         puis `confirmRestitutionRoot` publie la racine des feuilles de restitution. Aucune
///         sortie vers le protocole ni le multisig.
///         INVARIANT MAÎTRE (testé) : `asset.balanceOf(this) >= assetGhost.totalSupply()`.
contract AssetVault is IAssetVault, VaultGuardians, ReentrancyGuard {
    using SafeERC20 for IERC20;

    IERC20 internal immutable _asset;
    AssetGhost internal immutable _assetGhost;
    address internal immutable _router;

    /// @notice Racine de Merkle des feuilles de restitution (0 tant qu'aucune destruction confirmée).
    bytes32 public restitutionRoot;
    /// @notice Feuilles déjà payées (idempotence par nonce).
    mapping(uint256 => bool) public claimed;
    /// @notice Total restitué (sortie b), pour l'invariant de conservation.
    uint256 public totalRestituted;
    /// @notice Total converti (sortie a), pour l'invariant de conservation.
    uint256 public totalRedeemed;
    /// @notice Total d'actif bloqué entré (par `lockAndIssue`), pour l'invariant de conservation.
    uint256 public totalLockedIn;

    constructor(address asset_, address router_, address[3] memory guardians_) VaultGuardians(guardians_) {
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
        totalLockedIn += amount;
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
        totalRedeemed += amount;
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
        // La restitution ne peut puiser que dans l'argent LIBÉRÉ par les burns de Ghost de
        // paiement des graines (`locked - offre restante`). Puiser au-delà laisserait du Ghost de
        // paiement honnête (d'une autre vente) sans adossement : l'invariant maître
        // `locked >= assetGhost.totalSupply()` tient alors quoi que publie le multisig.
        uint256 available = locked() - _assetGhost.totalSupply();
        if (amount > available) revert ExceedsLocked(amount, available);
        claimed[nonce] = true;
        totalRestituted += amount;
        _asset.safeTransfer(to, amount);
        emit Restituted(to, amount, nonce);
    }

    // ------------------------------------------------------------------ destruction confirmée (2/3)

    /// @notice Geste 2/3 (1) de la destruction (§10bis point 4.1) : brûle `amount` de Ghost de
    ///         paiement d'une GRAINE `seed`, ce qui libère son argent bloqué pour la restitution.
    ///         Le `nonce` distingue deux brûlages identiques. Aucun actif ne sort ici.
    function burnSeedPayment(address seed, uint256 amount, uint256 nonce) external onlyGuardian {
        if (amount == 0) revert ZeroAmount();
        bytes32 action = keccak256(abi.encode("BURN_SEED", seed, amount, nonce));
        if (_vote(action)) {
            _assetGhost.burnAny(seed, amount);
        }
    }

    /// @notice Geste 2/3 (2) : publie la racine de Merkle des feuilles de restitution (§10bis
    ///         point 4.2-4.3). Les feuilles sont calculées HORS CHAÎNE (piste b de #85) et
    ///         contestables. Remplace la racine courante au quorum.
    function confirmRestitutionRoot(bytes32 root) external onlyGuardian {
        bytes32 action = keccak256(abi.encode("RESTITUTION_ROOT", root));
        if (_vote(action)) {
            restitutionRoot = root;
        }
    }
}
