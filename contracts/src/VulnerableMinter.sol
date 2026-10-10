// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {StableToken} from "./StableToken.sol";

/// @title VulnerableMinter — VOLONTAIREMENT VULNÉRABLE (démo uniquement, ne jamais déployer comme vrai contrat).
/// @notice Reproduit le schéma Resolv : un utilisateur dépose du collatéral (`requestSwap`), puis un
///         compte `SERVICE_ROLE` appelle `completeSwap` avec un MONTANT et un DESTINATAIRE libres.
///         Le contrat vérifie le rôle et que la demande existe / est en attente, mais ne relie pas le
///         montant minté au dépôt : une clé de service volée mint ce qu'elle veut.
contract VulnerableMinter is AccessControl {
    using SafeERC20 for IERC20;

    bytes32 public constant SERVICE_ROLE = keccak256("SERVICE_ROLE");

    enum RequestStatus {
        None,
        Pending,
        Completed
    }

    struct SwapRequest {
        address depositor;
        uint256 depositAmount;
        RequestStatus status;
    }

    IERC20 public immutable collateral;
    StableToken public immutable stable;
    uint256 public nextRequestId;

    mapping(uint256 => SwapRequest) private _requests;

    event SwapRequested(uint256 indexed requestId, address indexed depositor, uint256 depositAmount);
    event SwapCompleted(uint256 indexed requestId, address indexed recipient, uint256 mintAmount);

    error ZeroAmount();
    error ZeroAddress();
    error RequestNotPending(uint256 requestId);

    constructor(IERC20 collateral_, address admin, address service) {
        if (address(collateral_) == address(0) || admin == address(0) || service == address(0)) {
            revert ZeroAddress();
        }
        collateral = collateral_;
        stable = new StableToken("Vulnerable USD (fictif)", "vUSD", address(this));
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(SERVICE_ROLE, service);
    }

    function requestSwap(uint256 depositAmount) external returns (uint256 requestId) {
        if (depositAmount == 0) revert ZeroAmount();
        requestId = nextRequestId++;
        _requests[requestId] =
            SwapRequest({depositor: msg.sender, depositAmount: depositAmount, status: RequestStatus.Pending});
        collateral.safeTransferFrom(msg.sender, address(this), depositAmount);
        emit SwapRequested(requestId, msg.sender, depositAmount);
    }

    /// @notice LA FAILLE : `recipient` et `mintAmount` sont fournis par l'appelant et jamais
    ///         comparés au dépôt de la demande.
    function completeSwap(uint256 requestId, address recipient, uint256 mintAmount) external onlyRole(SERVICE_ROLE) {
        SwapRequest storage req = _requests[requestId];
        if (req.status != RequestStatus.Pending) revert RequestNotPending(requestId);
        req.status = RequestStatus.Completed;
        stable.mint(recipient, mintAmount);
        emit SwapCompleted(requestId, recipient, mintAmount);
    }

    function getRequest(uint256 requestId) external view returns (SwapRequest memory) {
        return _requests[requestId];
    }
}
