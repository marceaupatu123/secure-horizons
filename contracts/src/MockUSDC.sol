// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title MockUSDC — collatéral FICTIF (6 décimales) pour les tests et la démo.
/// @notice `mint` est volontairement ouvert : c'est un faucet de test, sans aucune valeur.
contract MockUSDC is ERC20 {
    constructor() ERC20("Mock USD Coin (fictif)", "mUSDC") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// @notice Faucet de test ouvert à tous (données fictives uniquement).
    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
