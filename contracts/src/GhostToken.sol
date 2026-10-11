// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {GhostedStable} from "./GhostedStable.sol";
import {GuardianActions} from "./GuardianActions.sol";
import {IGhostRisk} from "./interfaces/IGhostRisk.sol";
import {IGhostToken} from "./interfaces/IGhostToken.sol";
import {MaturityBuckets} from "./lib/MaturityBuckets.sol";

/// @notice Paramètres immuables du M-Ghost (design §3.1). Toutes les valeurs sont des PARAMÈTRES
///         à mesurer ; les valeurs des tests sont des fixtures. Pas de setter : changer une valeur
///         = redéployer.
struct GhostConfig {
    uint64 window; // W en secondes (> 0)
    uint64 slot; // durée d'un créneau (> 0, window % slot == 0, window / slot <= 255)
    uint32 maxExtensionFactor; // >= 1 : durée max d'une série de retards = factor × W
    uint16 quarantineBudgetBps; // <= 10_000 : part max de l'offre sous fenêtre allongée (incident courant)
    uint256 maxConvertRatio; // <= 1e18 : ratio max autorisant la conversion (inclus)
    uint256 maxConvertSuspect; // montant suspect absolu max autorisant la conversion (inclus)
    uint16 convertFeeBaseBps; // marge Ghost -> M, partie fixe
    uint16 convertFeeSlopeBps; // + slope × ratio / 1e18 ; base + slope <= 10_000
    uint16 entryFeeBps; // marge M -> Ghost (transfert de M) ; <= 10_000
    uint64 restitutionClaimDelay; // réservé (sweepToInsurance, suivi) ; exposé tel quel
}

/// @title GhostToken — M-Ghost (FICTIF, 18 décimales) : quarantaine liquide de M (#8).
/// @notice ERC-20 distinct (adresse propre, `Transfer` standard) qui porte tout l'état de sécurité :
///         - tranches d'échéance par adresse (`MaturityBuckets`, OPEN_ANSWERS §0bis-b) : rien n'est
///           convertible avant W après l'entrée en Ghost ; la valeur garde son échéance ;
///         - soupçon absolu par adresse en deux composantes, confirmé `Sc` et en attente `Sp`
///           (auto-expirant avec son incident), propagé au ratio de l'expéditeur (§9) ;
///         - incidents posés par le surveillant (`WATCHER_ROLE`) : il ne peut que RETARDER, dans
///           la limite de `maxExtensionFactor × W` par série et par compte et du budget de
///           quarantaine ; silence = retour automatique (§3) ;
///         - actions humaines 2/3 (destruction, restitution, extension hors budget, blanchiment)
///           et pause globale 3/3 (`GuardianPausable`), rounds séparés ;
///         - réserve de restitution `totalIssued − supplyValue` (§0bis-c), restitution plafonnée.
///         Propriétés VÉRIFIÉES PAR TESTS D'INVARIANTS (jamais « prouvées ») : voir README.
contract GhostToken is ERC20, AccessControl, GuardianActions, IGhostRisk, IGhostToken {
    using MaturityBuckets for MaturityBuckets.Account;

    bytes32 public constant WATCHER_ROLE = keccak256("WATCHER_ROLE");
    uint256 public constant MAX_BATCH = 64;
    uint256 internal constant ONE = 1e18;
    uint256 internal constant BPS = 10_000;

    enum IssueKind {
        MINT,
        TRANSFER_M,
        RESTITUTION
    }

    struct Incident {
        uint64 openedAt;
        uint64 expiresAt;
        bool confirmed;
        uint256 extendedBalance;
    }

    // ------------------------------------------------------------------ immuables

    /// @notice Seul émetteur de Ghost « mint » (le `ProtectedMinter`).
    address public immutable minter;
    /// @notice Le vrai token M (`GhostedStable`), déployé par ce contrat.
    address public immutable underlying;
    uint64 public immutable window;
    uint64 public immutable slot;
    uint32 public immutable maxExtensionFactor;
    uint16 public immutable quarantineBudgetBps;
    uint256 public immutable maxConvertRatio;
    uint256 public immutable maxConvertSuspect;
    uint16 public immutable convertFeeBaseBps;
    uint16 public immutable convertFeeSlopeBps;
    uint16 public immutable entryFeeBps;
    uint64 public immutable restitutionClaimDelay;
    /// @dev Taille de l'anneau de tranches : window / slot + 1.
    uint256 internal immutable _ring;

    // ------------------------------------------------------------------ état

    mapping(address => MaturityBuckets.Account) internal _accounts;
    mapping(address => uint256) internal _sc;
    mapping(address => uint256) internal _sp;
    /// @notice Incident portant le soupçon en attente brut (0 si aucun).
    mapping(address => uint256) public pendingTag;

    /// @notice Incidents, ids à partir de 1.
    mapping(uint256 => Incident) public incidents;
    /// @notice Dernier incident ouvert (surveillant ou `Extend` 2/3).
    uint256 public openIncidentId;
    /// @dev Fin de fenêtre allongée ; ne baisse JAMAIS.
    mapping(address => uint64) internal _extendedUntil;
    mapping(address => uint64) public extensionRunStart;
    mapping(address => uint256) public extensionTag;
    mapping(address => uint64) public destroyedAt;
    mapping(address => uint256) public destroyedIncident;
    mapping(address => uint64) public clearedAt;

    uint256 public totalIssued;
    uint256 public totalBurned;
    uint256 public totalFees;
    uint256 public totalRestituted;
    uint256 public totalConverted;
    uint256 public totalSeeded;
    uint256 public totalSuspectBurned;
    uint256 public totalSuspectExpired;
    uint256 public totalSuspectCleared;

    // ------------------------------------------------------------------ événements (design §3.12)

    event GhostIssued(
        address indexed recipient,
        address indexed source,
        uint256 indexed requestId,
        uint256 amount,
        uint256 incomingRatio,
        uint64 maturity,
        IssueKind kind
    );
    event GhostTransferred(
        address indexed from,
        address indexed to,
        uint256 amount,
        uint256 incomingRatio,
        uint256 suspectMoved,
        uint64 latestMaturity
    );
    event GhostConverted(
        address indexed holder, uint256 ghostAmount, uint256 tokenAmount, uint256 feeAmount, uint256 ratio
    );
    event IncidentOpened(uint256 indexed incidentId, address indexed actor, uint64 expiresAt);
    event PerimeterDelayed(
        uint256 indexed incidentId,
        address indexed account,
        address indexed actor,
        uint256 suspectAmount,
        uint64 extendedUntil
    );
    event SuspicionCleared(address indexed account, uint256 indexed proposalId, uint256 clearedAmount);
    event IncidentConfirmed(uint256 indexed incidentId, uint256 indexed proposalId);
    event GhostDestroyed(
        address indexed account,
        uint256 indexed incidentId,
        uint256 indexed proposalId,
        uint256 burnedAmount,
        uint256 ratio,
        uint256 suspectAmount
    );
    event Restituted(address indexed to, uint256 indexed proposalId, uint256 amount);

    // ------------------------------------------------------------------ erreurs (design §3.13)

    error InvalidConfig(uint8 field);
    error ZeroAddress();
    error ZeroAmount();
    error NotMinter(address caller);
    error NotUnderlying(address caller);
    error NotMatured(uint256 requested, uint256 matured);
    error WindowExtended(uint64 extendedUntil);
    error SuspicionAboveThreshold(uint256 ratio, uint256 suspect);
    error SuspectPartLocked(uint256 requested, uint256 available);
    error LengthMismatch();
    error BatchTooLarge(uint256 length);
    error InvalidDuration();
    error ExtensionTooLong(address account, uint64 end);
    error QuarantineBudgetExceeded(uint256 extendedBalance, uint256 supplyValue);
    error UnknownIncident(uint256 incidentId);
    error IncidentExpired(uint256 incidentId);
    error ExceedsReserve(uint256 amount, uint256 reserve);

    constructor(address minter_, address admin, address[3] memory guardians_, GhostConfig memory cfg)
        ERC20("M-Ghost (fictif)", "gpUSD")
        GuardianActions(guardians_)
    {
        if (minter_ == address(0) || admin == address(0)) revert ZeroAddress();
        if (cfg.window == 0) revert InvalidConfig(0);
        if (cfg.slot == 0 || cfg.window % cfg.slot != 0 || cfg.window / cfg.slot > 255) revert InvalidConfig(1);
        if (cfg.maxExtensionFactor == 0) revert InvalidConfig(2);
        if (cfg.quarantineBudgetBps > BPS) revert InvalidConfig(3);
        if (cfg.maxConvertRatio > ONE) revert InvalidConfig(4);
        if (uint256(cfg.convertFeeBaseBps) + cfg.convertFeeSlopeBps > BPS) revert InvalidConfig(7);
        if (cfg.entryFeeBps > BPS) revert InvalidConfig(8);

        minter = minter_;
        window = cfg.window;
        slot = cfg.slot;
        maxExtensionFactor = cfg.maxExtensionFactor;
        quarantineBudgetBps = cfg.quarantineBudgetBps;
        maxConvertRatio = cfg.maxConvertRatio;
        maxConvertSuspect = cfg.maxConvertSuspect;
        convertFeeBaseBps = cfg.convertFeeBaseBps;
        convertFeeSlopeBps = cfg.convertFeeSlopeBps;
        entryFeeBps = cfg.entryFeeBps;
        restitutionClaimDelay = cfg.restitutionClaimDelay;
        _ring = cfg.window / cfg.slot + 1;
        underlying = address(new GhostedStable(address(this)));
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    // ================================================================== points d'entrée (IGhostToken)

    /// @inheritdoc IGhostToken
    function issueFromMinter(address to, uint256 amount, uint256 requestId) external {
        if (msg.sender != minter) revert NotMinter(msg.sender);
        _requireNotPaused();
        uint64 m = _issue(to, amount);
        totalIssued += amount;
        emit GhostIssued(to, msg.sender, requestId, amount, 0, m, IssueKind.MINT);
    }

    /// @inheritdoc IGhostToken
    function onUnderlyingTransfer(address from, address to, uint256 amount) external {
        if (msg.sender != underlying) revert NotUnderlying(msg.sender);
        _requireNotPaused();
        uint256 fee = amount * entryFeeBps / BPS;
        uint256 net = amount - fee;
        uint64 m;
        if (net != 0) m = _issue(to, net);
        totalFees += fee;
        emit GhostIssued(to, from, 0, net, 0, m, IssueKind.TRANSFER_M);
    }

    // ================================================================== conversion Ghost -> M (§3.5)

    /// @notice Convertit `amount` Ghost échu, sans soupçon valide, en M (moins la marge).
    function convert(uint256 amount) external returns (uint256 tokenOut) {
        _requireNotPaused();
        if (amount == 0) revert ZeroAmount();
        address a = msg.sender;
        uint256 bal = balanceOf(a);
        if (bal == 0) revert NotMatured(amount, 0);
        _normalize(a);
        MaturityBuckets.Account storage acc = _accounts[a];
        acc.settle(_ring);
        uint256 matured = acc.matured;
        if (amount > matured) revert NotMatured(amount, matured);
        uint64 ext = _extendedUntil[a];
        if (block.timestamp < ext) revert WindowExtended(ext);
        uint256 s = _sc[a] + _sp[a];
        uint256 ratioUp = Math.mulDiv(s, ONE, bal, Math.Rounding.Ceil);
        if (ratioUp > maxConvertRatio || s > maxConvertSuspect) revert SuspicionAboveThreshold(ratioUp, s);
        if (amount > bal - s) revert SuspectPartLocked(amount, bal - s);
        uint256 ratio = s * ONE / bal;
        uint256 fee = amount * (convertFeeBaseBps + convertFeeSlopeBps * ratio / ONE) / BPS;
        tokenOut = amount - fee;
        acc.matured = matured - amount;
        totalFees += fee;
        totalConverted += amount;
        _burn(a, amount);
        GhostedStable(underlying).mint(a, tokenOut);
        emit GhostConverted(a, amount, tokenOut, fee, ratio);
    }

    // ================================================================== surveillant (§3.4)

    /// @notice RETARDE `accounts` (sens sûr uniquement) : rejoint l'incident vivant non confirmé
    ///         ou en ouvre un d'une durée `duration`. Sème `Sp = max(Sp, min(montant, solde − Sc))`.
    ///         Bornes : `maxExtensionFactor × W` par incident et par série d'extensions d'un compte,
    ///         budget de quarantaine de l'incident courant. Tout le lot revert si une borne casse.
    function delay(address[] calldata accounts, uint256[] calldata suspectAmounts, uint64 duration)
        external
        onlyRole(WATCHER_ROLE)
        returns (uint256 incidentId)
    {
        return _delay(accounts, suspectAmounts, duration, true, msg.sender);
    }

    // ================================================================== guardians 2/3 (§3.6, §3.6bis, §3.7)

    /// @notice Propose de confirmer `incidentId` et de brûler le soupçon CONFIRMÉ de `targets`
    ///         (liste vide = confirmation seule).
    function proposeDestroy(uint256 incidentId, address[] calldata targets)
        external
        onlyGuardian
        returns (uint256)
    {
        if (targets.length > MAX_BATCH) revert BatchTooLarge(targets.length);
        _checkNonZero(targets);
        if (incidentId == 0 || incidentId > openIncidentId) revert UnknownIncident(incidentId);
        return _propose(ActionKind.Destroy, abi.encode(incidentId, targets));
    }

    /// @notice Propose d'émettre `amount` Ghost frais à la victime `to`, plafonné par `reserve()`
    ///         à l'exécution.
    function proposeRestitution(address to, uint256 amount) external onlyGuardian returns (uint256) {
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        return _propose(ActionKind.Restitution, abi.encode(to, amount));
    }

    /// @notice Propose un retard hors budget (humain requis au-delà du budget du surveillant) ;
    ///         mêmes bornes de durée que le surveillant, auto-expirant.
    function proposeExtend(address[] calldata accounts, uint256[] calldata suspectAmounts, uint64 duration)
        external
        onlyGuardian
        returns (uint256)
    {
        _checkBatch(accounts.length);
        if (accounts.length != suspectAmounts.length) revert LengthMismatch();
        _checkNonZero(accounts);
        _checkDuration(duration);
        return _propose(ActionKind.Extend, abi.encode(accounts, suspectAmounts, duration));
    }

    /// @notice Propose de blanchir `accounts` (audit : soupçon remis à 0 ; extension inchangée).
    function proposeClear(address[] calldata accounts) external onlyGuardian returns (uint256) {
        _checkBatch(accounts.length);
        _checkNonZero(accounts);
        return _propose(ActionKind.Clear, abi.encode(accounts));
    }

    // ================================================================== vues (IGhostRisk)

    function effectiveSuspectOf(address account) public view returns (uint256) {
        return _sc[account] + _spValid(account);
    }

    function suspectComponentsOf(address account)
        external
        view
        returns (uint256 confirmed, uint256 pendingValid, uint256 pendingIncidentId)
    {
        confirmed = _sc[account];
        pendingValid = _spValid(account);
        pendingIncidentId = pendingValid == 0 ? 0 : pendingTag[account];
    }

    /// @notice Soupçon brut stocké (Sc, Sp non filtré par l'expiration, tag) : tests d'invariants.
    function suspectRawOf(address account) external view returns (uint256 sc, uint256 sp, uint256 tag) {
        return (_sc[account], _sp[account], pendingTag[account]);
    }

    function ratioOf(address account) external view returns (uint256) {
        uint256 bal = balanceOf(account);
        return bal == 0 ? 0 : effectiveSuspectOf(account) * ONE / bal;
    }

    function extendedUntil(address account) external view returns (uint64) {
        uint64 e = _extendedUntil[account];
        return block.timestamp < e ? e : 0;
    }

    function maxExtensionEnd(address account) external view returns (uint64) {
        uint256 prev = _extendedUntil[account];
        uint256 start = (prev == 0 || block.timestamp >= prev + window) ? block.timestamp : extensionRunStart[account];
        return uint64(start + uint256(maxExtensionFactor) * window);
    }

    function convertibleOf(address account) external view returns (uint256) {
        if (block.timestamp < _extendedUntil[account]) return 0;
        uint256 bal = balanceOf(account);
        if (bal == 0) return 0;
        uint256 s = effectiveSuspectOf(account);
        if (Math.mulDiv(s, ONE, bal, Math.Rounding.Ceil) > maxConvertRatio || s > maxConvertSuspect) return 0;
        uint256 eff = _accounts[account].maturedEffective(_ring);
        return Math.min(eff, bal - s);
    }

    function maturedEffectiveOf(address account) external view returns (uint256) {
        return _accounts[account].maturedEffective(_ring);
    }

    function maturedOf(address account) external view returns (uint256) {
        return _accounts[account].matured;
    }

    function bucketsOf(address account) external view returns (uint64[] memory, uint256[] memory) {
        return _accounts[account].list(_ring);
    }

    function nextOutgoingMaturity(address account, uint256 amount) external view returns (uint64) {
        return _accounts[account].nextOutgoing(amount, slot, _ring);
    }

    function reserve() public view returns (uint256) {
        uint256 s = supplyValue();
        return totalIssued > s ? totalIssued - s : 0;
    }

    function supplyValue() public view returns (uint256) {
        return GhostedStable(underlying).totalSupply() + totalSupply();
    }

    function paused() public view override(Pausable, IGhostRisk) returns (bool) {
        return super.paused();
    }

    // ================================================================== interne : ERC-20

    /// @dev Transfert de Ghost (from, to non nuls) : soupçon et tranches suivent la valeur.
    ///      Mint / burn : seul `extendedBalance` est mis à jour ici (tranches et soupçon sont gérés
    ///      par `_issue`, `convert` et la destruction).
    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0)) {
            _requireNotPaused();
            if (value != 0 && from != to) {
                _moveGhost(from, to, value);
                return;
            }
        } else {
            _trackExtended(from, to, value);
        }
        super._update(from, to, value);
    }

    function _moveGhost(address from, address to, uint256 v) private {
        uint256 bal = balanceOf(from);
        if (bal < v) revert ERC20InsufficientBalance(from, bal, v);
        _normalize(from);
        _normalize(to);
        uint256 sc = _sc[from];
        uint256 sp = _sp[from];
        uint256 moved;
        if (sc != 0 || sp != 0) {
            // Ratio de l'expéditeur, arrondi vers le haut (sens sûr) ; somme conservée exactement.
            moved = Math.mulDiv(v, sc + sp, bal, Math.Rounding.Ceil);
            uint256 movedC = Math.min(sc, Math.mulDiv(v, sc, bal, Math.Rounding.Ceil));
            uint256 movedP = moved - movedC;
            if (movedC != 0) {
                _sc[from] = sc - movedC;
                _sc[to] += movedC;
            }
            if (movedP != 0) {
                _sp[from] = sp - movedP;
                _sp[to] += movedP;
                pendingTag[to] = pendingTag[from];
                if (movedP == sp) pendingTag[from] = 0;
            }
        }
        MaturityBuckets.Account storage af = _accounts[from];
        MaturityBuckets.Account storage at = _accounts[to];
        uint256 ring = _ring;
        af.settle(ring);
        at.settle(ring);
        uint64 latest = af.move(at, v, slot, ring);
        _trackExtended(from, to, v);
        super._update(from, to, v);
        emit GhostTransferred(from, to, v, moved * ONE / v, moved, latest);
    }

    /// @dev `extendedBalance` de l'incident courant = Σ soldes des comptes qu'il a comptés.
    function _trackExtended(address from, address to, uint256 v) private {
        uint256 id = openIncidentId;
        if (id == 0 || v == 0) return;
        if (from != address(0) && extensionTag[from] == id) incidents[id].extendedBalance -= v;
        if (to != address(0) && extensionTag[to] == id) incidents[id].extendedBalance += v;
    }

    /// @dev Émission fraîche : tranche d'échéance `ceil(now + W)`.
    function _issue(address to, uint256 v) internal returns (uint64 m) {
        m = _accounts[to].issue(v, window, slot, _ring);
        _mint(to, v);
    }

    // ================================================================== interne : soupçon

    /// @dev Sp valide ssi son incident est confirmé ou encore vivant (invalidation paresseuse).
    function _spValid(address a) internal view returns (uint256) {
        uint256 sp = _sp[a];
        if (sp == 0) return 0;
        Incident storage inc = incidents[pendingTag[a]];
        return (inc.confirmed || block.timestamp < inc.expiresAt) ? sp : 0;
    }

    /// @dev Confirmé -> Sp bascule en Sc ; expiré non confirmé -> Sp compté expiré ; sinon rien.
    function _normalize(address a) internal {
        uint256 sp = _sp[a];
        if (sp == 0) return;
        Incident storage inc = incidents[pendingTag[a]];
        if (inc.confirmed) _sc[a] += sp;
        else if (block.timestamp >= inc.expiresAt) totalSuspectExpired += sp;
        else return;
        _sp[a] = 0;
        pendingTag[a] = 0;
    }

    // ================================================================== interne : retards

    function _delay(
        address[] memory accounts,
        uint256[] memory amounts,
        uint64 duration,
        bool checkBudget,
        address actor
    ) internal returns (uint256 id) {
        _requireNotPaused();
        _checkBatch(accounts.length);
        if (accounts.length != amounts.length) revert LengthMismatch();
        id = openIncidentId;
        Incident storage inc = incidents[id];
        if (id == 0 || inc.confirmed || block.timestamp >= inc.expiresAt) {
            // Pas d'incident non confirmé vivant : on en ouvre un (échéance figée).
            _checkDuration(duration);
            id++;
            openIncidentId = id;
            inc = incidents[id];
            inc.openedAt = uint64(block.timestamp);
            inc.expiresAt = uint64(block.timestamp + duration);
            emit IncidentOpened(id, actor, inc.expiresAt);
        }
        uint64 end = inc.expiresAt;
        uint256 cap = uint256(maxExtensionFactor) * window;
        for (uint256 i = 0; i < accounts.length; i++) {
            address a = accounts[i];
            if (a == address(0)) revert ZeroAddress();
            _normalize(a);
            // Borne cumulée par compte : une série contiguë d'extensions dure au plus cap ;
            // deux séries sont séparées d'au moins W sans extension.
            uint64 prev = _extendedUntil[a];
            if (prev == 0 || block.timestamp >= uint256(prev) + window) {
                extensionRunStart[a] = uint64(block.timestamp);
            }
            uint64 newEnd = end > prev ? end : prev;
            if (newEnd > uint256(extensionRunStart[a]) + cap) revert ExtensionTooLong(a, newEnd);
            _extendedUntil[a] = newEnd;
            // Semis : ne fait qu'augmenter, plafonné à la part non confirmée du solde.
            uint256 bal = balanceOf(a);
            uint256 room = bal - _sc[a];
            uint256 want = amounts[i] < room ? amounts[i] : room;
            uint256 sp = _sp[a];
            if (want > sp) {
                totalSeeded += want - sp;
                _sp[a] = want;
                sp = want;
            }
            if (sp != 0) pendingTag[a] = id;
            if (extensionTag[a] != id) {
                extensionTag[a] = id;
                inc.extendedBalance += bal;
            }
            emit PerimeterDelayed(id, a, actor, sp, newEnd);
        }
        if (checkBudget) {
            uint256 supply = supplyValue();
            if (inc.extendedBalance * BPS > uint256(quarantineBudgetBps) * supply) {
                revert QuarantineBudgetExceeded(inc.extendedBalance, supply);
            }
        }
    }

    function _checkBatch(uint256 n) private pure {
        if (n == 0 || n > MAX_BATCH) revert BatchTooLarge(n);
    }

    function _checkNonZero(address[] calldata accounts) private pure {
        for (uint256 i = 0; i < accounts.length; i++) {
            if (accounts[i] == address(0)) revert ZeroAddress();
        }
    }

    function _checkDuration(uint64 duration) private view {
        if (duration == 0) revert InvalidDuration();
        if (duration > uint256(maxExtensionFactor) * window) {
            revert ExtensionTooLong(address(0), uint64(block.timestamp + duration));
        }
    }

    // ================================================================== interne : actions 2/3

    function _executeAction(uint256 proposalId, ActionKind kind, bytes memory params) internal override {
        if (kind == ActionKind.Destroy) {
            (uint256 incidentId, address[] memory targets) = abi.decode(params, (uint256, address[]));
            _destroy(proposalId, incidentId, targets);
        } else if (kind == ActionKind.Restitution) {
            (address to, uint256 amount) = abi.decode(params, (address, uint256));
            _restitute(proposalId, to, amount);
        } else if (kind == ActionKind.Extend) {
            (address[] memory accounts, uint256[] memory amounts, uint64 duration) =
                abi.decode(params, (address[], uint256[], uint64));
            _delay(accounts, amounts, duration, false, address(this));
        } else {
            _clear(proposalId, abi.decode(params, (address[])));
        }
    }

    /// @dev Confirme l'incident (doit être vivant s'il ne l'est pas déjà) puis brûle le soupçon
    ///      confirmé de chaque cible. Permis pendant la pause.
    function _destroy(uint256 proposalId, uint256 incidentId, address[] memory targets) private {
        Incident storage inc = incidents[incidentId];
        if (!inc.confirmed) {
            if (block.timestamp >= inc.expiresAt) revert IncidentExpired(incidentId);
            inc.confirmed = true;
            emit IncidentConfirmed(incidentId, proposalId);
        }
        for (uint256 i = 0; i < targets.length; i++) {
            address a = targets[i];
            _normalize(a);
            uint256 bal = balanceOf(a);
            uint256 burned = _sc[a];
            uint256 ratio = bal == 0 ? 0 : burned * ONE / bal;
            uint256 suspect = burned + _sp[a];
            _burnSuspect(a, burned);
            destroyedAt[a] = uint64(block.timestamp);
            destroyedIncident[a] = incidentId;
            emit GhostDestroyed(a, incidentId, proposalId, burned, ratio, suspect);
        }
    }

    /// @dev Brûle `amount` du soupçon confirmé de `a` (tranches les plus récentes d'abord).
    ///      POINT D'EXTENSION (non implémenté, #85 option b) : une destruction depuis une racine de
    ///      Merkle signée 2/3 (liste recalculée hors chaîne, contestable) se brancherait ici avec un
    ///      `amount` lu dans la feuille prouvée au lieu de `Sc` ; le coût reste O(ring) par compte.
    function _burnSuspect(address a, uint256 amount) internal {
        if (amount == 0) return;
        MaturityBuckets.Account storage acc = _accounts[a];
        acc.settle(_ring);
        acc.burnNewestFirst(amount, slot, _ring);
        _sc[a] -= amount;
        totalBurned += amount;
        totalSuspectBurned += amount;
        _burn(a, amount);
    }

    function _restitute(uint256 proposalId, address to, uint256 amount) private {
        _requireNotPaused();
        uint256 r = reserve();
        if (amount > r) revert ExceedsReserve(amount, r);
        uint64 m = _issue(to, amount);
        totalRestituted += amount;
        emit GhostIssued(to, address(this), 0, amount, 0, m, IssueKind.RESTITUTION);
        emit Restituted(to, proposalId, amount);
    }

    function _clear(uint256 proposalId, address[] memory accounts) private {
        for (uint256 i = 0; i < accounts.length; i++) {
            address a = accounts[i];
            _normalize(a);
            uint256 cleared = _sc[a] + _sp[a];
            if (cleared != 0) {
                _sc[a] = 0;
                _sp[a] = 0;
                pendingTag[a] = 0;
                totalSuspectCleared += cleared;
            }
            clearedAt[a] = uint64(block.timestamp);
            emit SuspicionCleared(a, proposalId, cleared);
        }
    }
}
