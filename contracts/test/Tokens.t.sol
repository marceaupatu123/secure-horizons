// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {BaseTest} from "./utils/BaseTest.sol";
import {StableToken} from "../src/StableToken.sol";

contract TokensTest is BaseTest {
    function setUp() public {
        _deployUsdc();
    }

    function test_mockUsdc_hasSixDecimals() public view {
        assertEq(usdc.decimals(), 6);
    }

    function test_stable_hasEighteenDecimals() public {
        StableToken t = new StableToken("T", "T", address(this));
        assertEq(t.decimals(), 18);
    }

    function test_stable_onlyMinterCanMint() public {
        StableToken t = new StableToken("T", "T", address(this));
        t.mint(alice, 1e18);
        assertEq(t.balanceOf(alice), 1e18);

        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(StableToken.NotMinter.selector, attacker));
        t.mint(attacker, 1e18);
    }

    function test_stable_rejectsZeroMinter() public {
        vm.expectRevert(StableToken.ZeroAddress.selector);
        new StableToken("T", "T", address(0));
    }
}
