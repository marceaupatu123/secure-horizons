// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {SafeCast} from "@openzeppelin/contracts/utils/math/SafeCast.sol";

/// @title MaturityBuckets — tranches d'échéance du M-Ghost par adresse (OPEN_ANSWERS §0bis-b).
/// @notice Chaque adresse détient :
///         - `matured` : Ghost dont l'échéance est passée (agrégé, convertible côté temps) ;
///         - un ANNEAU de `ring = N + 1` tranches (N = window / slot), une par créneau d'échéance
///           à venir. Index d'une échéance `m` : `(m / slot) % ring`.
///         Une valeur entrante à `t` reçoit l'échéance `ceil((t + W) / slot) * slot` (arrondi au
///         créneau SUPÉRIEUR, le sens sûr : `m >= t + W`). Une valeur transférée GARDE son
///         échéance : la circulation ne remet jamais le compteur à zéro.
///
///         Pourquoi N + 1 entrées suffisent : à l'instant T, toute échéance non échue vérifie
///         `T < m <= ceil((T + W) / slot) * slot`. Cet intervalle contient au plus N + 1 multiples
///         de `slot`, donc deux tranches non échues ne partagent jamais un index (design §3.2).
///
///         Invariant de stockage (testé) : `balanceOf(a) == matured + Σ slots[i].amount`.
///         Coût de chaque opération borné par `ring` (<= 256), indépendant de l'historique.
library MaturityBuckets {
    /// @dev Une tranche tient dans un seul slot de stockage (64 + 192 bits).
    struct Bucket {
        uint64 maturity;
        uint192 amount;
    }

    struct Account {
        uint256 matured;
        /// @dev bit i = 1 ssi slots[i].amount > 0.
        uint256 mask;
        /// @dev Seuls les `ring` premiers indices servent (ring <= 256).
        Bucket[256] slots;
    }

    /// @dev Une tranche non échue d'index attendu porte une autre échéance : impossible si
    ///      l'anneau est correctement dimensionné (garde-fou, jamais silencieux).
    error BucketCollision(uint256 index, uint64 expected, uint64 found);
    /// @dev Demande supérieure au solde tranché (garde-fou ; l'appelant vérifie le solde avant).
    error BucketUnderflow(uint256 missing);

    // ------------------------------------------------------------------ écriture

    /// @notice Verse dans `matured` toutes les tranches échues (`maturity <= now`).
    function settle(Account storage a, uint256 ring) internal {
        uint256 mask = a.mask;
        if (mask == 0) return;
        uint256 newMask = mask;
        uint256 add;
        for (uint256 i = 0; i < ring; i++) {
            if (mask & (1 << i) == 0) continue;
            Bucket storage b = a.slots[i];
            if (b.maturity <= block.timestamp) {
                add += b.amount;
                b.amount = 0;
                b.maturity = 0;
                newMask &= ~(1 << i);
            }
        }
        if (add != 0) a.matured += add;
        if (newMask != mask) a.mask = newMask;
    }

    /// @notice Émission fraîche de `v` : échéance `ceil((now + W) / slot) * slot`.
    /// @dev L'appelant doit avoir appelé `settle` ; `v == 0` ne crée pas de tranche.
    function issue(Account storage a, uint256 v, uint64 window, uint64 slot, uint256 ring)
        internal
        returns (uint64 m)
    {
        settle(a, ring);
        m = freshMaturity(window, slot);
        if (v == 0) return m;
        _add(a, m, v, slot, ring);
    }

    /// @notice Déplace `v` de `from` vers `to` : d'abord l'agrégé échu (le plus ancien), puis les
    ///         tranches non échues par échéance CROISSANTE, chacune gardant son échéance.
    /// @dev Les deux comptes doivent être réglés (`settle`). Retourne l'échéance la plus tardive
    ///      déplacée (0 si tout venait de la part échue).
    function move(Account storage from, Account storage to, uint256 v, uint64 slot, uint256 ring)
        internal
        returns (uint64 latest)
    {
        uint256 rem = _moveMatured(from, to, v);
        if (rem == 0) return 0;
        uint256 base = block.timestamp / slot;
        for (uint256 k = 1; k <= ring && rem != 0; k++) {
            uint256 idx = (base + k) % ring;
            if (from.mask & (1 << idx) == 0) continue;
            uint64 m = uint64((base + k) * slot);
            uint256 t = _takeBucket(from, idx, m, rem);
            _add(to, m, t, slot, ring);
            rem -= t;
            latest = m;
        }
        if (rem != 0) revert BucketUnderflow(rem);
    }

    /// @notice Brûle `amount` en vidant d'abord les tranches les PLUS RÉCENTES, puis `matured`
    ///         (préserve la part convertible du porteur de bonne foi, design §9-8).
    /// @dev Le compte doit être réglé.
    function burnNewestFirst(Account storage a, uint256 amount, uint64 slot, uint256 ring) internal {
        uint256 rem = amount;
        uint256 base = block.timestamp / slot;
        uint256 mask = a.mask;
        for (uint256 k = ring; k >= 1 && rem != 0; k--) {
            uint256 idx = (base + k) % ring;
            if (mask & (1 << idx) == 0) continue;
            Bucket storage b = a.slots[idx];
            uint256 amt = b.amount;
            uint256 t = amt < rem ? amt : rem;
            amt -= t;
            b.amount = uint192(amt);
            if (amt == 0) {
                b.maturity = 0;
                mask &= ~(1 << idx);
            }
            rem -= t;
        }
        a.mask = mask;
        if (rem != 0) {
            uint256 mat = a.matured;
            if (mat < rem) revert BucketUnderflow(rem - mat);
            a.matured = mat - rem;
        }
    }

    // ------------------------------------------------------------------ lecture

    /// @notice Échéance d'une valeur fraîche émise maintenant.
    function freshMaturity(uint64 window, uint64 slot) internal view returns (uint64) {
        return uint64(Math.ceilDiv(block.timestamp + window, slot) * slot);
    }

    /// @notice Part temporellement échue : `matured` + tranches échues non encore réglées.
    function maturedEffective(Account storage a, uint256 ring) internal view returns (uint256 eff) {
        eff = a.matured;
        uint256 mask = a.mask;
        if (mask == 0) return eff;
        for (uint256 i = 0; i < ring; i++) {
            if (mask & (1 << i) == 0) continue;
            Bucket storage b = a.slots[i];
            if (b.maturity <= block.timestamp) eff += b.amount;
        }
    }

    /// @notice Échéance la plus tardive parmi les tranches qui partiraient pour un envoi de `v`,
    ///         avec règlement VIRTUEL (les tranches échues comptent dans la part échue) ; 0 si
    ///         tout vient de la part échue.
    function nextOutgoing(Account storage a, uint256 v, uint64 slot, uint256 ring)
        internal
        view
        returns (uint64 latest)
    {
        uint256 eff = maturedEffective(a, ring);
        if (v <= eff) return 0;
        uint256 rem = v - eff;
        uint256 base = block.timestamp / slot;
        uint256 mask = a.mask;
        for (uint256 k = 1; k <= ring && rem != 0; k++) {
            uint256 idx = (base + k) % ring;
            if (mask & (1 << idx) == 0) continue;
            Bucket storage b = a.slots[idx];
            if (b.maturity <= block.timestamp) continue; // déjà compté dans `eff`
            uint256 amt = b.amount;
            rem -= amt < rem ? amt : rem;
            latest = b.maturity;
        }
    }

    /// @notice Tranches non vides (échues non réglées comprises), triées par échéance croissante.
    function list(Account storage a, uint256 ring)
        internal
        view
        returns (uint64[] memory maturities, uint256[] memory amounts)
    {
        uint256 mask = a.mask;
        uint256 n;
        for (uint256 i = 0; i < ring; i++) {
            if (mask & (1 << i) != 0) n++;
        }
        maturities = new uint64[](n);
        amounts = new uint256[](n);
        uint256 j;
        for (uint256 i = 0; i < ring; i++) {
            if (mask & (1 << i) == 0) continue;
            Bucket storage b = a.slots[i];
            // Tri par insertion (n <= 256, vue de test).
            uint256 p = j;
            while (p > 0 && maturities[p - 1] > b.maturity) {
                maturities[p] = maturities[p - 1];
                amounts[p] = amounts[p - 1];
                p--;
            }
            maturities[p] = b.maturity;
            amounts[p] = b.amount;
            j++;
        }
    }

    // ------------------------------------------------------------------ interne

    /// @dev Prélève d'abord l'agrégé échu de `from` vers `to` ; retourne le reste à prélever.
    function _moveMatured(Account storage from, Account storage to, uint256 v) private returns (uint256 rem) {
        uint256 fromMatured = from.matured;
        uint256 take = fromMatured < v ? fromMatured : v;
        if (take != 0) {
            from.matured = fromMatured - take;
            to.matured += take;
        }
        rem = v - take;
    }

    /// @dev Retire au plus `want` de la tranche `idx` (échéance attendue `m`) ; vide la tranche
    ///      (bit effacé) si elle tombe à 0. Retourne le montant retiré.
    function _takeBucket(Account storage a, uint256 idx, uint64 m, uint256 want) private returns (uint256 t) {
        Bucket storage b = a.slots[idx];
        if (b.maturity != m) revert BucketCollision(idx, m, b.maturity);
        uint256 amt = b.amount;
        t = amt < want ? amt : want;
        amt -= t;
        b.amount = uint192(amt); // amt <= ancienne valeur uint192
        if (amt == 0) {
            b.maturity = 0;
            a.mask &= ~(1 << idx);
        }
    }

    /// @dev Ajoute `v` à la tranche d'échéance `m` (créée si vide). `SafeCast` : un dépassement
    ///      de uint192 revert au lieu de tronquer (inatteignable avec une offre fictive).
    function _add(Account storage a, uint64 m, uint256 v, uint64 slot, uint256 ring) private {
        uint256 idx = (uint256(m) / slot) % ring;
        Bucket storage b = a.slots[idx];
        uint256 bit = 1 << idx;
        if (a.mask & bit == 0) {
            b.maturity = m;
            b.amount = SafeCast.toUint192(v);
            a.mask |= bit;
        } else {
            if (b.maturity != m) revert BucketCollision(idx, m, b.maturity);
            b.amount = SafeCast.toUint192(uint256(b.amount) + v);
        }
    }
}
