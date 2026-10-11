// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IGhostToken} from "./interfaces/IGhostToken.sol";

/// @title GhostedStable — le vrai token M (FICTIF, 18 décimales), adossé à un M-Ghost.
/// @notice M ne se mint que par conversion depuis le M-Ghost (`ghost`, immuable). Tout transfert
///         de M brûle le M de l'expéditeur (`Transfer(from, 0, v)`) et fait émettre du M-Ghost
///         FRAIS au destinataire (OPEN_ANSWERS §0bis : le Ghost porte tous les transferts). Le
///         destinataire ne reçoit donc jamais de M par transfert. `transfer` / `transferFrom` /
///         allowances restent standard ; si le Ghost est en pause, le transfert de M revert.
contract GhostedStable is ERC20 {
    /// @notice Le M-Ghost, seul minter (immuable).
    address public immutable ghost;

    error NotMinter(address caller);
    error ZeroAddress();

    constructor(address ghost_) ERC20("Protected USD (fictif)", "pUSD") {
        if (ghost_ == address(0)) revert ZeroAddress();
        ghost = ghost_;
    }

    /// @notice Alias de `ghost` (compatibilité avec l'API `StableToken.minter()`).
    function minter() external view returns (address) {
        return ghost;
    }

    /// @notice Mint réservé au M-Ghost (conversion Ghost -> M).
    function mint(address to, uint256 amount) external {
        if (msg.sender != ghost) revert NotMinter(msg.sender);
        _mint(to, amount);
    }

    /// @dev Transfert (from et to non nuls, v > 0) = burn du M de `from` + Ghost frais à `to`.
    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0) && value != 0) {
            super._update(from, address(0), value);
            IGhostToken(ghost).onUnderlyingTransfer(from, to, value);
        } else {
            super._update(from, to, value);
        }
    }
}
