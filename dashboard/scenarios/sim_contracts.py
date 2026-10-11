"""Contrats simules en Python : simulation hors chaîne, à remplacer par #4/#5, #7 et #8.

Modeles minimaux, deterministes, sans aucune garantie de securite : ils servent
seulement a MESURER l'issue des scenarios de demo. Montants en base units (int).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from shared.models import MintRequest


class VulnerableMinter:
    """simulation hors chaîne, à remplacer par #4/#5 : credite le montant SIGNE."""

    def __init__(self) -> None:
        self.supply = 0
        self.collateral = 0

    def mint(self, signed_amount: int, deposit: int) -> int:
        """Credite `signed_amount` quel que soit le depot ; renvoie le montant emis."""
        self.supply += signed_amount
        self.collateral += deposit
        return signed_amount

    def unbacked(self) -> int:
        """Offre non adossee au depot (perte protocole)."""
        return max(0, self.supply - self.collateral)


class ProtectedMinter:
    """simulation hors chaîne, à remplacer par #4/#5 : derive le montant du depot on-chain."""

    def __init__(self) -> None:
        self.supply = 0
        self.collateral = 0

    def process(self, request: MintRequest) -> int:
        """Traite « la demande n°X » : credite `deposit_amount`, ignore tout montant signe."""
        self.supply += request.deposit_amount
        self.collateral += request.deposit_amount
        return request.deposit_amount

    def unbacked(self) -> int:
        """Offre non adossee au depot (perte protocole)."""
        return max(0, self.supply - self.collateral)


@dataclass
class GhostLot:
    """Lot de Ghost non converti (vérité terrain de la simulation pour `ratio`)."""

    amount: int
    ratio: float
    minted_at: datetime


class GhostLedger:
    """simulation hors chaîne, à remplacer par #8 : soldes Ghost non convertis par adresse.

    Chaque lot devient convertible 1:1 apres `window` ; un retard (`hold`) repousse
    la conversion de toute l'adresse. `converted_suspect` = vrai token emis contre
    du Ghost suspect (ratio x montant converti), base de la perte protocole.
    """

    def __init__(self, window: timedelta) -> None:
        self.window = window
        self._lots: dict[str, list[GhostLot]] = {}
        self._held_until: dict[str, datetime] = {}
        self.converted: dict[str, int] = {}
        self.converted_suspect: dict[str, float] = {}
        self.burned: dict[str, int] = {}

    def credit(self, address: str, amount: int, ratio: float, at: datetime) -> None:
        """Emet `amount` de Ghost chez `address` a `at` (ratio porte par le montant)."""
        self._lots.setdefault(address, []).append(GhostLot(amount, ratio, at))

    def _live(self, address: str, at: datetime) -> list[GhostLot]:
        return [lot for lot in self._lots.get(address, []) if lot.minted_at <= at and lot.amount]

    def balance(self, address: str, at: datetime) -> int:
        """Ghost non converti detenu a `at`."""
        return sum(lot.amount for lot in self._live(address, at))

    def ratio(self, address: str, at: datetime) -> float:
        """Ratio de contamination pondere du Ghost non converti a `at` (0.0 si vide)."""
        lots = self._live(address, at)
        total = sum(lot.amount for lot in lots)
        return sum(lot.amount * lot.ratio for lot in lots) / total if total else 0.0

    def hold(self, address: str, until: datetime) -> None:
        """Retard : aucune conversion de `address` avant `until`."""
        self._held_until[address] = max(until, self._held_until.get(address, until))

    def transfer(self, sender: str, recipient: str, amount: int, at: datetime,
                 keep_window: bool = False) -> int:
        """Deplace jusqu'a `amount` de Ghost (FIFO, ratio conserve).

        Par defaut : nouvelle fenetre chez le destinataire. `keep_window=True` : le lot
        garde son echeance d'origine (OPEN_ANSWERS §0bis-b, comme `data/generate.py`).
        """
        moved = 0
        for lot in self._live(sender, at):
            take = min(lot.amount, amount - moved)
            if take <= 0:
                break
            lot.amount -= take
            moved += take
            self.credit(recipient, take, lot.ratio, lot.minted_at if keep_window else at)
        return moved

    def convert_after_window(self, at: datetime) -> dict[str, int]:
        """Convertit 1:1 les lots dont la fenetre est passee (hors retard) ; renvoie les montants."""
        converted: dict[str, int] = {}
        for address, lots in self._lots.items():
            if self._held_until.get(address, at) > at:
                continue
            for lot in lots:
                if lot.amount and lot.minted_at + self.window <= at:
                    converted[address] = converted.get(address, 0) + lot.amount
                    self.converted[address] = self.converted.get(address, 0) + lot.amount
                    self.converted_suspect[address] = (
                        self.converted_suspect.get(address, 0.0) + lot.amount * lot.ratio
                    )
                    lot.amount = 0
        return converted

    def burn(self, address: str, ratio: float, at: datetime) -> int:
        """Detruit ratio x solde non converti ; le reste devient sain (ratio 0)."""
        lots = self._live(address, at)
        to_burn = int(ratio * sum(lot.amount for lot in lots))
        burned = 0
        for lot in lots:
            take = min(lot.amount, to_burn - burned)
            lot.amount -= take
            burned += take
            lot.ratio = 0.0
        self.burned[address] = self.burned.get(address, 0) + burned
        return burned

    def total_converted_suspect(self) -> int:
        """Vrai token emis contre du Ghost suspect, toutes adresses (base units)."""
        return int(sum(self.converted_suspect.values()))


class LendingMarket:
    """simulation hors chaîne, à remplacer par #7 : faux marche de pret lisant (ou non) la balise."""

    def __init__(self, reads_beacon: bool, ltv: float, ratio_threshold: float) -> None:
        self.reads_beacon = reads_beacon
        self.ltv = ltv
        self.ratio_threshold = ratio_threshold
        self.borrowed: dict[str, int] = {}
        self.accepted = 0
        self.refused: list[str] = []

    def deposit_and_borrow(self, address: str, collateral: int, published_ratio: float) -> bool:
        """Accepte le Ghost en garantie et prete `ltv` x garantie, sauf ratio publie > seuil."""
        if self.reads_beacon and published_ratio > self.ratio_threshold:
            self.refused.append(address)
            return False
        self.borrowed[address] = self.borrowed.get(address, 0) + int(collateral * self.ltv)
        self.accepted += 1
        return True

    def bad_debt(self, destroyed_addresses: Iterable[str]) -> int:
        """Somme pretee contre une garantie ensuite detruite (base units)."""
        destroyed = set(destroyed_addresses)
        return sum(amount for address, amount in self.borrowed.items() if address in destroyed)


class ConstantProductPool:
    """simulation hors chaîne, à remplacer par #8 : pool AMM Ghost/stable x*y=k."""

    def __init__(self, ghost_reserve: int, stable_reserve: int) -> None:
        self.ghost_reserve = ghost_reserve
        self.stable_reserve = stable_reserve

    @property
    def ghost_balance(self) -> int:
        """Ghost detenu par le pool."""
        return self.ghost_reserve

    def sell_ghost(self, amount: int) -> int:
        """Vend `amount` de Ghost au pool ; renvoie le stable verse (arrondi en faveur du pool)."""
        k = self.ghost_reserve * self.stable_reserve
        new_ghost = self.ghost_reserve + amount
        new_stable = -(-k // new_ghost)  # plafond : x*y ne descend jamais sous k
        stable_out = self.stable_reserve - new_stable
        self.ghost_reserve, self.stable_reserve = new_ghost, new_stable
        return stable_out

    def burn_ghost(self, amount: int) -> None:
        """Destruction de Ghost detenu par le pool (perte des fournisseurs de liquidite)."""
        self.ghost_reserve -= min(amount, self.ghost_reserve)
