// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";

/// @title AssetGhost — Ghost de paiement d'UN actif réel (le « USDC-Ghost »), #84 §10bis point 2.
/// @notice Émis 1:1 par le coffre (`vault`) quand un acheteur bloque de l'actif pour acheter du M'.
///         Porte l'échéance du M' vendu (passée explicitement, PAS `now + W`) : il n'est
///         convertible contre l'actif bloqué qu'à cette échéance (sortie (a) du coffre). Circule
///         librement entre-temps ; à l'envoi, les tranches les plus anciennes partent d'abord et
///         GARDENT leur échéance. Mêmes décimales que l'actif (1:1, sans oracle). FICTIF.
///
///         Itération 2 (#84) : échéances + circulation + conversion à l'échéance. La propagation
///         du RATIO de soupçon et le statut « pur » du Ghost de paiement revendu avant échéance
///         (§10bis point 2) sont une itération ultérieure, portée par le routeur (OPEN_QUESTIONS
///         §16). Invariant de stockage testé : `balanceOf(a) == Σ buckets(a)`.
contract AssetGhost is ERC20 {
    struct Bucket {
        uint64 maturity;
        uint256 amount;
    }

    /// @notice Le coffre, seul émetteur / brûleur (immuable).
    address public immutable vault;
    uint8 private immutable _decimals;

    /// @dev Tranches par adresse, triées par échéance croissante (fusion si même échéance).
    mapping(address => Bucket[]) private _buckets;

    error NotVault(address caller);
    error BucketOverflow();

    constructor(address asset_, address vault_) ERC20("Asset-Ghost (fictif)", "gAsset") {
        vault = vault_;
        _decimals = IERC20Metadata(asset_).decimals();
    }

    function decimals() public view override returns (uint8) {
        return _decimals;
    }

    modifier onlyVault() {
        if (msg.sender != vault) revert NotVault(msg.sender);
        _;
    }

    // ------------------------------------------------------------------ émission / destruction

    /// @notice Émet `amount` de Ghost de paiement à `to`, d'échéance `maturity`. Coffre seul.
    function issueTo(address to, uint256 amount, uint64 maturity) external onlyVault {
        _mint(to, amount); // le hook de mint ne touche pas aux buckets
        _addBucket(to, maturity, amount);
    }

    /// @notice Brûle `amount` de Ghost de paiement ÉCHU de `from` (sortie (a) : conversion), ou le
    ///         Ghost de paiement d'une graine (sortie (b) : destruction). Coffre seul.
    function burnMatured(address from, uint256 amount) external onlyVault {
        _burnBuckets(from, amount, true);
        _burn(from, amount);
    }

    /// @notice Brûle `amount` quel que soit l'état d'échéance (destruction d'une graine, §10bis
    ///         point 4). Coffre seul.
    function burnAny(address from, uint256 amount) external onlyVault {
        _burnBuckets(from, amount, false);
        _burn(from, amount);
    }

    // ------------------------------------------------------------------ vues

    /// @notice Ghost de paiement échu (convertible contre l'actif) de `a`.
    function maturedOf(address a) public view returns (uint256 m) {
        Bucket[] storage b = _buckets[a];
        for (uint256 i = 0; i < b.length; i++) {
            if (b[i].maturity <= block.timestamp) m += b[i].amount;
        }
    }

    function bucketsOf(address a) external view returns (uint64[] memory mats, uint256[] memory amts) {
        Bucket[] storage b = _buckets[a];
        mats = new uint64[](b.length);
        amts = new uint256[](b.length);
        for (uint256 i = 0; i < b.length; i++) {
            (mats[i], amts[i]) = (b[i].maturity, b[i].amount);
        }
    }

    // ------------------------------------------------------------------ circulation

    /// @dev Transfert : tranches les plus anciennes d'abord, gardant leur échéance. Mint/burn sont
    ///      gérés par `issueTo` / `burnMatured` / `burnAny` (le hook ne touche alors pas aux buckets).
    function _update(address from, address to, uint256 value) internal override {
        super._update(from, to, value);
        if (from != address(0) && to != address(0) && value != 0 && from != to) {
            _moveBuckets(from, to, value);
        }
    }

    // ------------------------------------------------------------------ interne : buckets

    function _addBucket(address a, uint64 maturity, uint256 amount) private {
        if (amount == 0) return;
        Bucket[] storage b = _buckets[a];
        uint256 i = b.length;
        while (i > 0 && b[i - 1].maturity > maturity) i--;
        if (i > 0 && b[i - 1].maturity == maturity) {
            b[i - 1].amount += amount;
            return;
        }
        b.push(Bucket(0, 0));
        for (uint256 j = b.length - 1; j > i; j--) {
            b[j] = b[j - 1];
        }
        b[i] = Bucket(maturity, amount);
    }

    function _moveBuckets(address from, address to, uint256 value) private {
        Bucket[] storage bf = _buckets[from];
        uint256 rem = value;
        uint256 k;
        while (rem != 0 && k < bf.length) {
            uint256 take = bf[k].amount < rem ? bf[k].amount : rem;
            _addBucket(to, bf[k].maturity, take);
            bf[k].amount -= take;
            rem -= take;
            if (bf[k].amount == 0) k++;
        }
        // Compacte les tranches vidées en tête.
        if (k != 0) {
            for (uint256 i = k; i < bf.length; i++) {
                bf[i - k] = bf[i];
            }
            for (uint256 i = 0; i < k; i++) {
                bf.pop();
            }
        }
    }

    /// @dev Brûle `amount` : si `maturedOnly`, uniquement les tranches échues (les plus anciennes
    ///      d'abord) ; sinon toutes (les plus anciennes d'abord). Revert si pas assez.
    function _burnBuckets(address a, uint256 amount, bool maturedOnly) private {
        Bucket[] storage b = _buckets[a];
        uint256 rem = amount;
        uint256 i;
        while (rem != 0 && i < b.length) {
            if (maturedOnly && b[i].maturity > block.timestamp) {
                i++;
                continue;
            }
            uint256 take = b[i].amount < rem ? b[i].amount : rem;
            b[i].amount -= take;
            rem -= take;
            i++;
        }
        if (rem != 0) revert BucketOverflow(); // pas assez d'échu : l'appelant a vérifié avant
        _compact(a);
    }

    function _compact(address a) private {
        Bucket[] storage b = _buckets[a];
        uint256 w;
        for (uint256 r = 0; r < b.length; r++) {
            if (b[r].amount != 0) {
                if (w != r) b[w] = b[r];
                w++;
            }
        }
        while (b.length > w) {
            b.pop();
        }
    }
}
