// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {GuardianPausable} from "./GuardianPausable.sol";
import {StableToken} from "./StableToken.sol";

/// @title ProtectedMinter — volet 1 : « une clé de service volée ne doit presque rien valoir ».
/// @notice La clé `SERVICE_ROLE` n'autorise que « traiter la demande n°X » : `completeSwap(requestId)`
///         n'a NI montant NI destinataire. Le contrat applique on-chain :
///         - I1 minted = deposit × rate (conversion 6 -> 18 décimales, arrondi vers le bas, ε = 0) ;
///         - I2 la demande existe, est en attente, est traitée exactement une fois ;
///         - I3 le destinataire du mint X est le déposant de X ;
///         - I4 seul `completeSwap` mint (le `StableToken` n'accepte que ce contrat comme minter).
///         Le taux est figé (snapshot) à la création de la demande. Aucun plafond fixe par opération.
///         Pause globale par un multisig simulé de 3 guardians (3/3).
contract ProtectedMinter is AccessControl, GuardianPausable {
    using SafeERC20 for IERC20;

    bytes32 public constant SERVICE_ROLE = keccak256("SERVICE_ROLE");
    bytes32 public constant RATE_ADMIN_ROLE = keccak256("RATE_ADMIN_ROLE");
    /// @dev 1e18 = 1 stable (18 déc.) pour 1 unité entière de collatéral (6 déc.).
    uint256 public constant RATE_PRECISION = 1e18;
    /// @dev 10**(18 - 6).
    uint256 public constant DECIMALS_SCALE = 1e12;
    uint8 public constant COLLATERAL_DECIMALS = 6;

    enum RequestStatus {
        None,
        Pending,
        Completed
    }

    struct SwapRequest {
        address depositor;
        uint256 depositAmount;
        uint256 rate;
        RequestStatus status;
    }

    IERC20 public immutable collateral;
    StableToken public immutable stable;
    uint256 public rate;
    uint256 public nextRequestId;
    uint256 public totalDeposited;
    uint256 public totalMinted;

    mapping(uint256 => SwapRequest) private _requests;

    event SwapRequested(uint256 indexed requestId, address indexed depositor, uint256 depositAmount, uint256 rate);
    event SwapCompleted(
        uint256 indexed requestId,
        address indexed depositor,
        address indexed recipient,
        uint256 depositAmount,
        uint256 mintedAmount,
        uint256 rate
    );
    event RateChanged(uint256 oldRate, uint256 newRate, address indexed changedBy);

    error ZeroAmount();
    error ZeroAddress();
    error SameAccount();
    error InvalidRate();
    error UnsupportedCollateralDecimals(uint8 decimals);
    error RequestNotFound(uint256 requestId);
    error RequestNotPending(uint256 requestId);

    constructor(
        IERC20 collateral_,
        address admin,
        address service,
        uint256 initialRate,
        address[3] memory guardians_
    ) GuardianPausable(guardians_) {
        if (address(collateral_) == address(0) || admin == address(0) || service == address(0)) {
            revert ZeroAddress();
        }
        if (admin == service) revert SameAccount();
        if (initialRate == 0) revert InvalidRate();
        uint8 dec = IERC20Metadata(address(collateral_)).decimals();
        if (dec != COLLATERAL_DECIMALS) revert UnsupportedCollateralDecimals(dec);

        collateral = collateral_;
        stable = new StableToken("Protected USD (fictif)", "pUSD", address(this));

        // Rôles séparés : l'admin (taux, gestion des rôles) n'est pas la clé de service.
        // AccessControl émet RoleGranted pour chaque attribution.
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(RATE_ADMIN_ROLE, admin);
        _grantRole(SERVICE_ROLE, service);

        rate = initialRate;
        emit RateChanged(0, initialRate, msg.sender);
    }

    /// @notice Dépose `depositAmount` unités de collatéral et crée la demande (taux figé).
    function requestSwap(uint256 depositAmount) external whenNotPaused returns (uint256 requestId) {
        uint256 currentRate = rate;
        if (depositAmount == 0 || quoteMint(depositAmount, currentRate) == 0) revert ZeroAmount();

        requestId = nextRequestId++;
        _requests[requestId] = SwapRequest({
            depositor: msg.sender, depositAmount: depositAmount, rate: currentRate, status: RequestStatus.Pending
        });
        totalDeposited += depositAmount;

        collateral.safeTransferFrom(msg.sender, address(this), depositAmount);
        emit SwapRequested(requestId, msg.sender, depositAmount, currentRate);
    }

    /// @notice « Traiter la demande n°X ». PAS de montant, PAS de destinataire : tout est dérivé
    ///         de la demande enregistrée on-chain.
    function completeSwap(uint256 requestId) external onlyRole(SERVICE_ROLE) whenNotPaused {
        SwapRequest storage req = _requests[requestId];
        if (req.status == RequestStatus.None) revert RequestNotFound(requestId);
        if (req.status != RequestStatus.Pending) revert RequestNotPending(requestId);

        req.status = RequestStatus.Completed;
        address depositor = req.depositor;
        uint256 depositAmount = req.depositAmount;
        uint256 reqRate = req.rate;
        uint256 minted = quoteMint(depositAmount, reqRate);
        totalMinted += minted;

        stable.mint(depositor, minted);
        emit SwapCompleted(requestId, depositor, depositor, depositAmount, minted, reqRate);
    }

    /// @notice Change le taux appliqué aux NOUVELLES demandes. Réservé à `RATE_ADMIN_ROLE`.
    function setRate(uint256 newRate) external onlyRole(RATE_ADMIN_ROLE) {
        if (newRate == 0) revert InvalidRate();
        uint256 oldRate = rate;
        rate = newRate;
        emit RateChanged(oldRate, newRate, msg.sender);
    }

    /// @notice minted = deposit × 1e12 × rate / 1e18, arrondi vers le bas (exact si rate = 1e18).
    function quoteMint(uint256 depositAmount, uint256 rate_) public pure returns (uint256) {
        return Math.mulDiv(depositAmount * DECIMALS_SCALE, rate_, RATE_PRECISION);
    }

    function getRequest(uint256 requestId) external view returns (SwapRequest memory) {
        return _requests[requestId];
    }
}
