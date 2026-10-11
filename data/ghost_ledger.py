"""Modele de reference HORS CHAINE du Token Ghost (donnees FICTIVES) — issue #25.

Reproduit en Python les mecanismes actes dans `docs/OPEN_ANSWERS.md`, pour generer les
scenarios C et D et servir de point de comparaison aux tests du contrat (#8). Il ne remplace
pas le contrat : la verite reste on-chain.

- §0bis   : tout transfert produit du Ghost chez le destinataire.
- §0bis-b : la fenetre est portee par la valeur. Le solde Ghost d'une adresse est range en
  tranches d'echeance arrondies au creneau superieur ; a l'envoi, les tranches les plus
  anciennes partent en premier et gardent leur echeance ; seules les tranches echues se
  convertissent.
- §9      : un ratio de contamination par adresse (moyenne ponderee par les montants). On stocke
  le montant suspect absolu, le ratio en derive : le soupcon est conserve par les transferts.
  La destruction retire `ratio x solde Ghost non converti`.
- §3      : pendant un retard, le Ghost circule mais ne se convertit pas.
- §9      : conversion seulement si le ratio ET le montant absolu suspect sont sous seuil.
- §0bis-c : reserve = collateral - valeur(supply M + supply Ghost).
- GHOST_MARKET_SEIZURE (proposition) : marche du Ghost (decote de rapidite + commission) et
  sequestre / saisie. `lock_escrow` bloque la vraie valeur a la source ; `flag_alert` ancre la
  chaine sur la premiere adresse ayant declenche une alerte (D2) ; `market_sell` cede du Ghost a
  decote avec commission (valeur existante, jamais mintee) ; `seize` detruit le Ghost aval
  (dernier acheteur perd tout, D1) et restitue le sequestre aux autorites (D1). Voir
  `docs/GHOST_MARKET_SEIZURE.md`.

Simplifications (a signaler pour #8) :

- soupcon en `float` (le contrat utilisera du point fixe) ;
- le vrai token est considere propre : il n'a pu etre converti que sous les seuils ;
- pas de marge de conversion (bareme encore ouvert, §0) ;
- `window = 0` desactive le Ghost (monde « Resolv tel quel », baseline des mesures).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class LedgerParams:
    """Parametres du registre (a calibrer, pas des mesures).

    Attributes:
        window: fenetre Ghost normale W (§0bis, ex. 10 min). `0` = pas de Ghost.
        slot: largeur d'une tranche d'echeance (§0bis-b, proposition : 1 min).
        ratio_threshold: ratio maximal autorisant la conversion (§9).
        suspect_threshold: montant absolu suspect maximal autorisant la conversion (§9).
        commission_rate: part prelevee par le protocole sur chaque vente de Ghost au marche
            secondaire, dans [0, 1] (GHOST_MARKET_SEIZURE §1.1, D3). `0` = pas de commission.
            Prelevee en valeur deja existante (jamais mintee).
    """

    window: timedelta = timedelta(minutes=10)
    slot: timedelta = timedelta(minutes=1)
    ratio_threshold: float = 0.01
    suspect_threshold: int = 100 * 10**6
    commission_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.window < timedelta(0):
            raise ValueError("window doit etre >= 0.")
        if self.slot <= timedelta(0):
            raise ValueError("slot doit etre > 0.")
        if not 0.0 <= self.ratio_threshold <= 1.0:
            raise ValueError("ratio_threshold doit etre dans [0, 1].")
        if self.suspect_threshold < 0:
            raise ValueError("suspect_threshold doit etre >= 0.")
        if not 0.0 <= self.commission_rate <= 1.0:
            raise ValueError("commission_rate doit etre dans [0, 1].")

    @property
    def ghost_enabled(self) -> bool:
        """False si la fenetre est nulle (monde sans Ghost)."""
        return self.window > timedelta(0)


@dataclass
class Account:
    """Etat d'une adresse : vrai token, tranches Ghost, soupcon, retard eventuel."""

    real: int = 0
    tranches: dict[datetime, int] = field(default_factory=dict)
    suspect: float = 0.0
    delayed_until: datetime | None = None

    @property
    def ghost(self) -> int:
        """Solde Ghost non converti (base units)."""
        return sum(self.tranches.values())

    @property
    def ratio(self) -> float:
        """Fraction suspecte du solde Ghost, dans [0, 1]."""
        ghost = self.ghost
        return min(1.0, max(0.0, self.suspect / ghost)) if ghost else 0.0

    def matured(self, at: datetime) -> int:
        """Ghost des tranches echues a `at`."""
        return sum(amount for due, amount in self.tranches.items() if due <= at)


@dataclass(frozen=True)
class Movement:
    """Ce que recoit un destinataire lors d'un mint ou d'un transfert."""

    amount: int
    ratio: float
    maturities: tuple[tuple[datetime, int], ...]

    @property
    def expires_at(self) -> datetime | None:
        """Echeance la plus tardive des tranches recues (None si vrai token)."""
        return max((due for due, _ in self.maturities), default=None)


@dataclass(frozen=True)
class Conversion:
    """Resultat d'une tentative de conversion Ghost -> vrai token."""

    amount: int
    ratio: float
    blocked_reason: str | None = None


@dataclass(frozen=True)
class MarketSale:
    """Resultat d'une vente de Ghost sur le marche secondaire (decote de rapidite).

    Le vendeur cede `amount` de Ghost (valeur faciale) contre un prix `price <= amount` paye
    en VRAI token deja existant (jamais minte). Le protocole prend une commission `commission`
    sur ce prix. Voir `docs/GHOST_MARKET_SEIZURE.md`.

    Attributes:
        amount: montant de Ghost cede (valeur faciale), base units.
        price: prix paye par l'acheteur en vrai token, base units (`<= amount`).
        discount: decote `amount - price` (prix du risque assume par l'acheteur).
        commission: part prelevee par le protocole sur `price`, base units.
        seller_proceeds: ce que touche le vendeur `price - commission`, base units.
    """

    amount: int
    price: int
    discount: int
    commission: int
    seller_proceeds: int


@dataclass(frozen=True)
class Seizure:
    """Resultat d'une saisie (clawback) multisig sur une ancre frauduleuse.

    Detruit le Ghost frauduleux non converti encore detenu en aval, et transfere le sequestre
    de l'ancre vers l'adresse de restitution (autorites). Voir `docs/GHOST_MARKET_SEIZURE.md` D1/D2.

    Attributes:
        anchor: premiere adresse ayant declenche une alerte (point d'ancrage, D2).
        burned_ghost: Ghost frauduleux detruit en aval, base units (perte des derniers acheteurs).
        seized_collateral: sequestre transfere aux autorites, base units (restitution).
        decision_id: ReleaseDecision multisig autorisant la saisie.
    """

    anchor: str
    burned_ghost: int
    seized_collateral: int
    decision_id: str


class GhostLedger:
    """Registre de reference : soldes, tranches, ratio de contamination, collateral."""

    def __init__(self, params: LedgerParams | None = None) -> None:
        self.params = params or LedgerParams()
        self.accounts: dict[str, Account] = {}
        self.collateral = 0
        self.burned_total = 0
        self.converted_suspect = 0.0
        # --- Marche du Ghost + sequestre / saisie (GHOST_MARKET_SEIZURE) ---
        # Sequestre par ancre : vraie valeur bloquee, non recuperable par l'emetteur
        # tant que le Ghost n'est pas verifie. L'ancre est une adresse (D2).
        self.escrow: dict[str, int] = {}
        # Ancre d'une adresse : la premiere adresse ayant declenche une alerte dans la
        # chaine dont cette adresse descend (lignage d'origine, #85 piste a). None = non ancree.
        self._anchor_of: dict[str, str] = {}
        # Porteurs en aval d'une ancre (pour la saisie : qui detient du Ghost descendant).
        self._downstream: dict[str, set[str]] = {}
        # Valeur deja existante encaissee par le protocole en commission (base units).
        self.commission_collected = 0
        # Valeur saisie et restituee aux autorites (base units).
        self.seized_total = 0

    # ----------------------------------------------------------------- lecture

    def account(self, address: str) -> Account:
        """Compte d'une adresse (cree vide au besoin)."""
        return self.accounts.setdefault(address, Account())

    @property
    def supply_real(self) -> int:
        """Offre de vrai token."""
        return sum(a.real for a in self.accounts.values())

    @property
    def supply_ghost(self) -> int:
        """Offre de Ghost non converti."""
        return sum(a.ghost for a in self.accounts.values())

    @property
    def total_supply(self) -> int:
        """valeur(supply M + supply Ghost), a parite (§0bis-c)."""
        return self.supply_real + self.supply_ghost

    @property
    def reserve(self) -> int:
        """Reserve de restitution (§0bis-c). Negative = deficit."""
        return self.collateral - self.total_supply

    @property
    def deficit(self) -> int:
        """Perte du protocole : offre non adossee (0 si solvable)."""
        return max(0, -self.reserve)

    def total_suspect(self) -> float:
        """Somme des montants suspects encore en Ghost."""
        return sum(a.suspect for a in self.accounts.values())

    def is_delayed(self, address: str, at: datetime) -> bool:
        """True si l'adresse est en fenetre allongee a `at` (§3)."""
        until = self.account(address).delayed_until
        return until is not None and until > at

    def maturity_for(self, at: datetime) -> datetime:
        """Echeance d'une valeur entrant dans le Ghost a `at`, arrondie au creneau superieur."""
        slots = math.ceil((at + self.params.window - _EPOCH) / self.params.slot)
        return _EPOCH + slots * self.params.slot

    # ------------------------------------------------------------- ecritures

    def credit_real(self, address: str, amount: int, *, backed: bool = True) -> None:
        """Solde pre-existant en vrai token (genese de la simulation)."""
        self._positive(amount)
        self.account(address).real += amount
        if backed:
            self.collateral += amount

    def mint(self, address: str, amount: int, at: datetime, *, backed: bool) -> Movement:
        """Mint vers `address`. `backed=False` = fraude qui a contourne le volet 1."""
        self._positive(amount)
        if backed:
            self.collateral += amount
        return self._credit(address, amount, at, ratio=0.0)

    def transfer(
        self, sender: str, recipient: str, amount: int, at: datetime, *, from_ghost: bool
    ) -> Movement:
        """Transfert. Le Ghost garde son echeance (§0bis-b) et porte le ratio expediteur (§9)."""
        self._positive(amount)
        source = self.account(sender)
        if not from_ghost:
            if source.real < amount:
                raise ValueError("solde reel insuffisant")
            source.real -= amount
            return self._credit(recipient, amount, at, ratio=0.0)

        if source.ghost < amount:
            raise ValueError("solde Ghost insuffisant")
        ratio = source.ratio
        taken: list[tuple[datetime, int]] = []
        remaining = amount
        for due in sorted(source.tranches):  # les plus anciennes d'abord
            used = min(source.tranches[due], remaining)
            taken.append((due, used))
            source.tranches[due] -= used
            if source.tranches[due] == 0:
                del source.tranches[due]
            remaining -= used
            if remaining == 0:
                break
        source.suspect = max(0.0, source.suspect - ratio * amount)
        return self._credit(recipient, amount, at, ratio=ratio, maturities=tuple(taken))

    def convert(self, address: str, at: datetime) -> Conversion:
        """Convertit toutes les tranches echues si les conditions de §0bis-b / §3 / §9 tiennent."""
        account = self.account(address)
        matured = account.matured(at)
        ratio = account.ratio
        if matured == 0:
            return Conversion(0, ratio, "aucune tranche echue")
        if self.is_delayed(address, at):
            return Conversion(0, ratio, "fenetre allongee")
        if ratio > self.params.ratio_threshold:
            return Conversion(0, ratio, "ratio au-dessus du seuil")
        if account.suspect > self.params.suspect_threshold:
            return Conversion(0, ratio, "montant suspect au-dessus du seuil")
        for due in [d for d in account.tranches if d <= at]:
            del account.tranches[due]
        part = ratio * matured
        account.suspect = max(0.0, account.suspect - part)
        self.converted_suspect += part
        account.real += matured
        return Conversion(matured, ratio)

    def mark_suspect(self, address: str, amount: float) -> None:
        """Seme un soupcon absolu (graine d'alerte), sans double comptage ni depasser le solde."""
        account = self.account(address)
        account.suspect = min(float(account.ghost), max(account.suspect, amount))

    # ------------------------------------------- marche du Ghost + sequestre / saisie

    def lock_escrow(self, anchor: str, amount: int) -> None:
        """Place `amount` de vraie valeur en sequestre, rattachee a `anchor` (GHOST_MARKET_SEIZURE §2).

        Le sequestre n'est pas rendu a l'emetteur tant que le Ghost n'est pas verifie. On compte
        l'ancre comme son propre porteur en aval (point de depart du lignage).
        """
        self._positive(amount)
        self.escrow[anchor] = self.escrow.get(anchor, 0) + amount
        self._anchor_of.setdefault(anchor, anchor)
        self._downstream.setdefault(anchor, set()).add(anchor)

    def flag_alert(self, address: str, at: datetime, *, suspect_amount: float | None = None) -> str:
        """Declenche une alerte a l'achat de Ghost par `address` et l'ancre si besoin (D2).

        Le « premier emetteur de la chaine » = la PREMIERE adresse ayant declenche une alerte
        lors de son achat de Ghost. La premiere alerte fixe l'ancre ; les alertes suivantes de la
        meme chaine ne la deplacent pas. Seme eventuellement un soupcon absolu.

        Returns:
            L'adresse-ancre de la chaine (celle qui a declenche la premiere alerte).
        """
        anchor = self._anchor_of.get(address, address)
        self._anchor_of.setdefault(address, anchor)
        self._downstream.setdefault(anchor, set()).add(address)
        self.delay(address, at + self.params.window)
        if suspect_amount is not None:
            self.mark_suspect(address, suspect_amount)
        return anchor

    def market_sell(
        self, seller: str, buyer: str, amount: int, price: int, at: datetime
    ) -> MarketSale:
        """Vend `amount` de Ghost du vendeur a l'acheteur, a decote, avec commission (D3).

        Le Ghost (valeur faciale `amount`) part du vendeur vers l'acheteur en gardant son echeance
        et son lignage (§0bis-b, #85). L'acheteur paie `price <= amount` en VRAI token deja
        existant (jamais minte -> solvabilite preservee). Le protocole prend
        `commission = round(commission_rate x price)` sur ce prix ; le vendeur touche le reste.

        Raises:
            ValueError: montant <= 0, prix hors [0, amount], ou solde reel acheteur insuffisant.
        """
        self._positive(amount)
        if not 0 <= price <= amount:
            raise ValueError("price doit etre dans [0, amount] (pas de token minte).")
        payer = self.account(buyer)
        if payer.real < price:
            raise ValueError("solde reel insuffisant pour payer le Ghost.")

        # 1) paiement en vraie valeur existante : acheteur -> vendeur, moins commission.
        commission = round(self.params.commission_rate * price)
        seller_proceeds = price - commission
        payer.real -= price
        self.account(seller).real += seller_proceeds
        self.commission_collected += commission

        # 2) transfert du Ghost (echeance + ratio conserves) et propagation du lignage.
        self.transfer(seller, buyer, amount, at, from_ghost=True)
        anchor = self._anchor_of.get(seller)
        if anchor is not None:
            self._anchor_of.setdefault(buyer, anchor)
            self._downstream.setdefault(anchor, set()).add(buyer)

        return MarketSale(
            amount=amount,
            price=price,
            discount=amount - price,
            commission=commission,
            seller_proceeds=seller_proceeds,
        )

    def seize(self, anchor: str, authorities: str, at: datetime, decision_id: str) -> Seizure:
        """Saisie (clawback) multisig d'une ancre frauduleuse (GHOST_MARKET_SEIZURE D1/D2).

        - Detruit tout le Ghost non converti encore detenu en aval de l'ancre : les derniers
          acheteurs perdent tout (D1), ils assumaient le risque.
        - Transfere le sequestre de l'ancre vers l'adresse de restitution (`authorities`) : le
          fraudeur restitue la vraie valeur qu'il detient, qu'il n'a jamais pu sortir (D1).

        `decision_id` est la ReleaseDecision multisig : une cle seule ne saisit pas (§3).

        Returns:
            Un `Seizure` chiffrant le Ghost detruit (perte marche) et le sequestre restitue.
        """
        burned = 0
        for holder in sorted(self._downstream.get(anchor, {anchor})):
            account = self.account(holder)
            ghost = account.ghost
            if ghost == 0:
                continue
            account.tranches.clear()
            account.suspect = 0.0
            self.burned_total += ghost
            burned += ghost
            self.lift_delay(holder)

        seized = self.escrow.pop(anchor, 0)
        if seized:
            # Le sequestre quitte le protocole vers les autorites (coffre HORS systeme) : la vraie
            # valeur restituee etait adossee (collateral), elle sort donc du collateral. On NE la
            # recredite PAS comme offre en-protocole (sinon double comptage), on l'enregistre.
            self.collateral = max(0, self.collateral - seized)
            self.seized_total += seized

        return Seizure(
            anchor=anchor, burned_ghost=burned, seized_collateral=seized, decision_id=decision_id
        )

        """Allonge la fenetre d'une adresse (jamais ne la raccourcit)."""
        account = self.account(address)
        if account.delayed_until is None or account.delayed_until < until:
            account.delayed_until = until

    def delay(self, address: str, until: datetime) -> None:
        """Allonge la fenetre d'une adresse (jamais ne la raccourcit)."""
        account = self.account(address)
        if account.delayed_until is None or account.delayed_until < until:
            account.delayed_until = until

    def lift_delay(self, address: str) -> None:
        """Fin du retard (destruction appliquee ou levee multisig)."""
        self.account(address).delayed_until = None

    def burn_suspect(self, address: str, burn_ratio: float | None = None) -> int:
        """Detruit `burn_ratio x solde Ghost` (par defaut tout le soupcon). Renvoie le montant.

        Sans `burn_ratio`, le montant suspect est arrondi a l'unite superieure (sens sur : aucune
        poussiere suspecte ne survit a la destruction).
        """
        account = self.account(address)
        ghost = account.ghost
        if burn_ratio is None:
            burned = min(ghost, math.ceil(account.suspect - 1e-6))
        elif 0.0 <= burn_ratio <= 1.0:
            burned = int(burn_ratio * ghost)
        else:
            raise ValueError("burn_ratio doit etre dans [0, 1].")
        if burned == 0:
            return 0
        shares = {due: amount * burned // ghost for due, amount in account.tranches.items()}
        leftover = burned - sum(shares.values())
        for due in sorted(account.tranches, reverse=True):  # arrondi pris sur les plus recentes
            if leftover == 0:
                break
            extra = min(leftover, account.tranches[due] - shares[due])
            shares[due] += extra
            leftover -= extra
        for due, share in shares.items():
            account.tranches[due] -= share
            if account.tranches[due] == 0:
                del account.tranches[due]
        account.suspect = max(0.0, account.suspect - burned)
        self.burned_total += burned
        return burned

    # --------------------------------------------------------------- internes

    @staticmethod
    def _positive(amount: int) -> None:
        if amount <= 0:
            raise ValueError("montant doit etre > 0")

    def _credit(
        self,
        address: str,
        amount: int,
        at: datetime,
        *,
        ratio: float,
        maturities: tuple[tuple[datetime, int], ...] | None = None,
    ) -> Movement:
        account = self.account(address)
        if not self.params.ghost_enabled:
            account.real += amount
            return Movement(amount, 0.0, ())
        if maturities is None:
            maturities = ((self.maturity_for(at), amount),)
        for due, part in maturities:
            account.tranches[due] = account.tranches.get(due, 0) + part
        account.suspect += ratio * amount
        return Movement(amount, ratio, maturities)
