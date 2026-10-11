"""Agregation des transferts par tranche (#12) : volume, dispersion, graines.

Sert `RuleBasedMonitor.check_transfer` (`detection/detector.py`). Decision
actee : docs/OPEN_ANSWERS.md §9 (ratios normalises, mediane + MAD, declencheur
« volume eleve ET dispersion effondree »). Choix NON actes, PROVISOIRES :
docs/OPEN_QUESTIONS.md §2 « Propositions (2026-10-10, Yannis) ».

Mesures d'une tranche :

- `volume_ratio` = volume DEDUPLIQUE / offre en circulation (§9 : jamais de
  volume absolu). Un montant qui rebondit A -> B -> C dans la tranche n'est
  compte qu'une fois (#87, regle PROVISOIRE : somme des soldes entrants nets,
  voir `SlotAggregate.volume`) ;
- `herfindahl` (HHI) = somme des parts au carre des soldes entrants NETS :
  mesure de dispersion de REFERENCE (§2, proposition 4), calculee la ou les
  fonds arrivent (les relais ne comptent pas). 1/HHI = « nombre effectif de
  destinataires », reporte dans `Alert.dispersion_score` (bas = concentre) ;
- `distinct_recipients` : nombre de destinataires distincts, EXPOSE pour le
  dashboard mais JAMAIS utilise comme indicateur d'attaque (§2, limite
  reperee : 50M vers 3 adresses neuves puis 4 bridges le fait passer de ~150 a
  ~157 seulement, alors que le HHI est multiplie par ~20) ;
- signaux par transfert (gros montant vers adresse neuve, decoupage, sortie
  rapide vers un point de sortie, fan-out) : ils sont DEJA captures par le HHI
  (concentration des montants sur peu de destinataires) et sont seulement
  exposes en descriptif (`new_sender_share`, `exit_share`, `max_fan_out`).
  Ils ne declenchent RIEN seuls : ce ne sont pas des surveillants separes.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from shared.models import AlertSeed, TransferEvent


def median(values: Sequence[float]) -> float:
    """Mediane d'une suite non vide.

    Raises:
        ValueError: si `values` est vide.
    """
    if not values:
        raise ValueError("mediane d'une suite vide")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def robust_zscore(
    value: float,
    history: Sequence[float],
    mad_scale: float,
    mad_floor_relative: float,
) -> float:
    """z robuste de `value` vs `history` : (x - mediane) / echelle.

    echelle = max(mad_scale x MAD, mad_floor_relative x |mediane|) ; le plancher
    evite un z infini sur une baseline parfaitement reguliere (MAD = 0).

    Args:
        value: valeur de la tranche courante.
        history: valeurs des tranches passees du meme creneau (non vide).
        mad_scale: facteur d'echelle du MAD.
        mad_floor_relative: plancher du MAD relatif a la mediane.

    Returns:
        Le z robuste (`math.inf` seulement si l'echelle est nulle et la valeur
        au-dessus de la mediane).
    """
    center = median(history)
    mad = median([abs(x - center) for x in history])
    scale = max(mad_scale * mad, mad_floor_relative * abs(center))
    if scale == 0:
        return 0.0 if value <= center else math.inf
    return (value - center) / scale


@dataclass(frozen=True)
class TransferSlotStats:
    """Mesures d'une tranche cloturee (exposees pour le dashboard).

    Attributes:
        slot_start: debut de la tranche (UTC).
        slot_end: fin de la tranche (UTC, exclue).
        transfer_count: nombre de transferts agreges.
        volume: volume deduplique (rebonds comptes une fois, #87), base units.
        gross_volume: somme brute des montants (chaque rebond recompte),
            base units, indicatif.
        circulating_supply: offre en circulation utilisee, base units.
        volume_ratio: volume (deduplique) / offre en circulation.
        herfindahl: indice de Herfindahl des soldes entrants nets (mesure de
            reference ; proche de 1 = tout part au meme endroit ; 0 si aucun
            solde net).
        effective_recipients: 1 / herfindahl (nombre effectif de
            destinataires ; s'effondre sous attaque ; 0 si aucun solde net).
        distinct_recipients: destinataires distincts (indicatif, JAMAIS seul).
        new_sender_share: part du volume envoyee par des adresses neuves
            (aucune transaction avant le debut de la tranche dans nos donnees).
        exit_share: part du volume recue par des points de sortie.
        max_fan_out: plus grand nombre de destinataires distincts d'un meme
            expediteur (eventail / decoupage).
        history_size: tranches du meme creneau dans la baseline.
        volume_zscore: z robuste du volume_ratio (None si historique
            insuffisant).
        herfindahl_zscore: z robuste du HHI (None si historique insuffisant).
    """

    slot_start: datetime
    slot_end: datetime
    transfer_count: int
    volume: int
    gross_volume: int
    circulating_supply: int
    volume_ratio: float
    herfindahl: float
    effective_recipients: float
    distinct_recipients: int
    new_sender_share: float
    exit_share: float
    max_fan_out: int
    history_size: int
    volume_zscore: float | None
    herfindahl_zscore: float | None


class SlotAggregate:
    """Transferts d'une tranche ouverte, indexes par `slot_index`.

    Les adresses sont comparees en minuscules ; la forme d'origine (premiere
    vue) est conservee pour les graines.
    """

    def __init__(self, slot_index: int) -> None:
        self.slot_index = slot_index
        self.events: list[TransferEvent] = []
        self._display: dict[str, str] = {}

    def add(self, event: TransferEvent) -> None:
        """Ajoute un transfert a la tranche."""
        self.events.append(event)
        for address in (event.sender, event.recipient):
            self._display.setdefault(address.lower(), address)

    def participants(self) -> set[str]:
        """Expediteurs et destinataires de la tranche (minuscules)."""
        return set(self._display)

    @property
    def gross_volume(self) -> int:
        """Somme brute des montants transferes (chaque rebond recompte), base units."""
        return sum(event.amount for event in self.events)

    def outflows(self) -> dict[str, int]:
        """Montant envoye par expediteur sur la tranche, base units."""
        sent: dict[str, int] = defaultdict(int)
        for event in self.events:
            sent[event.sender.lower()] += event.amount
        return dict(sent)

    def net_inflows(self) -> dict[str, int]:
        """Solde entrant net par adresse (recu - envoye), adresses > 0 seulement.

        Un relais qui recoit puis renvoie le meme montant dans la tranche a un
        solde net nul et disparait : c'est ce qui deduplique les rebonds (#87).
        """
        sent = self.outflows()
        return {
            address: received - sent.get(address, 0)
            for address, received in self.inflows().items()
            if received > sent.get(address, 0)
        }

    @property
    def volume(self) -> int:
        """Volume DEDUPLIQUE de la tranche (#87) — regle PROVISOIRE, a valider.

        Un meme montant qui transite A -> B -> C dans la tranche n'est compte
        qu'une fois : volume = somme des soldes entrants nets positifs
        (= somme des soldes sortants nets positifs, les flux se conservent).
        Exemple de reference : mint 50M -> 3 adresses neuves -> 4 bridges
        compte 50M (et non 100M en brut).

        Limites (docs/OPEN_QUESTIONS.md §2) : indifferent a l'ordre des
        transferts dans la tranche ; un aller-retour A -> B -> A compte 0 ;
        deux flux independants qui se croisent sur une meme adresse se
        compensent. Le volume brut reste expose (`gross_volume`).
        """
        return sum(self.net_inflows().values())

    def inflows(self) -> dict[str, int]:
        """Montant recu par destinataire sur la tranche, base units."""
        received: dict[str, int] = defaultdict(int)
        for event in self.events:
            received[event.recipient.lower()] += event.amount
        return dict(received)

    def herfindahl(self) -> float:
        """Indice de Herfindahl sur les soldes entrants NETS (#87).

        Coherent avec `volume` : les relais (solde net nul) ne comptent pas
        comme destinataires, la concentration se lit la ou les fonds
        arrivent. Convention : 0.0 si aucun solde net (tranche faite
        uniquement d'allers-retours).
        """
        volume = self.volume
        if volume == 0:
            return 0.0
        return sum(a * a for a in self.net_inflows().values()) / (volume * volume)

    def max_fan_out(self) -> int:
        """Plus grand nombre de destinataires distincts d'un expediteur."""
        fan_out: dict[str, set[str]] = defaultdict(set)
        for event in self.events:
            fan_out[event.sender.lower()].add(event.recipient.lower())
        return max(len(recipients) for recipients in fan_out.values())

    def share(self, predicate: Callable[[TransferEvent], bool]) -> float:
        """Part du volume BRUT des transferts verifiant `predicate` (descriptif)."""
        return sum(e.amount for e in self.events if predicate(e)) / self.gross_volume

    def largest_transfer_to(self, address: str) -> TransferEvent:
        """Plus gros transfert recu par `address` (minuscules) sur la tranche."""
        return max(
            (e for e in self.events if e.recipient.lower() == address),
            key=lambda e: e.amount,
        )

    def seeds(self, is_new: Callable[[str], bool]) -> list[AlertSeed]:
        """Graines : ou se trouvent, a la cloture, les fonds issus d'adresses
        neuves — PROVISOIRE, a valider par l'equipe.

        Un transfert envoye par une adresse neuve est suspect. Pour chaque
        adresse : montant suspect = suspect recu - envoye (si l'adresse est
        elle-meme neuve, tout ce qu'elle envoie part de ce qu'elle a recu),
        borne a 0. Les relais neufs (recu puis renvoye dans la tranche) tombent
        donc a 0 et le soupcon se retrouve la ou les fonds sont arrives
        (ex. les bridges) : la somme des graines est conservee. Ratio de la
        graine = montant suspect / montant recu sur la tranche (le module de
        reponse le recalcule sur le vrai solde Ghost).

        Limite : un attaquant aux adresses « chauffees » a l'avance
        (non neuves) ne produit aucune graine (OPEN_QUESTIONS §2 : variante
        future « moins de K transactions »).
        """
        suspect_in: dict[str, int] = defaultdict(int)
        sent_by_new: dict[str, int] = defaultdict(int)
        for event in self.events:
            sender = event.sender.lower()
            if is_new(sender):
                suspect_in[event.recipient.lower()] += event.amount
                sent_by_new[sender] += event.amount
        received = self.inflows()
        seeds: list[AlertSeed] = []
        for address in sorted(suspect_in):
            amount = suspect_in[address] - sent_by_new.get(address, 0)
            if amount <= 0:
                continue
            seeds.append(
                AlertSeed(
                    address=self._display[address],
                    suspect_amount=amount,
                    contamination_ratio=min(1.0, amount / received[address]),
                )
            )
        return seeds
