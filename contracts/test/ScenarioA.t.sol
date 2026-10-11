// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {BaseTest} from "./utils/BaseTest.sol";
import {ProtectedMinter} from "../src/ProtectedMinter.sol";
import {StableToken} from "../src/StableToken.sol";
import {GhostedStable} from "../src/GhostedStable.sol";
import {GhostToken} from "../src/GhostToken.sol";
import {VulnerableMinter} from "../src/VulnerableMinter.sol";

/// @notice Scénario A : la MÊME séquence d'attaque, jouée par le même attaquant détenteur de la
///         clé `SERVICE_ROLE`, sur le contrat vulnérable puis sur le contrat protégé.
/// @dev Montants = fixtures reprenant l'ordre de grandeur Resolv (docs/OPEN_ANSWERS.md §1), pas des mesures.
contract ScenarioATest is BaseTest {
    uint256 internal constant DEPOSIT = 200_000e6;
    uint256 internal constant INFLATED = 80_000_000e18;

    VulnerableMinter internal vulnerable;
    StableToken internal vStable;
    ProtectedMinter internal protected;
    GhostedStable internal pStable;
    GhostToken internal pGhost;

    function setUp() public {
        _deployUsdc();
        (vulnerable, vStable) = _deployVulnerable();
        (protected, pStable, pGhost) = _deployProtected();
    }

    /// @dev (a) l'attaquant dépose DEPOSIT ; (b) il tente le mint gonflé INFLATED vers lui-même.
    function _attackVulnerable() internal returns (uint256 minted) {
        uint256 id = _requestVulnerable(vulnerable, attacker, DEPOSIT);
        vm.prank(attacker);
        vulnerable.completeSwap(id, attacker, INFLATED);
        minted = vStable.balanceOf(attacker);
    }

    function _attackProtected() internal returns (uint256 id, bool inflatedCallOk, uint256 minted) {
        id = _requestProtected(protected, attacker, DEPOSIT);
        vm.prank(attacker);
        (inflatedCallOk,) = address(protected)
            .call(abi.encodeWithSignature("completeSwap(uint256,address,uint256)", id, attacker, INFLATED));
        // Seul appel possible : « traiter la demande n°id ».
        vm.prank(attacker);
        protected.completeSwap(id);
        minted = pGhost.balanceOf(attacker);
    }

    function test_scenarioA_vulnerable_inflatedMintSucceeds() public {
        uint256 minted = _attackVulnerable();
        assertEq(minted, INFLATED);
        assertGt(minted, DEPOSIT * SCALE);
    }

    function test_scenarioA_protected_onlyOneToOne() public {
        (uint256 id, bool inflatedCallOk, uint256 minted) = _attackProtected();
        assertFalse(inflatedCallOk);
        assertEq(minted, DEPOSIT * SCALE); // 1:1 à rate = 1e18
        assertEq(pGhost.supplyValue(), DEPOSIT * SCALE);

        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(ProtectedMinter.RequestNotPending.selector, id));
        protected.completeSwap(id);
    }

    function test_scenarioA_protected_victimRequestCannotBeRedirected() public {
        uint256 id = _requestProtected(protected, alice, DEPOSIT);
        vm.prank(attacker);
        protected.completeSwap(id);
        assertEq(pGhost.balanceOf(alice), DEPOSIT * SCALE);
        assertEq(pGhost.balanceOf(attacker), 0);
    }

    function test_scenarioA_sideBySide() public {
        uint256 vMinted = _attackVulnerable();
        (,, uint256 pMinted) = _attackProtected();
        emit log_named_uint("deposit (USDC units, 6 dec)", DEPOSIT);
        emit log_named_uint("VulnerableMinter minted (18 dec)", vMinted);
        emit log_named_uint("ProtectedMinter minted (18 dec)", pMinted);
        assertEq(vMinted, INFLATED);
        assertEq(pMinted, DEPOSIT * SCALE);
    }
}
