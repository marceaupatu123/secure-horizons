// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Vm} from "forge-std/Vm.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {GhostBase} from "../utils/GhostBase.sol";
import {GhostToken} from "../../src/GhostToken.sol";
import {GuardianActions} from "../../src/GuardianActions.sol";
import {ProtectedMinter} from "../../src/ProtectedMinter.sol";

/// @notice Correspondance logs -> lecture du monitor (design §3.12) : suite EXACTE de logs, avec
///         l'adresse émettrice, pour chaque chemin. Trois adresses émettent (minter, M-Ghost, M) et
///         `Transfer(0x0, …)` ne veut pas toujours dire « mint » : ce test fige le contrat de lecture.
contract GhostEventsTest is GhostBase {
    bytes32 internal constant TRANSFER = IERC20.Transfer.selector;

    function setUp() public {
        _setUpGhost();
        _mintGhost(makeAddr("dave"), 10_000e6); // demande n°0 ; offre de fond pour le budget
    }

    /// @dev Vérifie la suite exacte (émetteur, topic0) des logs enregistrés.
    function _assertSequence(Vm.Log[] memory logs, address[] memory emitters, bytes32[] memory topics)
        internal
        pure
    {
        assertEq(logs.length, emitters.length, "log count");
        for (uint256 i = 0; i < logs.length; i++) {
            assertEq(logs[i].emitter, emitters[i], "emitter");
            assertEq(logs[i].topics[0], topics[i], "topic0");
        }
    }

    function _seq3(address e0, bytes32 t0, address e1, bytes32 t1, address e2, bytes32 t2)
        internal
        pure
        returns (address[] memory es, bytes32[] memory ts)
    {
        es = new address[](3);
        ts = new bytes32[](3);
        (es[0], es[1], es[2]) = (e0, e1, e2);
        (ts[0], ts[1], ts[2]) = (t0, t1, t2);
    }

    /// @notice Mint : Transfer(0, déposant) + GhostIssued(MINT, requestId) côté Ghost, puis
    ///         SwapCompleted côté minter ; `GhostIssued.requestId == SwapCompleted.requestId`,
    ///         id 0 compris (setUp).
    function test_events_mint() public {
        uint256 id = _requestProtected(pm, alice, 100e6);
        assertEq(id, 1);
        vm.recordLogs();
        vm.prank(service);
        pm.completeSwap(id);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        (address[] memory es, bytes32[] memory ts) = _seq3(
            address(ghost),
            TRANSFER,
            address(ghost),
            GhostToken.GhostIssued.selector,
            address(pm),
            ProtectedMinter.SwapCompleted.selector
        );
        _assertSequence(logs, es, ts);

        assertEq(logs[0].topics[1], bytes32(0), "mint Transfer not from 0x0");
        assertEq(logs[1].topics[1], bytes32(uint256(uint160(alice))));
        assertEq(logs[1].topics[2], bytes32(uint256(uint160(address(pm)))), "source != minter");
        assertEq(logs[1].topics[3], logs[2].topics[1], "requestId differs from SwapCompleted");
        (uint256 amount, uint256 ratio, uint64 maturity, uint8 kind) =
            abi.decode(logs[1].data, (uint256, uint256, uint64, uint8));
        assertEq(amount, 100e18);
        assertEq(ratio, 0);
        assertEq(maturity, _maturityAt(block.timestamp));
        assertEq(kind, uint8(GhostToken.IssueKind.MINT));
    }

    /// @notice L'id de demande 0 est porté tel quel (aucune ambiguïté sur la chaîne).
    function test_events_mintRequestIdZero() public {
        _setUpGhost();
        uint256 id = _requestProtected(pm, alice, 1e6);
        assertEq(id, 0);
        vm.recordLogs();
        vm.prank(service);
        pm.completeSwap(id);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        assertEq(logs[1].topics[0], GhostToken.GhostIssued.selector);
        assertEq(logs[1].topics[3], bytes32(0));
        assertEq(logs[2].topics[1], bytes32(0));
    }

    /// @notice Transfert de M : Transfer(from, 0) côté M, puis Ghost frais (TRANSFER_M, source).
    function test_events_transferM() public {
        _mintMatured(alice, 100e6);
        _convert(alice, 100e18);
        vm.recordLogs();
        vm.prank(alice);
        m.transfer(bob, 40e18);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        (address[] memory es, bytes32[] memory ts) = _seq3(
            address(m), TRANSFER, address(ghost), TRANSFER, address(ghost), GhostToken.GhostIssued.selector
        );
        _assertSequence(logs, es, ts);
        assertEq(logs[0].topics[2], bytes32(0), "M transfer not burned");
        assertEq(logs[2].topics[1], bytes32(uint256(uint160(bob))));
        assertEq(logs[2].topics[2], bytes32(uint256(uint160(alice))), "source != M sender");
        assertEq(logs[2].topics[3], bytes32(0));
        (,,, uint8 kind) = abi.decode(logs[2].data, (uint256, uint256, uint64, uint8));
        assertEq(kind, uint8(GhostToken.IssueKind.TRANSFER_M));
    }

    /// @notice Transfert de Ghost : Transfer + GhostTransferred (soupçon déplacé, échéance).
    function test_events_transferGhost() public {
        _mintGhost(alice, 100e6);
        _delay(alice, 10e18, W);
        vm.recordLogs();
        _transferGhost(alice, bob, 50e18);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        assertEq(logs.length, 2);
        assertEq(logs[0].emitter, address(ghost));
        assertEq(logs[0].topics[0], TRANSFER);
        assertEq(logs[1].emitter, address(ghost));
        assertEq(logs[1].topics[0], GhostToken.GhostTransferred.selector);
        (uint256 amount, uint256 incomingRatio, uint256 suspectMoved, uint64 latest) =
            abi.decode(logs[1].data, (uint256, uint256, uint256, uint64));
        assertEq(amount, 50e18);
        assertEq(suspectMoved, 5e18);
        assertEq(incomingRatio, 0.1e18);
        assertEq(latest, _maturityAt(T0));
    }

    /// @notice Conversion : burn de Ghost, Transfer(0, a) côté M (jamais un mint), GhostConverted.
    function test_events_convert() public {
        _mintMatured(alice, 100e6);
        vm.recordLogs();
        _convert(alice, 60e18);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        (address[] memory es, bytes32[] memory ts) = _seq3(
            address(ghost), TRANSFER, address(m), TRANSFER, address(ghost), GhostToken.GhostConverted.selector
        );
        _assertSequence(logs, es, ts);
        assertEq(logs[0].topics[2], bytes32(0));
        assertEq(logs[1].topics[1], bytes32(0));
    }

    /// @notice Destruction 2/3 : approbation, confirmation, burn, GhostDestroyed, exécution.
    function test_events_destroy() public {
        _mintGhost(alice, 100e6);
        uint256 id = _delay(alice, 10e18, W);
        vm.prank(guardian1);
        uint256 pid = ghost.proposeDestroy(id, _one(alice));
        vm.recordLogs();
        vm.prank(guardian2);
        ghost.approveAction(pid);
        Vm.Log[] memory logs = vm.getRecordedLogs();

        address[] memory es = new address[](5);
        bytes32[] memory ts = new bytes32[](5);
        for (uint256 i = 0; i < 5; i++) {
            es[i] = address(ghost);
        }
        ts[0] = GuardianActions.ActionApproved.selector;
        ts[1] = GhostToken.IncidentConfirmed.selector;
        ts[2] = TRANSFER;
        ts[3] = GhostToken.GhostDestroyed.selector;
        ts[4] = GuardianActions.ActionExecuted.selector;
        _assertSequence(logs, es, ts);
        assertEq(logs[3].topics[3], bytes32(pid), "decision id != proposal id");
        (uint256 burned, uint256 ratio, uint256 suspect) = abi.decode(logs[3].data, (uint256, uint256, uint256));
        assertEq(burned, 10e18);
        assertEq(ratio, 0.1e18);
        assertEq(suspect, 10e18);
    }

    /// @notice Restitution 2/3 : Ghost frais (RESTITUTION, source = le Ghost) + Restituted.
    function test_events_restitution() public {
        _mintGhost(alice, 100e6);
        uint256 id = _delay(alice, 10e18, W);
        _destroy(id, _one(alice));
        vm.prank(guardian1);
        uint256 pid = ghost.proposeRestitution(carol, 10e18);
        vm.recordLogs();
        vm.prank(guardian2);
        ghost.approveAction(pid);
        Vm.Log[] memory logs = vm.getRecordedLogs();

        address[] memory es = new address[](5);
        bytes32[] memory ts = new bytes32[](5);
        for (uint256 i = 0; i < 5; i++) {
            es[i] = address(ghost);
        }
        ts[0] = GuardianActions.ActionApproved.selector;
        ts[1] = TRANSFER;
        ts[2] = GhostToken.GhostIssued.selector;
        ts[3] = GhostToken.Restituted.selector;
        ts[4] = GuardianActions.ActionExecuted.selector;
        _assertSequence(logs, es, ts);
        assertEq(logs[2].topics[2], bytes32(uint256(uint160(address(ghost)))));
        (,,, uint8 kind) = abi.decode(logs[2].data, (uint256, uint256, uint64, uint8));
        assertEq(kind, uint8(GhostToken.IssueKind.RESTITUTION));
    }
}
