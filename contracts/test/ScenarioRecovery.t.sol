// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {console} from "forge-std/console.sol";
import {GhostBase} from "./utils/GhostBase.sol";
import {GhostToken} from "../src/GhostToken.sol";

/// @notice Scénario de récupération (design §8.3, affirmation n°2 de la décision #37 :
///         « annulable tant que non converti, y compris après fragmentation »). Méthode : rejeu
///         d'une chaîne puis d'un fan-out depuis un compte marqué, dilution par du Ghost propre,
///         conversions « propres » tentées après W, confirmation 2/3, puis destructions par lots.
///         La part récupérée est MESURÉE et affichée (`console.log`), jamais assertée en dur
///         (`docs/CLAIMS.md`). Config à seuils > 0 (`_ghostConfigThresholds`).
contract ScenarioRecoveryTest is GhostBase {
    uint256 internal constant E = 1e18;
    uint64 internal constant LIFE = 3600; // FACTOR × W
    address internal whale = makeAddr("whale");
    address internal source = makeAddr("source");

    uint256 internal cleanConverted;

    function setUp() public {
        _setUpGhostWith(_ghostConfigThresholds());
        _mintGhost(whale, 2_000_000e6); // offre de fond : le budget 20 % couvre le marquage
    }

    /// @dev Construit la liste des détenteurs et répartit `S` suspect par chaîne + fan-out.
    ///      Retourne (détenteurs, incidentId, S semé).
    function _spread(uint8 depth, uint8 fanOut, uint256 seed)
        internal
        returns (address[] memory holders, uint256 id, uint256 S)
    {
        uint256 n = 1 + uint256(depth) + fanOut;
        holders = new address[](n);
        holders[0] = source;
        for (uint256 i = 1; i < n; i++) {
            holders[i] = address(uint160(0x20000 + i));
        }
        // Compte marqué : 150 Ghost dont 100 semés suspect (ratio 2/3).
        _mintGhost(source, 150e6);
        id = _delay(source, 100e18, LIFE);
        S = ghost.effectiveSuspectOf(source);
        assertEq(S, 100e18);

        // Chaîne : chaque maillon reçoit une part (montant dérivé de seed), le soupçon suit.
        for (uint256 i = 1; i <= depth; i++) {
            uint256 bal = ghost.balanceOf(holders[i - 1]);
            uint256 v = bal / 2 + (uint256(keccak256(abi.encode(seed, i))) % (bal / 2 + 1));
            if (v == 0) v = bal; // ne jamais transférer 0
            _transferGhost(holders[i - 1], holders[i], v);
        }
        // Fan-out depuis le dernier maillon vers les puits.
        address last = holders[depth];
        for (uint256 j = 0; j < fanOut; j++) {
            uint256 bal = ghost.balanceOf(last);
            uint256 v = bal / (fanOut - j);
            if (v != 0) _transferGhost(last, holders[1 + uint256(depth) + j], v);
        }
        // Dilution : du Ghost PROPRE chez un détenteur sur deux (baisse le ratio, pas le montant).
        for (uint256 i = 1; i < n; i += 2) {
            _mintGhost(holders[i], 20e6);
        }
    }

    /// @dev Après W (avant `expiresAt`), chaque détenteur convertit sa part convertible. Avec des
    ///      seuils > 0, un ratio au-dessus du seuil bloque TOUTE la conversion (§3.5) ; sinon seule
    ///      la part non suspecte sort. Dans les deux cas, le soupçon ne sort jamais.
    function _convertClean(address[] memory holders) internal {
        _skip(W + 2 * SLOT);
        cleanConverted = 0;
        for (uint256 i = 0; i < holders.length; i++) {
            address a = holders[i];
            uint256 c = ghost.convertibleOf(a);
            uint256 free = ghost.balanceOf(a) - ghost.effectiveSuspectOf(a);
            assertLe(c, free, "la part suspecte ne doit jamais etre convertible");
            if (c != 0) cleanConverted += _convert(a, c);
        }
    }

    function _destroyAll(uint256 id, address[] memory holders) internal {
        for (uint256 off = 0; off < holders.length; off += MAX_BATCH) {
            uint256 end = off + MAX_BATCH < holders.length ? off + MAX_BATCH : holders.length;
            address[] memory batch = new address[](end - off);
            for (uint256 i = off; i < end; i++) {
                batch[i - off] = holders[i];
            }
            _destroy(id, batch);
        }
    }

    uint256 internal constant MAX_BATCH = 64;

    /// @notice Conservation exacte : tout le soupçon, après fragmentation, est récupéré par la
    ///         destruction (rien de suspect n'a pu être converti). La part propre, elle, est bien
    ///         sortie.
    /// forge-config: default.fuzz.runs = 40
    function testFuzz_recovery_chainAndFanOut(uint8 depth, uint8 fanOut, uint256 seed) public {
        depth = uint8(bound(depth, 1, 16));
        fanOut = uint8(bound(fanOut, 1, 16));
        (address[] memory holders, uint256 id, uint256 S) = _spread(depth, fanOut, seed);
        _convertClean(holders);

        _confirm(id); // avant expiresAt : Sp -> Sc partout
        _destroyAll(id, holders);

        assertEq(ghost.totalSuspectBurned(), S, "soupcon non entierement recupere");
        for (uint256 i = 0; i < holders.length; i++) {
            assertEq(ghost.effectiveSuspectOf(holders[i]), 0, "soupcon residuel");
        }
        console.log("recovered / seeded (1e18)", ghost.totalSuspectBurned() * 1e18 / S);
        console.log("clean Ghost converted by holders", cleanConverted);
        assertLe(ghost.supplyValue(), ghost.totalIssued(), "insolvable");
    }

    /// @notice Détection partielle : un tiers des détenteurs n'est pas ciblé. La part récupérée
    ///         est affichée ; le soupçon confirmé restant chez les non-ciblés reste verrouillé.
    function test_recovery_partialDetection() public {
        (address[] memory holders, uint256 id, uint256 S) = _spread(9, 6, 0xABCD);
        _convertClean(holders);
        _confirm(id);

        // On cible deux détenteurs sur trois.
        uint256 n = holders.length;
        uint256 targetCount;
        for (uint256 i = 0; i < n; i++) {
            if (i % 3 != 2) targetCount++;
        }
        address[] memory targets = new address[](targetCount);
        uint256 k;
        for (uint256 i = 0; i < n; i++) {
            if (i % 3 != 2) targets[k++] = holders[i];
        }
        _destroy(id, targets);

        uint256 locked;
        for (uint256 i = 0; i < n; i++) {
            if (i % 3 == 2) {
                uint256 s = ghost.effectiveSuspectOf(holders[i]);
                locked += s;
                // Reste verrouillé : la part suspecte confirmée ne se convertit jamais (§3.5).
                assertLe(ghost.convertibleOf(holders[i]), ghost.balanceOf(holders[i]) - s);
            }
        }
        assertEq(ghost.totalSuspectBurned() + locked, S, "burned + verrouille != seme");
        console.log("recovered / seeded (1e18)", ghost.totalSuspectBurned() * 1e18 / S);
        console.log("confirmed suspicion still locked at untargeted holders", locked);
        assertGt(locked, 0, "la detection partielle devrait laisser du soupcon");
    }

    /// @notice Confirmation trop tardive : après `expiresAt`, l'incident ne peut plus être
    ///         confirmé (`IncidentExpired`), la part récupérée est 0 (silence = retour, §3).
    function test_recovery_confirmationTooLate() public {
        (address[] memory holders, uint256 id,) = _spread(4, 4, 0x1234);
        (, uint64 expiresAt,,) = ghost.incidents(id);
        vm.warp(expiresAt);

        vm.prank(guardian1);
        uint256 pid = ghost.proposeDestroy(id, holders);
        vm.prank(guardian2);
        vm.expectRevert(abi.encodeWithSelector(GhostToken.IncidentExpired.selector, id));
        ghost.approveAction(pid);

        assertEq(ghost.totalSuspectBurned(), 0);
        // Le soupçon en attente a expiré : tout le monde est revenu NORMAL.
        for (uint256 i = 0; i < holders.length; i++) {
            assertEq(ghost.effectiveSuspectOf(holders[i]), 0);
        }
        console.log("recovered after late confirmation (seeded units)", ghost.totalSuspectBurned());
    }
}
