// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {GhostBase} from "./utils/GhostBase.sol";
import {SettlementRouter} from "../src/SettlementRouter.sol";
import {AssetVault} from "../src/AssetVault.sol";
import {AssetGhost} from "../src/AssetGhost.sol";
import {ISettlementTypes} from "../src/interfaces/ISettlementTypes.sol";

/// @notice Cas de référence §10bis bout-en-bout (#84 point 5), jambe M' (M-Ghost #8 : marquage
///         surveillant + destruction 2/3) ET jambe paiement (coffre + Ghost de paiement). Prouve
///         que le voleur ne garde rien, que le dernier porteur du M' pur est restitué à hauteur de
///         son paiement, que les intermédiaires gardent le leur, et que le protocole ne garde rien.
///         Données FICTIVES. Un transfert direct de M' est encore permis (enforcement « routeur
///         seul » différé après le merge de #123, OPEN_QUESTIONS §16).
contract ScenarioSettlementTest is GhostBase {
    SettlementRouter internal router;

    address internal thief = makeAddr("thief"); // A1 : clé volée, détient du M' frauduleux
    address internal a2 = makeAddr("a2"); // acheteur intermédiaire
    address internal a40 = makeAddr("a40"); // dernier porteur du M' pur
    address internal whale = makeAddr("whale"); // offre de fond (budget de quarantaine)
    uint64 internal constant LIFE = 3600;

    function setUp() public {
        _setUpGhost();
        router = new SettlementRouter(address(ghost));
        _mintGhost(whale, 1_000e6); // 1000 M' de fond légitime
    }

    function _approveMprime(address who, uint256 amount) internal {
        vm.prank(who);
        ghost.approve(address(router), amount);
    }

    function _fundAsset(address who, uint256 amount) internal {
        usdc.mint(who, amount);
        vm.prank(who);
        usdc.approve(address(router), amount);
    }

    function _leaf(address to, uint256 amount, uint256 nonce) internal pure returns (bytes32) {
        return keccak256(bytes.concat(keccak256(abi.encode(to, amount, nonce))));
    }

    /// @notice Cas 2 : chaîne en M' pur au même prix (10). Le voleur finit à 0 (son Ghost de
    ///         paiement est brûlé), l'intermédiaire garde son paiement, le dernier porteur est
    ///         restitué à hauteur de ce qu'il a payé, le protocole ne garde rien.
    function test_cas2_chainSamePrice_thiefZero_lastHolderWhole() public {
        uint256 M = _mintGhost(thief, 10e6); // 10 M' frauduleux, échéance T0 + W
        uint256 id = _delay(thief, M, LIFE); // marqué 100 % suspect
        assertEq(ghost.effectiveSuspectOf(thief), M);

        // A2 achète le M' du voleur contre 10 USDC (bloqués) : le voleur reçoit 10 Ghost de paiement.
        _fundAsset(a2, 10e6);
        _approveMprime(thief, M);
        vm.prank(a2);
        router.buyWithAsset(thief, M, address(usdc), 10e6);

        address vaultAddr = router.vaultOf(address(usdc));
        AssetVault vault = AssetVault(vaultAddr);
        AssetGhost pay = AssetGhost(vault.assetGhost());
        assertEq(pay.balanceOf(thief), 10e6, "voleur non paye en Ghost de paiement");
        assertEq(ghost.effectiveSuspectOf(a2), M, "soupcon non transmis a A2");

        // A2 revend le M' (devenu pur) à A40 ; A40 paie A2 10 USDC hors routeur (l'intermédiaire
        // garde son paiement).
        usdc.mint(a40, 10e6);
        vm.prank(a40);
        usdc.transfer(a2, 10e6);
        _approveMprime(a2, M);
        vm.prank(a40);
        router.sellPure(a2, M, address(0), 0);
        assertEq(ghost.balanceOf(a40), M);
        assertEq(ghost.effectiveSuspectOf(a40), M, "soupcon non transmis a A40");

        // Destruction confirmée 2/3 : le M' suspect de A40 est brûlé (jambe M', #8).
        _confirm(id);
        address[] memory targets = new address[](3);
        (targets[0], targets[1], targets[2]) = (thief, a2, a40);
        _destroy(id, targets);
        assertEq(ghost.balanceOf(a40), 0, "M' du dernier porteur non brule");

        // Jambe paiement : brûler le Ghost de paiement du voleur, restituer A40 (racine Merkle).
        vm.prank(guardian1);
        vault.burnSeedPayment(thief, 10e6, 0);
        vm.prank(guardian2);
        vault.burnSeedPayment(thief, 10e6, 0);
        assertEq(pay.balanceOf(thief), 0, "Ghost de paiement du voleur non brule");

        bytes32 root = _leaf(a40, 10e6, 0);
        vm.prank(guardian1);
        vault.confirmRestitutionRoot(root);
        vm.prank(guardian2);
        vault.confirmRestitutionRoot(root);
        bytes32[] memory proof = new bytes32[](0);
        vault.restitute(a40, 10e6, 0, proof);

        // Résultats §10bis cas 2.
        assertEq(usdc.balanceOf(thief), 0, "le voleur a garde de l'argent");
        assertEq(usdc.balanceOf(a2), 10e6, "l'intermediaire n'a pas garde son paiement");
        assertEq(usdc.balanceOf(a40), 10e6, "le dernier porteur n'est pas restitue"); // payé 10, restitué 10 -> net 0
        assertEq(vault.locked(), 0, "le coffre garde de l'actif");
        assertEq(vault.totalRedeemed() + vault.totalRestituted(), vault.totalLockedIn(), "conservation");
        assertLe(vault.totalRestituted(), 10e6, "restitution > argent bloque du voleur");
    }

    /// @notice Cas 2bis : prix qui montent (voleur vend 10, A40 achète 15). A40 récupère les 10
    ///         bloqués par le voleur et perd les 5 de marge — gagnés par l'intermédiaire. Le risque
    ///         se partage entre acheteurs/vendeurs de M' pur par les prix (§10bis cas 2bis).
    function test_cas2bis_risingPrice_lastHolderLosesMarkup() public {
        uint256 M = _mintGhost(thief, 10e6);
        uint256 id = _delay(thief, M, LIFE);

        _fundAsset(a2, 10e6);
        _approveMprime(thief, M);
        vm.prank(a2);
        router.buyWithAsset(thief, M, address(usdc), 10e6); // voleur reçoit 10 Ghost de paiement

        // A40 paie A2 15 (hors routeur) : l'intermédiaire encaisse la marge.
        usdc.mint(a40, 15e6);
        vm.prank(a40);
        usdc.transfer(a2, 15e6);
        _approveMprime(a2, M);
        vm.prank(a40);
        router.sellPure(a2, M, address(0), 0);

        _confirm(id);
        address[] memory targets = new address[](3);
        (targets[0], targets[1], targets[2]) = (thief, a2, a40);
        _destroy(id, targets);

        AssetVault vault = AssetVault(router.vaultOf(address(usdc)));
        vm.prank(guardian1);
        vault.burnSeedPayment(thief, 10e6, 0);
        vm.prank(guardian2);
        vault.burnSeedPayment(thief, 10e6, 0);
        // La racine ne peut restituer que l'argent bloqué du voleur (10), pas la marge (5).
        bytes32 root = _leaf(a40, 10e6, 0);
        vm.prank(guardian1);
        vault.confirmRestitutionRoot(root);
        vm.prank(guardian2);
        vault.confirmRestitutionRoot(root);
        bytes32[] memory proof = new bytes32[](0);
        vault.restitute(a40, 10e6, 0, proof);

        assertEq(usdc.balanceOf(thief), 0);
        assertEq(usdc.balanceOf(a2), 15e6, "l'intermediaire garde prix de vente"); // acheté via vault 10, vendu 15
        assertEq(usdc.balanceOf(a40), 10e6, "A40 recupere les 10 bloques"); // payé 15 -> perte nette 5
        assertEq(vault.locked(), 0);
        assertEq(vault.totalRestituted(), 10e6);
    }

    /// @notice Cas 3 : salaire payé en M' hors routeur (chèque). Le M' est brûlé à la destruction ;
    ///         le salarié n'a rien payé on-chain, aucune restitution on-chain, aucune perte on-chain
    ///         (recours hors chaîne contre l'employeur).
    function test_cas3_cheque_noOnChainRestitution() public {
        address worker = makeAddr("worker");
        uint256 M = _mintGhost(thief, 10e6);
        uint256 id = _delay(thief, M, LIFE);

        // Paiement direct (hors routeur) : le salarié reçoit un M' « chèque ».
        _transferGhost(thief, worker, M);
        assertEq(ghost.balanceOf(worker), M);
        assertEq(
            uint8(router.statusOf(worker, uint64(T0 + W))), uint8(ISettlementTypes.TrancheStatus.NONE),
            "un don/salaire ne doit jamais etre suivi par le routeur"
        );

        _confirm(id);
        _destroy(id, _one(worker));
        assertEq(ghost.balanceOf(worker), 0, "M' cheque non brule");
        assertEq(usdc.balanceOf(worker), 0, "le salarie a touche de l'argent on-chain");
        // Aucun coffre n'a été créé : rien n'a transité par le routeur.
        assertEq(router.vaultOf(address(usdc)), address(0));
    }
}
