"""Entrees du surveillant de mint (types internes a `detection/`).

`MintContext` regroupe ce que les invariants de docs/OPEN_ANSWERS.md §1
demandent en plus du mint observe : depot, taux, deposant, offre totale,
collateral, evenements d'administration, taux de reference.

Depuis la revision groupee de `shared/` (#104, PR #135), `shared.models.MintEvent`
porte le depot, le deposant, le taux et `via_protected_path`, et
`shared.models.AdminEvent` les evenements d'administration :
`detection.provenance.mint_context_from_event` / `admin_event_from_shared` les
traduisent vers les types ci-dessous, qui restent l'API du surveillant.

Restent hors `shared/` : l'offre en circulation, le taux de reference et les
annonces d'administration (`AdminAnnouncement`). Le depot n'est jamais retrouve
via `MintEvent.request_id` (qui peut valoir `None`, decision #79, OPEN_ANSWERS
§79) : il vient des champs de demande du `MintEvent` ou de l'appelant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction

_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


def _check_address(name: str, value: str) -> None:
    if not _ADDRESS_RE.match(value):
        raise ValueError(f"{name} : adresse EVM invalide {value!r}")


def _check_non_negative(name: str, value: int | None) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{name} doit etre >= 0")


class AdminEventKind(str, Enum):
    """Evenements d'administration surveilles (OPEN_ANSWERS §1, Q2).

    Liste exacte encore ouverte (§1 « Reste ouvert ») : PROVISOIRE.
    """

    UPGRADED = "upgraded"
    ROLE_GRANTED = "role_granted"
    ORACLE_CHANGED = "oracle_changed"
    RATE_CHANGED = "rate_changed"
    # #104 : retrait d'un role (AccessControl `RoleRevoked`), p. ex. un admin
    # legitime evince apres une prise de controle.
    ROLE_REVOKED = "role_revoked"


@dataclass(frozen=True)
class AdminEvent:
    """Evenement d'administration observe on-chain.

    Attributes:
        kind: nature de l'evenement.
        subject_address: adresse concernee (nouvelle implementation, compte
            recevant le role, nouvel oracle...).
        tx_hash: transaction ayant emis l'evenement.
    """

    kind: AdminEventKind
    subject_address: str
    tx_hash: str

    def __post_init__(self) -> None:
        _check_address("subject_address", self.subject_address)
        if not _TX_HASH_RE.match(self.tx_hash):
            raise ValueError(f"tx_hash invalide {self.tx_hash!r}")


@dataclass(frozen=True)
class AdminAnnouncement:
    """Changement d'administration annonce au prealable (donc attendu).

    Le canal d'annonce n'est pas tranche par l'equipe : PROVISOIRE, un
    changement est « annonce » si (kind, subject_address) a ete declare au
    surveillant avant d'etre observe.
    """

    kind: AdminEventKind
    subject_address: str

    def __post_init__(self) -> None:
        _check_address("subject_address", self.subject_address)


@dataclass(frozen=True)
class MintContext:
    """Donnees necessaires aux invariants, fournies par l'appelant.

    Chaque groupe est optionnel : une verification dont les entrees manquent
    est SAUTEE (ce n'est pas une anomalie). Montants en base units du token
    minte sauf mention contraire.

    Attributes:
        deposit_amount: depot de la demande traitee par ce mint, base units du
            token depose (I1). Fourni par l'appelant, PAS retrouve via
            `request_id` (voir docstring du module).
        rate: taux applique par le contrat, en base units mintees par base
            unit deposee (I1 ; compare a `reference_rate`).
        reference_rate: taux d'une source de reference independante, meme
            unite que `rate` (ecart delta). Source non tranchee (§1).
        total_supply_before: offre totale avant l'intervalle observe (I5).
        total_supply_after: offre totale apres l'intervalle observe (I5, I6).
        interval_minted_total: Somme des Mint observes sur l'intervalle ;
            None = ce seul mint (`event.amount`) (I5).
        interval_burned_total: Somme des Burn observes sur l'intervalle (I5).
        collateral_value: valeur du collateral, exprimee en base units du
            token minte (I6).
        admin_events: evenements d'administration observes depuis la
            derniere verification.
        requester: deposant de la demande traitee par ce mint (I3 : le
            destinataire du mint doit etre le deposant, OPEN_ANSWERS §1).
            Fourni par l'appelant (`MintRequest.requester`), PAS retrouve via
            `request_id` (voir docstring du module).
    """

    deposit_amount: int | None = None
    rate: Fraction | None = None
    reference_rate: Fraction | None = None
    total_supply_before: int | None = None
    total_supply_after: int | None = None
    interval_minted_total: int | None = None
    interval_burned_total: int = 0
    collateral_value: int | None = None
    admin_events: tuple[AdminEvent, ...] = field(default_factory=tuple)
    requester: str | None = None
    # #104 : le mint observe (Transfer depuis 0x0 du token) n'a AUCUN
    # `SwapCompleted` du contrat protege dans sa transaction : il est passe par
    # un chemin non prevu (I4 viole, OPEN_ANSWERS §1). Renseigne par
    # `detection.provenance`, jamais devine.
    path_unexpected: bool = False

    def __post_init__(self) -> None:
        if self.requester is not None:
            _check_address("requester", self.requester)
        if self.deposit_amount is not None and self.deposit_amount <= 0:
            raise ValueError("deposit_amount doit etre > 0")
        for name in ("rate", "reference_rate"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} doit etre > 0")
        for name in (
            "total_supply_before",
            "total_supply_after",
            "interval_minted_total",
            "interval_burned_total",
            "collateral_value",
        ):
            _check_non_negative(name, getattr(self, name))
