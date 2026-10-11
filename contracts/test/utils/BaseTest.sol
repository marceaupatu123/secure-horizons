// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {MockUSDC} from "../../src/MockUSDC.sol";
import {StableToken} from "../../src/StableToken.sol";
import {VulnerableMinter} from "../../src/VulnerableMinter.sol";
import {ProtectedMinter} from "../../src/ProtectedMinter.sol";
import {GhostedStable} from "../../src/GhostedStable.sol";
import {GhostConfig, GhostToken} from "../../src/GhostToken.sol";

/// @notice Base commune : acteurs fictifs (`makeAddr`, aucune clé privée) et déploiements.
abstract contract BaseTest is Test {
    uint256 internal constant INITIAL_RATE = 1e18; // 1 stable pour 1 USDC
    uint256 internal constant SCALE = 1e12; // 10**(18 - 6)

    /// @dev Fixtures Ghost (PAS des mesures) : W = 10 min, créneau 1 min (N = 10).
    uint64 internal constant W = 600;
    uint64 internal constant SLOT = 60;
    uint32 internal constant FACTOR = 6;
    uint16 internal constant BUDGET_BPS = 2_000;

    address internal admin = makeAddr("admin");
    /// @dev La clé de service « volée » : contrôlée par l'attaquant.
    address internal service = makeAddr("service");
    /// @dev Alias de `service` (même adresse), pour la lisibilité des scénarios d'attaque.
    address internal attacker = service;
    address internal alice = makeAddr("alice");
    address internal bob = makeAddr("bob");
    address internal carol = makeAddr("carol");
    address internal watcher = makeAddr("watcher");
    address internal guardian1 = makeAddr("guardian1");
    address internal guardian2 = makeAddr("guardian2");
    address internal guardian3 = makeAddr("guardian3");

    MockUSDC internal usdc;

    function _deployUsdc() internal {
        usdc = new MockUSDC();
    }

    function _fund(address who, uint256 amount) internal {
        usdc.mint(who, amount);
    }

    function _approve(address who, address spender) internal {
        vm.prank(who);
        usdc.approve(spender, type(uint256).max);
    }

    function _deployVulnerable() internal returns (VulnerableMinter vmr, StableToken token) {
        vmr = new VulnerableMinter(IERC20(address(usdc)), admin, service);
        token = vmr.stable();
    }

    /// @dev Finance `who`, approuve le minter vulnérable et crée une demande de dépôt.
    function _requestVulnerable(VulnerableMinter vmr, address who, uint256 amount) internal returns (uint256 id) {
        _fund(who, amount);
        _approve(who, address(vmr));
        vm.prank(who);
        id = vmr.requestSwap(amount);
    }

    function _guardians() internal view returns (address[3] memory g) {
        g = [guardian1, guardian2, guardian3];
    }

    /// @dev Fixture par défaut : seuils de conversion à 0, marges à 0.
    function _ghostConfig() internal pure returns (GhostConfig memory c) {
        c = GhostConfig({
            window: W,
            slot: SLOT,
            maxExtensionFactor: FACTOR,
            quarantineBudgetBps: BUDGET_BPS,
            maxConvertRatio: 0,
            maxConvertSuspect: 0,
            convertFeeBaseBps: 0,
            convertFeeSlopeBps: 0,
            entryFeeBps: 0,
            restitutionClaimDelay: 1 days
        });
    }

    /// @dev Fixture à seuils > 0 (alignés sur data/ghost_ledger.py en 18 déc.), tests de dispersion.
    function _ghostConfigThresholds() internal pure returns (GhostConfig memory c) {
        c = _ghostConfig();
        c.maxConvertRatio = 0.01e18;
        c.maxConvertSuspect = 100e18;
    }

    function _deployProtected() internal returns (ProtectedMinter pm, GhostedStable token, GhostToken ghost) {
        return _deployProtectedWith(_ghostConfig());
    }

    function _deployProtectedWith(GhostConfig memory cfg)
        internal
        returns (ProtectedMinter pm, GhostedStable token, GhostToken ghost)
    {
        pm = new ProtectedMinter(IERC20(address(usdc)), admin, service, INITIAL_RATE, _guardians(), cfg);
        token = pm.stable();
        ghost = pm.ghost();
        bytes32 role = ghost.WATCHER_ROLE();
        vm.prank(admin);
        ghost.grantRole(role, watcher);
    }

    /// @dev Les 3 guardians approuvent la pause (3/3).
    function _pauseAll(ProtectedMinter pm) internal {
        vm.prank(guardian1);
        pm.approvePause();
        vm.prank(guardian2);
        pm.approvePause();
        vm.prank(guardian3);
        pm.approvePause();
    }

    /// @dev Finance `who`, approuve le minter protégé et crée une demande de dépôt.
    function _requestProtected(ProtectedMinter pm, address who, uint256 amount) internal returns (uint256 id) {
        _fund(who, amount);
        _approve(who, address(pm));
        vm.prank(who);
        id = pm.requestSwap(amount);
    }

    /// @dev Pilote le taux via le timelock borné de #131 : `admin` propose (variation <= 5 %),
    ///      on attend `RATE_DELAY`, puis on exécute. `newRate` doit être dans la borne de pas.
    function _proposeExecuteRate(ProtectedMinter pm, uint256 newRate) internal {
        vm.prank(admin);
        pm.proposeRate(newRate);
        vm.warp(block.timestamp + pm.RATE_DELAY());
        pm.executeRate();
    }
}
