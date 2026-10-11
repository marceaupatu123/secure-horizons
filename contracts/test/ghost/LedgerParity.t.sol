// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {GhostBase} from "../utils/GhostBase.sol";

/// @notice Parité avec le registre hors chaîne `data/ghost_ledger.py` (#25), design §10bis (#124).
///         Séquence courte SANS marquage ni marge (le registre n'a ni Sc/Sp séparés, ni marge, et
///         détruit au prorata au lieu des tranches les plus récentes : écarts listés au design
///         §10bis). Les valeurs attendues sont RECOPIÉES EN DUR depuis le registre, sans aucune
///         dépendance Python dans la CI Foundry. Elles se reproduisent avec (unités de 1e18,
///         t(s) = epoch + 1_200_000 + s, `LedgerParams()` par défaut : W = 10 min, créneau 1 min) :
///
///             g = GhostLedger(LedgerParams())
///             g.mint("A", 100 * E, t(0), backed=True)
///             g.mint("B", 50 * E, t(90), backed=True)
///             g.transfer("A", "B", 40 * E, t(180), from_ghost=True)
///             g.transfer("B", "C", 60 * E, t(300), from_ghost=True)
///             # A: [(600, 60)]   B: [(720, 30)]   C: [(600, 40), (720, 20)]
///             g.convert("A", t(600)) -> 60 ; g.convert("B", t(600)) -> 0 ; g.convert("C", t(600)) -> 40
///             g.convert("B", t(720)) -> 30 ; g.convert("C", t(720)) -> 20
///             g.transfer("A", "B", 25 * E, t(720), from_ghost=False)   # B: [(1320, 25)]
///             # reserve == 0, total_supply == 150
contract LedgerParityTest is GhostBase {
    uint256 internal constant E = 1e18;

    function setUp() public {
        _setUpGhost(); // T0 = 1_200_000, aligné sur le créneau ; marges et seuils à 0
    }

    function _assertBuckets(address a, uint64[] memory offs, uint256[] memory amts) internal view {
        (uint64[] memory mats, uint256[] memory vals) = ghost.bucketsOf(a);
        assertEq(mats.length, offs.length, "bucket count");
        for (uint256 i = 0; i < offs.length; i++) {
            assertEq(mats[i], T0 + offs[i], "maturity");
            assertEq(vals[i], amts[i] * E, "amount");
        }
    }

    function _b1(uint64 o, uint256 v) internal pure returns (uint64[] memory offs, uint256[] memory amts) {
        offs = new uint64[](1);
        amts = new uint256[](1);
        (offs[0], amts[0]) = (o, v);
    }

    function test_ledgerParity_simpleChain() public {
        address a = alice;
        address b = bob;
        address c = carol;

        _mintGhost(a, 100e6); // t0
        vm.warp(T0 + 90);
        _mintGhost(b, 50e6); // arrondi au créneau supérieur : échéance t0 + 720
        vm.warp(T0 + 180);
        _transferGhost(a, b, 40 * E);
        vm.warp(T0 + 300);
        _transferGhost(b, c, 60 * E); // 40 @600 puis 20 @720 (plus anciennes d'abord)

        (uint64[] memory o, uint256[] memory v) = _b1(600, 60);
        _assertBuckets(a, o, v);
        (o, v) = _b1(720, 30);
        _assertBuckets(b, o, v);
        o = new uint64[](2);
        v = new uint256[](2);
        (o[0], v[0], o[1], v[1]) = (600, 40, 720, 20);
        _assertBuckets(c, o, v);

        // t0 + 600 : A et C convertissent leur part échue, B n'a rien d'échu.
        vm.warp(T0 + 600);
        assertEq(_convert(a, ghost.convertibleOf(a)), 60 * E);
        assertEq(ghost.convertibleOf(b), 0);
        assertEq(_convert(c, ghost.convertibleOf(c)), 40 * E);

        // t0 + 720 : B et C convertissent le reste.
        vm.warp(T0 + 720);
        assertEq(ghost.convertibleOf(a), 0);
        assertEq(_convert(b, ghost.convertibleOf(b)), 30 * E);
        assertEq(_convert(c, ghost.convertibleOf(c)), 20 * E);

        assertEq(m.balanceOf(a), 60 * E);
        assertEq(m.balanceOf(b), 30 * E);
        assertEq(m.balanceOf(c), 60 * E);

        // Transfert de vrai token : Ghost FRAIS chez le destinataire (échéance t0 + 1320).
        vm.prank(a);
        m.transfer(b, 25 * E);
        (o, v) = _b1(1320, 25);
        _assertBuckets(b, o, v);
        assertEq(m.balanceOf(a), 35 * E);

        assertEq(ghost.reserve(), 0);
        assertEq(ghost.supplyValue(), 150 * E);
    }
}
