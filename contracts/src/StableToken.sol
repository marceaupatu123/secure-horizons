// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title StableToken — stablecoin FICTIF (18 décimales).
/// @notice Seul le contrat minter fixé au déploiement peut minter (invariant I4).
///         `minter` est immuable : aucun admin ne peut ajouter un second chemin de mint.
contract StableToken is ERC20 {
    address public immutable minter;

    error NotMinter(address caller);
    error ZeroAddress();

    constructor(string memory name_, string memory symbol_, address minter_) ERC20(name_, symbol_) {
        if (minter_ == address(0)) revert ZeroAddress();
        minter = minter_;
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != minter) revert NotMinter(msg.sender);
        _mint(to, amount);
    }
}
