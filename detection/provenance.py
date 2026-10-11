"""Traduction des faits du monitor (contrat protege #5) en entrees de detection (#104).

Le monitor (`monitor/protected.py`) rattache chaque mint a sa demande
(`MintProvenance`) et decode les evenements d'administration
(`AdminObservation`). Ce module les convertit en `MintContext` / `AdminEvent`,
SANS faire confiance au contrat surveille plus que necessaire :

- le montant et le destinataire du mint viennent du `Transfer` du token (verite
  du solde credite) ;
- le depot, le deposant et le taux viennent de `SwapRequested` (enregistre au
  depot, avant tout traitement) ; le surveillant recalcule donc lui-meme I1
  (minted = depot x taux) et I3 (destinataire = deposant).

Unites (`ProtectedMinter.quoteMint`) : `minted = depot x 1e12 x rate / 1e18`
(collateral 6 decimales -> stable 18 decimales, `rate` en WAD). Le taux du
`MintContext` est en base units mintees par base unit deposee, soit
`rate x 1e12 / 1e18`. Le contrat arrondit vers le bas : l'ecart d'arrondi
(< 1 base unit) est tres en dessous de la tolerance epsilon de I1.
"""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction

from detection.inputs import AdminEvent, AdminEventKind, MintContext
from monitor.protected import AdminObservation, MintCorrelator, MintProvenance
from shared.models import MintEvent

#: `ProtectedMinter.DECIMALS_SCALE` (10**(18 - 6)) et `RATE_PRECISION` (1e18).
DECIMALS_SCALE = 10**12
RATE_PRECISION = 10**18

_ADMIN_KINDS: dict[str, AdminEventKind] = {
    "role_granted": AdminEventKind.ROLE_GRANTED,
    "role_revoked": AdminEventKind.ROLE_REVOKED,
    "rate_changed": AdminEventKind.RATE_CHANGED,
}


def rate_from_wad(rate_wad: int) -> Fraction:
    """Taux WAD du contrat -> base units mintees par base unit deposee."""
    if rate_wad <= 0:
        raise ValueError("rate_wad doit etre > 0")
    return Fraction(rate_wad * DECIMALS_SCALE, RATE_PRECISION)


def mint_context_from_provenance(provenance: MintProvenance | None) -> MintContext:
    """`MintContext` d'un mint observe en mode contrat protege.

    Args:
        provenance: demande rattachee au mint ; `None` = aucun `SwapCompleted`
            dans la transaction (chemin de mint non prevu, I4).

    Returns:
        Le contexte : depot + taux (I1) et deposant (I3), ou
        `path_unexpected=True` si le mint n'a pas de provenance.
    """
    if provenance is None:
        return MintContext(path_unexpected=True)
    deposit = provenance.deposit_amount if provenance.deposit_amount > 0 else None
    rate = rate_from_wad(provenance.rate_wad) if provenance.rate_wad > 0 else None
    return MintContext(
        deposit_amount=deposit,
        rate=rate,
        requester=provenance.depositor,
    )


def admin_event_from_observation(observation: AdminObservation) -> AdminEvent:
    """`AdminObservation` du monitor -> `AdminEvent` du surveillant de mint."""
    return AdminEvent(
        kind=_ADMIN_KINDS[observation.kind],
        subject_address=observation.subject_address,
        tx_hash=observation.tx_hash,
    )


def correlator_context_provider(
    correlator: MintCorrelator,
) -> Callable[[MintEvent], MintContext | None]:
    """`MintContextProvider` du pipeline, adosse au correlateur du monitor.

    Un mint inconnu du correlateur (ex. lu hors du mode protege) donne `None`
    (aucune regle de mint verifiee, comme avant #104) ; un mint connu SANS
    provenance donne `path_unexpected=True`.
    """

    def provide(event: MintEvent) -> MintContext | None:
        if not correlator.is_tracked(event.tx_hash, event.log_index):
            return None
        return mint_context_from_provenance(
            correlator.provenance_for(event.tx_hash, event.log_index)
        )

    return provide
