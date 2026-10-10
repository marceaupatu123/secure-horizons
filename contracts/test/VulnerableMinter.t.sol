// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {BaseTest} from "./utils/BaseTest.sol";
import {StableToken} from "../src/StableToken.sol";
import {VulnerableMinter} from "../src/VulnerableMinter.sol";

/// @notice Montre que le contrat VOLONTAIREMENT vulnérable laisse la clé de service minter
///         n'importe quel montant vers n'importe qui.
contract VulnerableMinterTest is BaseTest {
    VulnerableMinter internal minter;
    StableToken internal stable;

    // Fixtures (ordre de grandeur de l'incident Resolv cité dans docs/OPEN_ANSWERS.md §1),
    // pas des mesures.
    uint256 internal constant DEPOSIT = 200_000e6;
    uint256 internal constant INFLATED = 80_000_000e18;

    event SwapRequested(uint256 indexed requestId, address indexed depositor, uint256 depositAmount);

    function setUp() public {
        _deployUsdc();
        (minter, stable) = _deployVulnerable();
    }

    function test_requestSwap_pullsCollateralAndRecords() public {
        _fund(alice, DEPOSIT);
        _approve(alice, address(minter));

        vm.expectEmit(true, true, false, true, address(minter));
        emit SwapRequested(0, alice, DEPOSIT);
        vm.prank(alice);
        uint256 id = minter.requestSwap(DEPOSIT);

        assertEq(id, 0);
        assertEq(usdc.balanceOf(address(minter)), DEPOSIT);
        assertEq(usdc.balanceOf(alice), 0);
        VulnerableMinter.SwapRequest memory r = minter.getRequest(id);
        assertEq(r.depositor, alice);
        assertEq(r.depositAmount, DEPOSIT);
        assertEq(uint8(r.status), uint8(VulnerableMinter.RequestStatus.Pending));
    }

    function test_requestSwap_revertsOnZero() public {
        vm.prank(alice);
        vm.expectRevert(VulnerableMinter.ZeroAmount.selector);
        minter.requestSwap(0);
    }

    function test_completeSwap_onlyServiceRole() public {
        uint256 id = _requestVulnerable(minter, alice, DEPOSIT);
        bytes32 role = minter.SERVICE_ROLE();
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, alice, role));
        minter.completeSwap(id, alice, 1);
    }

    function test_completeSwap_revertsOnReplay() public {
        uint256 id = _requestVulnerable(minter, alice, DEPOSIT);
        vm.prank(service);
        minter.completeSwap(id, alice, DEPOSIT * SCALE);
        vm.prank(service);
        vm.expectRevert(abi.encodeWithSelector(VulnerableMinter.RequestNotPending.selector, id));
        minter.completeSwap(id, alice, DEPOSIT * SCALE);
    }

    /// @notice L'attaque : petit dépôt réel, mint énorme signé par la clé de service.
    function test_attack_smallDepositHugeMint() public {
        uint256 id = _requestVulnerable(minter, attacker, DEPOSIT);
        vm.prank(attacker);
        minter.completeSwap(id, attacker, INFLATED);

        uint256 minted = stable.balanceOf(attacker);
        assertEq(minted, INFLATED);
        assertGt(minted, DEPOSIT * SCALE);
        assertEq(usdc.balanceOf(address(minter)), DEPOSIT);
    }

    /// @notice La clé de service redirige le mint de la demande d'Alice vers elle-même.
    function test_attack_mintToArbitraryRecipient() public {
        uint256 id = _requestVulnerable(minter, alice, DEPOSIT);
        vm.prank(attacker);
        minter.completeSwap(id, attacker, DEPOSIT * SCALE);

        assertEq(stable.balanceOf(alice), 0);
        assertEq(stable.balanceOf(attacker), DEPOSIT * SCALE);
    }

    /// @notice Quel que soit le dépôt, le montant minté est celui choisi par la clé de service.
    function testFuzz_vulnerable_mintsAnyAmount(uint256 deposit, uint256 mintAmount) public {
        deposit = bound(deposit, 1, 1e18);
        mintAmount = bound(mintAmount, 0, type(uint128).max);
        uint256 id = _requestVulnerable(minter, attacker, deposit);
        vm.prank(attacker);
        minter.completeSwap(id, attacker, mintAmount);
        assertEq(stable.balanceOf(attacker), mintAmount);
        assertEq(stable.totalSupply(), mintAmount);
    }
}
