// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IGhostRisk} from "../../src/interfaces/IGhostRisk.sol";

/// @notice Mock du M-Ghost pour #7 (en attendant #8) : ERC-20 + vues `IGhostRisk`.
///         Le soupçon suit les fonds au prorata (`ratio × montant`, §9), une destruction 2/3
///         brûle `suspect` du solde (§9 : destruction = ratio × solde Ghost). Tout le reste est
///         réglable par les tests. Données FICTIVES.
contract MockGhostRisk is ERC20, IGhostRisk {
    mapping(address => uint256) public suspect;
    mapping(address => uint64) public extendedUntilOf;
    mapping(address => uint256) public extensionTagOf;
    mapping(address => uint256) public pendingTagOf;
    mapping(address => uint64) public destroyedAtOf;
    mapping(address => uint256) public destroyedIncidentOf;
    mapping(address => uint64) public clearedAtOf;
    bool public pausedFlag;
    uint64 public windowSecs = 600;
    uint64 public slotSecs = 60;

    constructor() ERC20("M-Ghost (mock, fictif)", "gM") {}

    // ------------------------------------------------ réglages de test
    function mint(address to, uint256 amount, uint256 suspectAmount) external {
        _mint(to, amount);
        suspect[to] += suspectAmount;
    }

    function setSuspect(address a, uint256 s) external {
        suspect[a] = s;
    }

    function setExtended(address a, uint64 until, uint256 tag) external {
        extendedUntilOf[a] = until;
        extensionTagOf[a] = tag;
    }

    function setPendingTag(address a, uint256 tag) external {
        pendingTagOf[a] = tag;
    }

    function setPaused(bool p) external {
        pausedFlag = p;
    }

    function setCleared(address a, uint64 at) external {
        clearedAtOf[a] = at;
    }

    /// @notice Destruction 2/3 simulée : brûle le soupçon de `a` sur son solde.
    function destroy(address a, uint256 incidentId) external {
        uint256 s = suspect[a];
        uint256 bal = balanceOf(a);
        uint256 burnt = s > bal ? bal : s;
        suspect[a] = 0;
        _burn(a, burnt);
        destroyedAtOf[a] = uint64(block.timestamp);
        destroyedIncidentOf[a] = incidentId;
    }

    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0) && value > 0) {
            uint256 bal = balanceOf(from);
            uint256 moved = bal == 0 ? 0 : (suspect[from] * value) / bal;
            suspect[from] -= moved;
            suspect[to] += moved;
        }
        super._update(from, to, value);
    }

    // ------------------------------------------------ IGhostRisk
    function effectiveSuspectOf(address a) external view returns (uint256) {
        return suspect[a];
    }

    function suspectComponentsOf(address a) external view returns (uint256, uint256, uint256) {
        return (0, suspect[a], pendingTagOf[a]);
    }

    function ratioOf(address a) external view returns (uint256) {
        uint256 bal = balanceOf(a);
        return bal == 0 ? 0 : (suspect[a] * 1e18) / bal;
    }

    function pendingTag(address a) external view returns (uint256) {
        return pendingTagOf[a];
    }

    function extendedUntil(address a) external view returns (uint64) {
        return extendedUntilOf[a];
    }

    function maxExtensionEnd(address) external pure returns (uint64) {
        return 0;
    }

    function extensionRunStart(address) external pure returns (uint64) {
        return 0;
    }

    function extensionTag(address a) external view returns (uint256) {
        return extensionTagOf[a];
    }

    function convertibleOf(address) external pure returns (uint256) {
        return 0;
    }

    function maturedEffectiveOf(address) external pure returns (uint256) {
        return 0;
    }

    function maturedOf(address) external pure returns (uint256) {
        return 0;
    }

    function bucketsOf(address) external pure returns (uint64[] memory m, uint256[] memory a) {
        return (m, a);
    }

    function nextOutgoingMaturity(address, uint256) external pure returns (uint64) {
        return 0;
    }

    function incidents(uint256) external pure returns (uint64, uint64, bool, uint256) {
        return (0, 0, false, 0);
    }

    function openIncidentId() external pure returns (uint256) {
        return 0;
    }

    function destroyedAt(address a) external view returns (uint64) {
        return destroyedAtOf[a];
    }

    function destroyedIncident(address a) external view returns (uint256) {
        return destroyedIncidentOf[a];
    }

    function clearedAt(address a) external view returns (uint64) {
        return clearedAtOf[a];
    }

    function reserve() external pure returns (uint256) {
        return 0;
    }

    function supplyValue() external view returns (uint256) {
        return totalSupply();
    }

    function totalIssued() external view returns (uint256) {
        return totalSupply();
    }

    function window() external view returns (uint64) {
        return windowSecs;
    }

    function slot() external view returns (uint64) {
        return slotSecs;
    }

    function maxExtensionFactor() external pure returns (uint32) {
        return 3;
    }

    function quarantineBudgetBps() external pure returns (uint16) {
        return 0;
    }

    function maxConvertRatio() external pure returns (uint256) {
        return 0;
    }

    function maxConvertSuspect() external pure returns (uint256) {
        return 0;
    }

    function convertFeeBaseBps() external pure returns (uint16) {
        return 0;
    }

    function convertFeeSlopeBps() external pure returns (uint16) {
        return 0;
    }

    function entryFeeBps() external pure returns (uint16) {
        return 0;
    }

    function restitutionClaimDelay() external pure returns (uint64) {
        return 0;
    }

    function paused() external view returns (bool) {
        return pausedFlag;
    }
}
