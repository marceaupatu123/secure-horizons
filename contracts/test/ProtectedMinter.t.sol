// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {BaseTest} from "./utils/BaseTest.sol";
import {ProtectedMinter} from "../src/ProtectedMinter.sol";
import {GhostedStable} from "../src/GhostedStable.sol";
import {GhostToken} from "../src/GhostToken.sol";

/// @dev ERC20 de test à 18 décimales (collatéral refusé par le ProtectedMinter).
contract Token18 is ERC20 {
    constructor() ERC20("T18", "T18") {}
}

/// @notice Tests unitaires par invariant (I1–I5) et séparation des clés.
contract ProtectedMinterTest is BaseTest {
    ProtectedMinter internal minter;
    GhostedStable internal stable;
    GhostToken internal ghost;

    uint256 internal constant DEPOSIT = 1_000e6;

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

    function setUp() public {
        _deployUsdc();
        (minter, stable, ghost) = _deployProtected();
    }

    // ---------------------------------------------------------------- I1

    function test_I1_mintsDepositTimesRate() public {
        uint256 id = _requestProtected(minter, alice, DEPOSIT);
        vm.prank(service);
        minter.completeSwap(id);
        assertEq(ghost.balanceOf(alice), DEPOSIT * SCALE); // rate = 1e18 => 1:1

        vm.prank(admin);
        minter.setRate(0.5e18);
        uint256 id2 = _requestProtected(minter, bob, DEPOSIT);
        vm.prank(service);
        minter.completeSwap(id2);
        assertEq(ghost.balanceOf(bob), DEPOSIT * SCALE / 2);
    }

    /// @notice Le taux est figé à la création de la demande : le changer ensuite n'a pas d'effet.
    function test_I1_rateSnapshotAtRequest() public {
        uint256 id = _requestProtected(minter, alice, DEPOSIT);
        vm.prank(admin);
        minter.setRate(3e18);
        vm.prank(service);
        minter.completeSwap(id);
        assertEq(ghost.balanceOf(alice), DEPOSIT * SCALE);
        assertEq(minter.getRequest(id).rate, INITIAL_RATE);
    }

    function testFuzz_I1_mintedEqualsQuote(uint256 deposit, uint256 rate_) public {
        deposit = bound(deposit, 1, 1e18);
        rate_ = bound(rate_, 1e6, 1e24);
        vm.prank(admin);
        minter.setRate(rate_);
        uint256 expected = deposit * SCALE * rate_ / 1e18; // recalculé par le test
        vm.assume(expected > 0);
        uint256 id = _requestProtected(minter, alice, deposit);
        vm.prank(service);
        minter.completeSwap(id);
        assertEq(ghost.balanceOf(alice), expected);
        assertEq(minter.quoteMint(deposit, rate_), expected);
    }

    function test_requestSwap_revertsOnZero() public {
        vm.prank(alice);
        vm.expectRevert(ProtectedMinter.ZeroAmount.selector);
        minter.requestSwap(0);
    }

    function test_requestSwap_revertsOnZeroQuote() public {
        vm.prank(admin);
        minter.setRate(1); // 1 unité USDC × 1e12 × 1 / 1e18 = 0
        _fund(alice, 1);
        _approve(alice, address(minter));
        vm.prank(alice);
        vm.expectRevert(ProtectedMinter.ZeroAmount.selector);
        minter.requestSwap(1);
    }

    // ---------------------------------------------------------------- I2

    function test_I2_revertUnknownRequest() public {
        vm.prank(service);
        vm.expectRevert(abi.encodeWithSelector(ProtectedMinter.RequestNotFound.selector, 0));
        minter.completeSwap(0);
    }

    function test_I2_revertReplay() public {
        uint256 id = _requestProtected(minter, alice, DEPOSIT);
        vm.prank(service);
        minter.completeSwap(id);
        vm.prank(service);
        vm.expectRevert(abi.encodeWithSelector(ProtectedMinter.RequestNotPending.selector, id));
        minter.completeSwap(id);
        assertEq(ghost.balanceOf(alice), DEPOSIT * SCALE);
    }

    function test_I2_revertFutureId() public {
        _requestProtected(minter, alice, DEPOSIT);
        uint256 future = minter.nextRequestId();
        vm.prank(service);
        vm.expectRevert(abi.encodeWithSelector(ProtectedMinter.RequestNotFound.selector, future));
        minter.completeSwap(future);
    }

    // ---------------------------------------------------------------- I3

    function test_I3_mintGoesToDepositor() public {
        uint256 id = _requestProtected(minter, alice, DEPOSIT);
        vm.prank(service);
        minter.completeSwap(id);
        assertEq(ghost.balanceOf(alice), DEPOSIT * SCALE);
        assertEq(ghost.balanceOf(service), 0);
    }

    /// @notice Il n'existe pas de variante avec montant / destinataire.
    function test_I3_noRecipientOverload() public {
        uint256 id = _requestProtected(minter, alice, DEPOSIT);
        vm.prank(service);
        (bool ok,) =
            address(minter).call(abi.encodeWithSignature("completeSwap(uint256,address,uint256)", id, service, 1e30));
        assertFalse(ok);
        // Variante « destinataire seul » : n'existe pas non plus.
        vm.prank(service);
        (ok,) = address(minter).call(abi.encodeWithSignature("completeSwap(uint256,address)", id, service));
        assertFalse(ok);
        assertEq(ghost.supplyValue(), 0);
        assertEq(uint8(minter.getRequest(id).status), uint8(ProtectedMinter.RequestStatus.Pending));
    }

    // ---------------------------------------------------------------- I4

    function test_I4_onlyMinterCanMint() public {
        address[3] memory callers = [admin, service, alice];
        for (uint256 i = 0; i < callers.length; i++) {
            vm.prank(callers[i]);
            vm.expectRevert(abi.encodeWithSelector(GhostedStable.NotMinter.selector, callers[i]));
            stable.mint(callers[i], 1e18);
        }
    }

    /// @notice I4 révisé (#8) : M n'est minté que par le Ghost (conversion) ; le Ghost « mint »
    ///         n'est émis que par le minter protégé.
    function test_I4_minterIsProtectedMinter() public view {
        assertEq(stable.minter(), address(ghost));
        assertEq(ghost.minter(), address(minter));
        assertEq(ghost.underlying(), address(stable));
        assertEq(address(minter.stable()), address(stable));
        assertEq(address(minter.ghost()), address(ghost));
    }

    function test_I4_onlyMinterCanIssueGhost() public {
        address[3] memory callers = [admin, service, alice];
        for (uint256 i = 0; i < callers.length; i++) {
            vm.prank(callers[i]);
            vm.expectRevert(abi.encodeWithSelector(GhostToken.NotMinter.selector, callers[i]));
            ghost.issueFromMinter(callers[i], 1e18, 0);
        }
    }

    /// @notice Le mint produit du Ghost FRAIS au déposant : aucun M, rien de convertible avant W.
    function test_completeSwap_issuesFreshGhost() public {
        uint256 id = _requestProtected(minter, alice, DEPOSIT);
        vm.prank(service);
        minter.completeSwap(id);
        assertEq(stable.balanceOf(alice), 0);
        assertEq(ghost.balanceOf(alice), DEPOSIT * SCALE);
        assertEq(ghost.convertibleOf(alice), 0);
        assertEq(ghost.totalIssued(), minter.totalMinted());
    }

    // ---------------------------------------------------------------- I5

    function test_I5_supplyMatchesTotalMinted() public {
        uint256 a = _requestProtected(minter, alice, DEPOSIT);
        uint256 b = _requestProtected(minter, bob, 2 * DEPOSIT);
        vm.startPrank(service);
        minter.completeSwap(a);
        minter.completeSwap(b);
        vm.stopPrank();
        assertEq(ghost.supplyValue(), minter.totalMinted());
        assertEq(ghost.supplyValue(), 3 * DEPOSIT * SCALE);
        assertEq(minter.totalDeposited(), 3 * DEPOSIT);
        assertEq(usdc.balanceOf(address(minter)), 3 * DEPOSIT);
    }

    // ---------------------------------------------------------------- rôles

    function test_roles_serviceCannotSetRate() public {
        bytes32 role = minter.RATE_ADMIN_ROLE();
        vm.prank(service);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, service, role));
        minter.setRate(1000e18);
    }

    function test_roles_adminCannotComplete() public {
        uint256 id = _requestProtected(minter, alice, DEPOSIT);
        bytes32 role = minter.SERVICE_ROLE();
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, admin, role));
        minter.completeSwap(id);
    }

    function test_roles_serviceCannotGrantRoles() public {
        bytes32 adminRole = minter.DEFAULT_ADMIN_ROLE();
        bytes32 rateRole = minter.RATE_ADMIN_ROLE();
        vm.prank(service);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, service, adminRole)
        );
        minter.grantRole(rateRole, service);
    }

    function test_roles_assignment() public view {
        assertTrue(minter.hasRole(minter.DEFAULT_ADMIN_ROLE(), admin));
        assertTrue(minter.hasRole(minter.RATE_ADMIN_ROLE(), admin));
        assertTrue(minter.hasRole(minter.SERVICE_ROLE(), service));
        assertFalse(minter.hasRole(minter.RATE_ADMIN_ROLE(), service));
        assertFalse(minter.hasRole(minter.SERVICE_ROLE(), admin));
    }

    function test_constructor_rejectsSameAdminAndService() public {
        vm.expectRevert(ProtectedMinter.SameAccount.selector);
        new ProtectedMinter(IERC20(address(usdc)), admin, admin, INITIAL_RATE, _guardians(), _ghostConfig());
    }

    function test_constructor_rejectsZeroRate() public {
        vm.expectRevert(ProtectedMinter.InvalidRate.selector);
        new ProtectedMinter(IERC20(address(usdc)), admin, service, 0, _guardians(), _ghostConfig());
    }

    function test_constructor_rejectsWrongCollateralDecimals() public {
        Token18 t = new Token18();
        vm.expectRevert(abi.encodeWithSelector(ProtectedMinter.UnsupportedCollateralDecimals.selector, uint8(18)));
        new ProtectedMinter(IERC20(address(t)), admin, service, INITIAL_RATE, _guardians(), _ghostConfig());
    }

    function test_setRate_rejectsZero() public {
        vm.prank(admin);
        vm.expectRevert(ProtectedMinter.InvalidRate.selector);
        minter.setRate(0);
    }

    function test_setRate_emitsRateChanged() public {
        vm.expectEmit(true, true, true, true, address(minter));
        emit RateChanged(INITIAL_RATE, 2e18, admin);
        vm.prank(admin);
        minter.setRate(2e18);
        assertEq(minter.rate(), 2e18);
    }

    // ---------------------------------------------------------------- événements

    function test_requestSwap_emitsEvent() public {
        _fund(alice, DEPOSIT);
        _approve(alice, address(minter));
        vm.expectEmit(true, true, true, true, address(minter));
        emit SwapRequested(0, alice, DEPOSIT, INITIAL_RATE);
        vm.prank(alice);
        minter.requestSwap(DEPOSIT);
    }

    function test_completeSwap_emitsFullEvent() public {
        uint256 id = _requestProtected(minter, alice, DEPOSIT);
        vm.expectEmit(true, true, true, true, address(minter));
        emit SwapCompleted(id, alice, alice, DEPOSIT, DEPOSIT * SCALE, INITIAL_RATE);
        vm.prank(service);
        minter.completeSwap(id);
    }
}
