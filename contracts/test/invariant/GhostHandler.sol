// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockUSDC} from "../../src/MockUSDC.sol";
import {ProtectedMinter} from "../../src/ProtectedMinter.sol";
import {GhostedStable} from "../../src/GhostedStable.sol";
import {GhostToken} from "../../src/GhostToken.sol";

/// @notice Handler des invariants du M-Ghost (design §8.2). 5 acteurs, 1 surveillant, 3 guardians
///         honnêtes (H2), clé de service volée (volet 1), plus un « whale » de fond qui n'agit pas
///         (offre légitime pour que le budget de quarantaine laisse marquer des acteurs).
///
///         Les valeurs attendues viennent d'un MODÈLE D'OMBRE tenu par le handler (tranches
///         d'échéance, étiquettes d'incident, séries d'extension, entrées horodatées), jamais du
///         contrat testé. Règle de vivacité : chaque action est classée « doit réussir » (un revert
///         lève `ghost_unexpectedRevert`) ou « doit échouer » (un succès lève
///         `ghost_unexpectedSuccess`) ; seules les approbations de pause « peuvent échouer ».
contract GhostHandler is Test {
    struct SB {
        uint64 m;
        uint256 v;
    }

    struct Entry {
        uint64 t;
        uint256 v;
    }

    /// @dev Attentes d'une destruction pour une cible, calculées AVANT l'action.
    struct BurnExp {
        uint256 burn;
        uint256 bal;
        uint256 mBal;
        bool keepPending;
        uint256 sp;
        uint256 tag;
    }

    ProtectedMinter internal immutable pm;
    GhostToken internal immutable ghost;
    GhostedStable internal immutable m;
    MockUSDC internal immutable usdc;
    address internal immutable service;
    address internal immutable watcher;
    uint256 internal immutable W;
    uint256 internal immutable SLOT;
    uint256 internal immutable CAP;
    uint256 internal immutable BUDGET_BPS;

    address[3] internal guardians;
    address[] public actors;

    bool public ghost_unexpectedRevert;
    bool public ghost_unexpectedSuccess;
    bool public ghost_bucketViolation;
    bool public ghost_lockViolation;
    bool public ghost_destroyViolation;
    bool public ghost_watcherViolation;
    bool public ghost_restitutionOverReserve;
    string public ghost_firstFailure;
    mapping(bytes32 => uint256) public calls;

    Entry[] internal _entries;
    uint256 public ghost_sumDepositsTimesRate;
    uint256 public ghost_converted;

    mapping(address => uint256) internal _sMatured;
    mapping(address => SB[]) internal _sBuckets;
    mapping(address => uint64) public ghost_lastEnd;
    mapping(address => uint64) public ghost_runStart;
    mapping(address => uint256) public ghost_tag;

    constructor(
        ProtectedMinter pm_,
        MockUSDC usdc_,
        address service_,
        address watcher_,
        address[3] memory guardians_,
        address[] memory actors_,
        address whale,
        uint256 whaleUsdc
    ) {
        pm = pm_;
        ghost = pm_.ghost();
        m = pm_.stable();
        usdc = usdc_;
        service = service_;
        watcher = watcher_;
        guardians = guardians_;
        actors = actors_;
        W = ghost.window();
        SLOT = ghost.slot();
        CAP = uint256(ghost.maxExtensionFactor()) * W;
        BUDGET_BPS = ghost.quarantineBudgetBps();
        _mintFor(whale, whaleUsdc);
    }

    // ================================================================== actions

    function mint(uint256 actorSeed, uint256 usdcAmount) external {
        calls["mint"]++;
        _mintFor(_actor(actorSeed), _bound(usdcAmount, 1, 1_000e6));
    }

    function transferGhost(uint256 fromSeed, uint256 toSeed, uint256 amount) external {
        calls["transferGhost"]++;
        address from = _actor(fromSeed);
        address to = _actor(toSeed);
        uint256 bal = ghost.balanceOf(from);
        if (bal == 0) return;
        amount = _bound(amount, 1, bal);
        bool shouldWork = !ghost.paused();
        uint256 effTo = ghost.maturedEffectiveOf(to);
        uint256 effFrom = ghost.maturedEffectiveOf(from);
        uint256 freeTo = _free(to);
        vm.prank(from);
        try ghost.transfer(to, amount) {
            if (!shouldWork) return _unexpectedSuccess("transferGhost while paused");
            calls["transferGhost_ok"]++;
            if (from == to) return;
            _sMove(from, to, amount);
            // (b) sur la part temporelle, indépendante du soupçon.
            if (ghost.maturedEffectiveOf(to) < effTo) _fail(1, "recipient matured part decreased");
            if (ghost.maturedEffectiveOf(from) + amount < effFrom) _fail(1, "sender lost more than v");
            if (_free(to) < freeTo) _fail(1, "incoming dust locked clean value");
        } catch {
            if (shouldWork) _unexpectedRevert("transferGhost");
        }
    }

    function transferM(uint256 fromSeed, uint256 toSeed, uint256 amount) external {
        calls["transferM"]++;
        address from = _actor(fromSeed);
        address to = _actor(toSeed);
        uint256 bal = m.balanceOf(from);
        if (bal == 0) return;
        amount = _bound(amount, 1, bal);
        bool shouldWork = !ghost.paused();
        uint256 net = amount - amount * ghost.entryFeeBps() / 10_000;
        vm.prank(from);
        try m.transfer(to, amount) {
            if (!shouldWork) return _unexpectedSuccess("transferM while paused");
            calls["transferM_ok"]++;
            if (net != 0) _recordIssue(to, net);
        } catch {
            if (shouldWork) _unexpectedRevert("transferM");
        }
    }

    function convert(uint256 actorSeed, uint256 amount) external {
        calls["convert"]++;
        address a = _actor(actorSeed);
        uint256 bal = ghost.balanceOf(a);
        if (bal == 0) return;
        uint256 c = ghost.convertibleOf(a);
        if (c == 0) {
            // Rien de convertible : toute conversion doit échouer.
            vm.prank(a);
            try ghost.convert(_bound(amount, 1, bal)) {
                _unexpectedSuccess("convert with convertibleOf == 0");
            } catch {}
            return;
        }
        amount = _bound(amount, 1, c);
        bool shouldWork = !ghost.paused();
        vm.prank(a);
        try ghost.convert(amount) {
            if (!shouldWork) return _unexpectedSuccess("convert while paused");
            calls["convert_ok"]++;
            ghost_converted += amount;
            _sSettle(a);
            _sMatured[a] -= amount;
            if (ghost.balanceOf(a) < ghost.effectiveSuspectOf(a)) _fail(2, "conversion left balance < S");
        } catch {
            if (shouldWork) _unexpectedRevert("convert");
        }
    }

    /// @notice Tente de convertir 1 wei de plus que `balanceOf − S` : doit toujours échouer.
    function convertSuspectPart(uint256 actorSeed) external {
        calls["convertSuspectPart"]++;
        address a = _actor(actorSeed);
        uint256 s = ghost.effectiveSuspectOf(a);
        if (s == 0) return;
        uint256 amount = ghost.balanceOf(a) - s + 1;
        vm.prank(a);
        try ghost.convert(amount) {
            _unexpectedSuccess("suspect part converted");
        } catch {}
    }

    function warp(uint256 dt) external {
        calls["warp"]++;
        vm.warp(block.timestamp + _bound(dt, 0, 2 * W));
    }

    function watcherDelay(uint256 seed, uint256 amountSeed, uint256 duration) external {
        calls["watcherDelay"]++;
        address[] memory acc = _pick(seed, 1, 3);
        _watcherDelay(acc, _amounts(acc, amountSeed), uint64(_bound(duration, 1, CAP)), "watcherDelay");
    }

    /// @notice Ouvre un incident au bloc d'expiration du précédent et re-marque les mêmes comptes.
    function watcherChainIncident() external {
        calls["watcherChain"]++;
        uint256 id = ghost.openIncidentId();
        if (id == 0) return;
        (, uint64 exp, bool conf,) = ghost.incidents(id);
        if (conf || block.timestamp >= exp) return;
        address[] memory tagged = _taggedActors(id);
        if (tagged.length == 0) return;
        vm.warp(exp);
        _watcherDelay(tagged, new uint256[](tagged.length), uint64(W), "watcherChain");
    }

    /// @notice Actions interdites au surveillant (et à la clé de service) : toutes doivent échouer.
    function watcherForbidden(uint256 op) external {
        calls["watcherForbidden"]++;
        op = op % 10;
        if (op == 6) {
            // Rejoindre un incident vivant ignore `duration` (design §3.4) : la durée trop longue
            // n'est interdite qu'à l'ouverture d'un incident.
            uint256 open = ghost.openIncidentId();
            (, uint64 exp, bool conf,) = ghost.incidents(open);
            if (open != 0 && !conf && block.timestamp < exp) return;
        }
        address caller = op >= 7 ? service : watcher;
        bytes memory data;
        address target = address(ghost);
        if (op == 0) data = abi.encodeCall(GhostToken.proposeDestroy, (1, new address[](0)));
        else if (op == 1) data = abi.encodeCall(ghost.approveAction, (1));
        else if (op == 2) data = abi.encodeCall(ghost.approvePause, ());
        else if (op == 3) data = abi.encodeCall(GhostToken.proposeClear, (_pick(op, 1, 1)));
        else if (op == 4) data = abi.encodeCall(GhostToken.proposeRestitution, (watcher, 1));
        else if (op == 5) data = abi.encodeCall(GhostToken.proposeExtend, (_pick(op, 1, 1), new uint256[](1), 60));
        else if (op == 6) data = abi.encodeCall(GhostToken.delay, (_pick(op, 1, 1), new uint256[](1), uint64(CAP + 1)));
        else if (op == 7) data = abi.encodeCall(GhostToken.issueFromMinter, (service, 1e18, 0));
        else if (op == 8) (target, data) = (address(m), abi.encodeCall(GhostedStable.mint, (service, 1e18)));
        else data = abi.encodeCall(GhostToken.delay, (_pick(op, 1, 1), new uint256[](1), 60));
        vm.prank(caller);
        (bool success,) = target.call(data);
        if (success) _unexpectedSuccess("forbidden action succeeded");
    }

    function guardianDestroy(uint256 idSeed, uint256 targetsSeed, uint256 gSeed) external {
        calls["guardianDestroy"]++;
        uint256 open = ghost.openIncidentId();
        if (open == 0) return;
        uint256 id = _bound(idSeed, 1, open);
        (, uint64 exp, bool conf,) = ghost.incidents(id);
        bool shouldWork = conf || block.timestamp < exp;
        address[] memory targets = _pick(targetsSeed, 0, 3);
        BurnExp[] memory e = new BurnExp[](targets.length);
        for (uint256 i = 0; i < targets.length; i++) {
            e[i] = _burnExpectation(targets[i], id);
        }
        (address g1, address g2) = _twoGuardians(gSeed);
        vm.prank(g1);
        uint256 pid = ghost.proposeDestroy(id, targets);
        vm.prank(g2);
        try ghost.approveAction(pid) {
            if (!shouldWork) return _unexpectedSuccess("destroy of an expired incident");
            calls["guardianDestroy_ok"]++;
            for (uint256 i = 0; i < targets.length; i++) {
                _checkBurn(targets[i], e[i]);
            }
        } catch {
            if (shouldWork) _unexpectedRevert("guardianDestroy");
        }
    }

    function guardianExtend(uint256 seed, uint256 amountSeed, uint256 duration, uint256 gSeed) external {
        calls["guardianExtend"]++;
        address[] memory acc = _pick(seed, 1, 3);
        uint256[] memory amts = _amounts(acc, amountSeed);
        uint64 d = uint64(_bound(duration, 1, CAP));
        (bool ok, uint256 id, uint64 end) = _predictDelay(acc, d, false);
        (address g1, address g2) = _twoGuardians(gSeed);
        vm.prank(g1);
        uint256 pid = ghost.proposeExtend(acc, amts, d);
        vm.prank(g2);
        try ghost.approveAction(pid) {
            if (!ok) return _unexpectedSuccess("Extend beyond its bounds");
            calls["guardianExtend_ok"]++;
            _afterDelay(acc, id, end);
        } catch {
            if (ok) _unexpectedRevert("guardianExtend");
        }
    }

    function guardianClear(uint256 seed, uint256 gSeed) external {
        calls["guardianClear"]++;
        address[] memory acc = _pick(seed, 1, 3);
        (address g1, address g2) = _twoGuardians(gSeed);
        vm.prank(g1);
        uint256 pid = ghost.proposeClear(acc);
        vm.prank(g2);
        try ghost.approveAction(pid) {
            calls["guardianClear_ok"]++;
            for (uint256 i = 0; i < acc.length; i++) {
                (uint256 sc, uint256 sp, uint256 tag) = ghost.suspectRawOf(acc[i]);
                if (sc + sp + tag != 0) _fail(2, "Clear left suspicion");
            }
        } catch {
            _unexpectedRevert("guardianClear");
        }
    }

    function guardianRestitute(uint256 actorSeed, uint256 amount, uint256 gSeed) external {
        calls["guardianRestitute"]++;
        address to = _actor(actorSeed);
        uint256 r = ghost.reserve();
        amount = _bound(amount, 1, r + 10e18);
        bool shouldWork = !ghost.paused() && amount <= r;
        (address g1, address g2) = _twoGuardians(gSeed);
        vm.prank(g1);
        uint256 pid = ghost.proposeRestitution(to, amount);
        vm.prank(g2);
        try ghost.approveAction(pid) {
            if (amount > r) ghost_restitutionOverReserve = true;
            if (!shouldWork) return _unexpectedSuccess("restitution beyond reserve or while paused");
            calls["guardianRestitute_ok"]++;
            _recordIssue(to, amount);
        } catch {
            if (shouldWork) _unexpectedRevert("guardianRestitute");
        }
    }

    function sweep(uint256 seed) external {
        calls["sweep"]++;
        if (seed % 8 == 0) vm.warp(block.timestamp + ghost.restitutionClaimDelay());
        bool shouldWork = block.timestamp >= uint256(ghost.lastReserveInflowAt()) + ghost.restitutionClaimDelay()
            && ghost.reserve() > 0;
        try ghost.sweepToInsurance() {
            if (!shouldWork) return _unexpectedSuccess("sweep too early or empty");
            calls["sweep_ok"]++;
        } catch {
            if (shouldWork) _unexpectedRevert("sweep");
        }
    }

    /// @notice Approbation de pause / dépause 3/3 : seule action « peut échouer ».
    function guardianPause(uint256 gSeed) external {
        calls["guardianPause"]++;
        address g = guardians[gSeed % 3];
        bool isPaused = ghost.paused(); // lu AVANT vm.prank (sinon l'appel de vue consomme le prank)
        vm.prank(g);
        if (isPaused) {
            try ghost.approveUnpause() {
                calls["guardianPause_ok"]++;
            } catch {
                calls["guardianPause_ko"]++;
            }
        } else {
            try ghost.approvePause() {
                calls["guardianPause_ok"]++;
            } catch {
                calls["guardianPause_ko"]++;
            }
        }
    }

    // ================================================================== vues du modèle d'ombre

    function actorCount() external view returns (uint256) {
        return actors.length;
    }

    /// @notice (a) Σ des entrées (mint, transfert de M, restitution) d'horodatage ≤ now − W.
    function ghost_entriesOlderThanW() external view returns (uint256 s) {
        for (uint256 i = 0; i < _entries.length; i++) {
            if (uint256(_entries[i].t) + W <= block.timestamp) s += _entries[i].v;
        }
    }

    function shadowMaturedEffective(address a) external view returns (uint256 eff) {
        eff = _sMatured[a];
        SB[] storage b = _sBuckets[a];
        for (uint256 i = 0; i < b.length; i++) {
            if (b[i].m <= block.timestamp) eff += b[i].v;
        }
    }

    function shadowTotal(address a) external view returns (uint256 t) {
        t = _sMatured[a];
        SB[] storage b = _sBuckets[a];
        for (uint256 i = 0; i < b.length; i++) {
            t += b[i].v;
        }
    }

    /// @notice Tranches non échues du modèle, par échéance croissante.
    function shadowLive(address a) external view returns (uint64[] memory ms, uint256[] memory vs) {
        SB[] storage b = _sBuckets[a];
        uint256 n;
        for (uint256 i = 0; i < b.length; i++) {
            if (b[i].m > block.timestamp) n++;
        }
        ms = new uint64[](n);
        vs = new uint256[](n);
        uint256 j;
        for (uint256 i = 0; i < b.length; i++) {
            if (b[i].m <= block.timestamp) continue;
            ms[j] = b[i].m;
            vs[j] = b[i].v;
            j++;
        }
    }

    /// @notice Σ soldes des acteurs que le modèle a comptés dans l'incident `id`.
    function ghost_taggedSum(uint256 id) public view returns (uint256 s) {
        for (uint256 i = 0; i < actors.length; i++) {
            if (ghost_tag[actors[i]] == id) s += ghost.balanceOf(actors[i]);
        }
    }

    // ================================================================== interne : actions

    function _mintFor(address who, uint256 usdcAmount) internal {
        usdc.mint(who, usdcAmount);
        vm.prank(who);
        usdc.approve(address(pm), usdcAmount);
        vm.prank(who);
        uint256 id = pm.requestSwap(usdcAmount);
        uint256 g = usdcAmount * 1e12; // taux figé 1e18 (le handler ne le change pas)
        ghost_sumDepositsTimesRate += g;
        bool shouldWork = !ghost.paused();
        vm.prank(service);
        try pm.completeSwap(id) {
            if (!shouldWork) return _unexpectedSuccess("mint while Ghost paused");
            calls["mint_ok"]++;
            _recordIssue(who, g);
        } catch {
            if (shouldWork) _unexpectedRevert("mint");
        }
    }

    function _watcherDelay(address[] memory acc, uint256[] memory amts, uint64 duration, string memory label)
        internal
    {
        (bool ok, uint256 id, uint64 end) = _predictDelay(acc, duration, true);
        uint256[] memory sBefore = new uint256[](acc.length);
        for (uint256 i = 0; i < acc.length; i++) {
            sBefore[i] = ghost.effectiveSuspectOf(acc[i]);
        }
        vm.prank(watcher);
        try ghost.delay(acc, amts, duration) returns (uint256 got) {
            if (!ok) return _unexpectedSuccess(label);
            calls["watcherDelay_ok"]++;
            if (got != id) _fail(3, "unexpected incident id");
            _afterDelay(acc, id, end);
            for (uint256 i = 0; i < acc.length; i++) {
                if (ghost.effectiveSuspectOf(acc[i]) < sBefore[i]) _fail(3, "watcher lowered suspicion");
            }
            if (ghost_taggedSum(id) * 10_000 > BUDGET_BPS * ghost.supplyValue()) _fail(3, "budget exceeded");
        } catch {
            if (ok) _unexpectedRevert(label);
            else calls["watcherDelay_refused"]++;
        }
    }

    /// @dev Prédit l'issue d'un `_delay` d'après le modèle : incident cible, borne cumulée par
    ///      compte (série), budget (si vérifié), pause.
    function _predictDelay(address[] memory acc, uint64 duration, bool checkBudget)
        internal
        view
        returns (bool ok, uint256 id, uint64 end)
    {
        id = ghost.openIncidentId();
        (, uint64 exp, bool conf,) = ghost.incidents(id);
        bool live = id != 0 && !conf && block.timestamp < exp;
        if (live) {
            end = exp;
        } else {
            id = id + 1;
            end = uint64(block.timestamp + duration);
        }
        ok = !ghost.paused();
        uint256 ext = live ? ghost_taggedSum(id) : 0;
        for (uint256 i = 0; i < acc.length; i++) {
            (uint256 start, uint64 newEnd) = _series(acc[i], end);
            if (newEnd > start + CAP) ok = false;
            if (ghost_tag[acc[i]] != id) ext += ghost.balanceOf(acc[i]);
        }
        if (checkBudget && ext * 10_000 > BUDGET_BPS * ghost.supplyValue()) ok = false;
    }

    /// @dev Série d'extensions du modèle : nouvelle série après au moins W sans extension.
    function _series(address a, uint64 end) internal view returns (uint256 start, uint64 newEnd) {
        uint64 last = ghost_lastEnd[a];
        start = (last == 0 || block.timestamp >= uint256(last) + W) ? block.timestamp : ghost_runStart[a];
        newEnd = end > last ? end : last;
    }

    function _afterDelay(address[] memory acc, uint256 id, uint64 end) internal {
        for (uint256 i = 0; i < acc.length; i++) {
            address a = acc[i];
            (uint256 start, uint64 newEnd) = _series(a, end);
            ghost_runStart[a] = uint64(start);
            ghost_lastEnd[a] = newEnd;
            ghost_tag[a] = id;
            uint64 expected = newEnd > block.timestamp ? newEnd : 0;
            if (ghost.extendedUntil(a) != expected) _fail(3, "extendedUntil differs from model");
            if (newEnd - start > CAP) _fail(3, "extension series longer than factor x W");
        }
    }

    function _burnExpectation(address a, uint256 id) internal view returns (BurnExp memory e) {
        (uint256 sc, uint256 sp, uint256 tag) = ghost.suspectRawOf(a);
        bool toConfirmed;
        bool live;
        if (sp != 0) {
            (, uint64 tExp, bool tConf,) = ghost.incidents(tag);
            toConfirmed = tag == id || tConf;
            live = !toConfirmed && block.timestamp < tExp;
        }
        e.burn = sc + (toConfirmed ? sp : 0);
        e.bal = ghost.balanceOf(a);
        e.mBal = m.balanceOf(a);
        e.keepPending = live;
        e.sp = sp;
        e.tag = tag;
    }

    function _checkBurn(address a, BurnExp memory e) internal {
        if (e.bal - ghost.balanceOf(a) != e.burn) _fail(4, "burned != confirmed suspicion");
        (uint256 sc, uint256 sp, uint256 tag) = ghost.suspectRawOf(a);
        if (sc != 0) _fail(4, "confirmed suspicion left after destroy");
        if (e.keepPending && (sp != e.sp || tag != e.tag)) _fail(4, "other live incident pending touched");
        if (m.balanceOf(a) != e.mBal) _fail(4, "destroy touched M");
        _sBurnNewestFirst(a, e.burn);
    }

    // ================================================================== interne : modèle d'ombre

    function _recordIssue(address a, uint256 v) internal {
        _entries.push(Entry(uint64(block.timestamp), v));
        _sSettle(a);
        _sAdd(a, uint64(((block.timestamp + W + SLOT - 1) / SLOT) * SLOT), v);
    }

    function _sSettle(address a) internal {
        SB[] storage b = _sBuckets[a];
        uint256 k;
        uint256 add;
        while (k < b.length && b[k].m <= block.timestamp) {
            add += b[k].v;
            k++;
        }
        if (k == 0) return;
        for (uint256 i = k; i < b.length; i++) {
            b[i - k] = b[i];
        }
        for (uint256 i = 0; i < k; i++) {
            b.pop();
        }
        _sMatured[a] += add;
    }

    /// @dev Insertion triée (fusion si même échéance).
    function _sAdd(address a, uint64 mt, uint256 v) internal {
        if (v == 0) return;
        SB[] storage b = _sBuckets[a];
        uint256 i = b.length;
        while (i > 0 && b[i - 1].m > mt) i--;
        if (i > 0 && b[i - 1].m == mt) {
            b[i - 1].v += v;
            return;
        }
        b.push(SB(0, 0));
        for (uint256 j = b.length - 1; j > i; j--) {
            b[j] = b[j - 1];
        }
        b[i] = SB(mt, v);
    }

    /// @dev Part échue d'abord, puis tranches les plus anciennes, chacune gardant son échéance.
    function _sMove(address from, address to, uint256 v) internal {
        _sSettle(from);
        _sSettle(to);
        uint256 take = _sMatured[from] < v ? _sMatured[from] : v;
        _sMatured[from] -= take;
        _sMatured[to] += take;
        uint256 rem = v - take;
        SB[] storage b = _sBuckets[from];
        uint256 k;
        while (rem != 0) {
            if (k >= b.length) return _fail(1, "shadow underflow on move");
            uint256 t = b[k].v < rem ? b[k].v : rem;
            b[k].v -= t;
            rem -= t;
            _sAdd(to, b[k].m, t);
            if (b[k].v == 0) k++;
        }
        for (uint256 i = k; i < b.length; i++) {
            b[i - k] = b[i];
        }
        for (uint256 i = 0; i < k; i++) {
            b.pop();
        }
    }

    /// @dev Destruction : tranches les plus récentes d'abord, puis la part échue.
    function _sBurnNewestFirst(address a, uint256 v) internal {
        _sSettle(a);
        SB[] storage b = _sBuckets[a];
        while (v != 0 && b.length != 0) {
            SB storage last = b[b.length - 1];
            uint256 t = last.v < v ? last.v : v;
            last.v -= t;
            v -= t;
            if (last.v == 0) b.pop();
        }
        if (v > _sMatured[a]) return _fail(4, "shadow underflow on burn");
        _sMatured[a] -= v;
    }

    // ================================================================== interne : utilitaires

    function _actor(uint256 seed) internal view returns (address) {
        return actors[seed % actors.length];
    }

    /// @dev `min..max` acteurs DISTINCTS (rotation depuis un départ aléatoire).
    function _pick(uint256 seed, uint256 min, uint256 max) internal view returns (address[] memory acc) {
        uint256 n = min + seed % (max - min + 1);
        acc = new address[](n);
        uint256 start = (seed >> 8) % actors.length;
        for (uint256 i = 0; i < n; i++) {
            acc[i] = actors[(start + i) % actors.length];
        }
    }

    function _amounts(address[] memory acc, uint256 seed) internal view returns (uint256[] memory amts) {
        amts = new uint256[](acc.length);
        for (uint256 i = 0; i < acc.length; i++) {
            uint256 bal = ghost.balanceOf(acc[i]);
            amts[i] = uint256(keccak256(abi.encode(seed, i))) % (bal + 1);
        }
    }

    function _taggedActors(uint256 id) internal view returns (address[] memory acc) {
        uint256 n;
        for (uint256 i = 0; i < actors.length; i++) {
            if (ghost_tag[actors[i]] == id) n++;
        }
        acc = new address[](n);
        uint256 j;
        for (uint256 i = 0; i < actors.length; i++) {
            if (ghost_tag[actors[i]] == id) acc[j++] = actors[i];
        }
    }

    function _twoGuardians(uint256 seed) internal view returns (address, address) {
        uint256 i = seed % 3;
        return (guardians[i], guardians[(i + 1 + (seed >> 8) % 2) % 3]);
    }

    function _free(address a) internal returns (uint256) {
        uint256 bal = ghost.balanceOf(a);
        uint256 s = ghost.effectiveSuspectOf(a);
        if (s > bal) {
            _fail(2, "suspicion above balance");
            return 0;
        }
        return bal - s;
    }

    function _fail(uint8 kind, string memory why) internal {
        if (kind == 1) ghost_bucketViolation = true;
        else if (kind == 2) ghost_lockViolation = true;
        else if (kind == 3) ghost_watcherViolation = true;
        else ghost_destroyViolation = true;
        _firstFailure(why);
    }

    function _unexpectedRevert(string memory why) internal {
        ghost_unexpectedRevert = true;
        _firstFailure(string.concat("unexpected revert: ", why));
    }

    function _unexpectedSuccess(string memory why) internal {
        ghost_unexpectedSuccess = true;
        _firstFailure(string.concat("unexpected success: ", why));
    }

    function _firstFailure(string memory why) internal {
        if (bytes(ghost_firstFailure).length == 0) ghost_firstFailure = why;
    }
}
