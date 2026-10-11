// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IGhostRisk} from "./interfaces/IGhostRisk.sol";
import {RiskBeacon} from "./RiskBeacon.sol";

/// @title MockLendingMarket — faux marché de prêt (volet 3, #7), FICTIF.
/// @notice Prête du MockUSDC contre du M ou du M-Ghost. Avec balise (`useBeacon`), il PRICE le
///         risque : décote `base + slope × ratio` et refus au-delà des seuils ou hors état NORMAL.
///         Sans balise, il n'appelle jamais la balise (comparaison du scénario C).
///         Prix PROVISOIRE : 1 token de garantie = 1 unité de prêt (après mise à l'échelle des
///         décimales). Pas de liquidation : le marché constate la mauvaise créance. Données
///         FICTIVES uniquement, jamais sur un vrai actif.
contract MockLendingMarket is ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 private constant BPS = 10_000;
    uint256 private constant WAD = 1e18;

    /// @notice Paramètres (PROVISOIRES, à calibrer — aucun chiffre mesuré).
    struct MarketConfig {
        bool useBeacon;
        uint16 ltvBps;
        uint16 baseHaircutBps;
        uint16 slopeHaircutBps;
        uint256 maxBorrowRatio; // 1e18, inclus
        uint256 maxBorrowSuspect; // 18 décimales, inclus
    }

    struct Position {
        uint256 collateral; // garantie déposée (comptable), 18 décimales
        uint256 suspect; // soupçon importé mesuré au dépôt (0 sans balise), 18 décimales
        uint256 debt; // en unités du token prêté
        uint64 unlockAt; // retrait interdit avant (verrou fenêtre §0bis)
    }

    IERC20 public immutable collateralToken;
    IERC20 public immutable loanToken;
    IGhostRisk public immutable ghost;
    RiskBeacon public immutable beacon;
    /// @notice 10**(décimales garantie − décimales prêt) : 1e12 pour M (18) / MockUSDC (6).
    uint256 public immutable scale;

    bool public immutable useBeacon;
    uint16 public immutable ltvBps;
    uint16 public immutable baseHaircutBps;
    uint16 public immutable slopeHaircutBps;
    uint256 public immutable maxBorrowRatio;
    uint256 public immutable maxBorrowSuspect;

    mapping(address => Position) public positions;
    uint256 public totalCollateral;
    uint256 public totalDebt;

    event Deposited(address indexed borrower, uint256 amount, uint256 importedSuspect, uint64 unlockAt);
    event Borrowed(address indexed borrower, uint256 amount);
    event Repaid(address indexed borrower, uint256 amount);
    event Withdrawn(address indexed borrower, uint256 amount);

    error ZeroAddress();
    error ZeroAmount();
    error InvalidConfig();
    error BorrowRefused(RiskBeacon.State state, uint256 ratio, uint256 suspect);
    error ExceedsCapacity(uint256 debt, uint256 capacity);
    error Locked(uint64 unlockAt);
    error RepayTooMuch(uint256 amount, uint256 debt);

    /// @param ghost_ vues du M-Ghost (fenêtre W et créneau, et soupçon importé avec balise).
    /// @param beacon_ balise ; peut être nulle si `cfg.useBeacon == false`.
    constructor(
        IERC20 collateralToken_,
        IERC20 loanToken_,
        IGhostRisk ghost_,
        RiskBeacon beacon_,
        uint256 scale_,
        MarketConfig memory cfg
    ) {
        if (address(collateralToken_) == address(0) || address(loanToken_) == address(0)) revert ZeroAddress();
        if (address(ghost_) == address(0)) revert ZeroAddress();
        if (cfg.useBeacon && address(beacon_) == address(0)) revert ZeroAddress();
        if (cfg.useBeacon && address(beacon_.ghost()) != address(ghost_)) revert InvalidConfig();
        if (scale_ == 0 || cfg.ltvBps > BPS || cfg.baseHaircutBps > BPS) revert InvalidConfig();
        collateralToken = collateralToken_;
        loanToken = loanToken_;
        ghost = ghost_;
        beacon = beacon_;
        scale = scale_;
        useBeacon = cfg.useBeacon;
        ltvBps = cfg.ltvBps;
        baseHaircutBps = cfg.baseHaircutBps;
        slopeHaircutBps = cfg.slopeHaircutBps;
        maxBorrowRatio = cfg.maxBorrowRatio;
        maxBorrowSuspect = cfg.maxBorrowSuspect;
    }

    // ------------------------------------------------------------------ Vues

    /// @notice Décote appliquée à une position (bps, plafonnée à 100 %).
    function haircutBps(address borrower) public view returns (uint256) {
        if (!useBeacon) return baseHaircutBps;
        Position storage p = positions[borrower];
        uint256 ratio = p.collateral == 0 ? 0 : (p.suspect * WAD) / p.collateral;
        uint256 h = baseHaircutBps + (uint256(slopeHaircutBps) * ratio) / WAD;
        return h > BPS ? BPS : h;
    }

    /// @notice Capacité d'emprunt (unités du token prêté) pour `collateral` et la décote courante.
    function capacityOf(address borrower) public view returns (uint256) {
        return _capacity(positions[borrower].collateral, haircutBps(borrower));
    }

    /// @notice Garantie comptée mais absente du solde réel (ex. après une destruction 2/3).
    function collateralShortfall() external view returns (uint256) {
        uint256 bal = collateralToken.balanceOf(address(this));
        return bal >= totalCollateral ? 0 : totalCollateral - bal;
    }

    // ------------------------------------------------------------------ Actions

    /// @notice Dépose de la garantie. Avec balise, mesure le soupçon que ce dépôt importe dans le
    ///         solde du marché (`effectiveSuspectOf(market)` après − avant) et l'attache à la
    ///         position. Verrouille la position jusqu'à `now + window + slot`.
    function deposit(uint256 amount) external nonReentrant {
        if (amount == 0) revert ZeroAmount();
        uint256 before = useBeacon ? ghost.effectiveSuspectOf(address(this)) : 0;
        uint256 balBefore = collateralToken.balanceOf(address(this));
        collateralToken.safeTransferFrom(msg.sender, address(this), amount);
        // Compte le montant réellement reçu (token à frais : marge d'entrée §0).
        uint256 received = collateralToken.balanceOf(address(this)) - balBefore;
        uint256 imported;
        if (useBeacon) {
            uint256 afterS = ghost.effectiveSuspectOf(address(this));
            imported = afterS > before ? afterS - before : 0;
        }
        Position storage p = positions[msg.sender];
        p.collateral += received;
        p.suspect += imported;
        uint64 unlock = uint64(block.timestamp) + ghost.window() + ghost.slot();
        if (unlock > p.unlockAt) p.unlockAt = unlock;
        totalCollateral += received;
        emit Deposited(msg.sender, received, imported, p.unlockAt);
    }

    /// @notice Emprunte du token prêté. Avec balise : refusé si l'emprunteur n'est pas NORMAL ou
    ///         si le ratio / montant suspect de la position dépasse les seuils.
    function borrow(uint256 amount) external nonReentrant {
        if (amount == 0) revert ZeroAmount();
        Position storage p = positions[msg.sender];
        if (useBeacon) {
            RiskBeacon.Risk memory r = beacon.riskOf(msg.sender);
            uint256 ratio = p.collateral == 0 ? 0 : (p.suspect * WAD) / p.collateral;
            if (r.state != RiskBeacon.State.NORMAL || ratio > maxBorrowRatio || p.suspect > maxBorrowSuspect) {
                revert BorrowRefused(r.state, ratio, p.suspect);
            }
        }
        uint256 newDebt = p.debt + amount;
        uint256 cap = capacityOf(msg.sender);
        if (newDebt > cap) revert ExceedsCapacity(newDebt, cap);
        p.debt = newDebt;
        totalDebt += amount;
        loanToken.safeTransfer(msg.sender, amount);
        emit Borrowed(msg.sender, amount);
    }

    function repay(uint256 amount) external nonReentrant {
        if (amount == 0) revert ZeroAmount();
        Position storage p = positions[msg.sender];
        if (amount > p.debt) revert RepayTooMuch(amount, p.debt);
        p.debt -= amount;
        totalDebt -= amount;
        loanToken.safeTransferFrom(msg.sender, address(this), amount);
        emit Repaid(msg.sender, amount);
    }

    /// @notice Retire de la garantie après le verrou, si la dette reste couverte.
    function withdraw(uint256 amount) external nonReentrant {
        if (amount == 0) revert ZeroAmount();
        Position storage p = positions[msg.sender];
        if (block.timestamp < p.unlockAt) revert Locked(p.unlockAt);
        uint256 remaining = p.collateral - amount; // revert (underflow) si trop
        uint256 suspectOut = p.collateral == 0 ? 0 : (p.suspect * amount) / p.collateral;
        uint256 hc = haircutBps(msg.sender);
        uint256 cap = _capacity(remaining, hc);
        if (p.debt > cap) revert ExceedsCapacity(p.debt, cap);
        p.collateral = remaining;
        p.suspect -= suspectOut;
        // Après une destruction 2/3, le solde réel peut être < garantie comptée : on paie au
        // prorata du solde réel pour qu'aucun déposant ne sorte avant les autres avec leurs
        // fonds (course au retrait). Répartition PROVISOIRE (OPEN_QUESTIONS §14).
        uint256 bal = collateralToken.balanceOf(address(this));
        uint256 payout = bal >= totalCollateral ? amount : (amount * bal) / totalCollateral;
        totalCollateral -= amount;
        collateralToken.safeTransfer(msg.sender, payout);
        emit Withdrawn(msg.sender, payout);
    }

    function _capacity(uint256 collateral, uint256 hcBps) private view returns (uint256) {
        return (collateral * (BPS - hcBps) * ltvBps) / (BPS * BPS * scale);
    }
}
