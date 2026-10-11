"""Trafic synthetique : simulation hors chaîne, à remplacer par #24/#25 (générateurs data) et #2 (monitor).

Fonctions pures et deterministes (seul `rng` porte l'aleatoire) produisant des
`shared.models.TransferEvent` fictifs. Tout transfert emet du Ghost chez le
destinataire (OPEN_ANSWERS §0bis) : `is_ghost=True`.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from dashboard.demo_data import DEMO_CHAIN_ID, _fake_address, _fake_tx_hash
from dashboard.scenarios.config import SimulationParams
from shared.models import TransferEvent

# Convention ERC-20 : un mint est un transfert depuis l'adresse nulle.
MINT_SENDER = "0x" + "0" * 40
_BLOCK_BASE = 30_000_000
_SECONDS_PER_BLOCK = 2  # ordre de grandeur Fuji, sert seulement a numeroter les blocs


def _transfer(
    rng: random.Random, origin: datetime, at: datetime, sender: str, recipient: str, amount: int
) -> TransferEvent:
    return TransferEvent(
        tx_hash=_fake_tx_hash(rng),
        log_index=rng.randint(0, 3),
        block_number=_BLOCK_BASE + int((at - origin).total_seconds()) // _SECONDS_PER_BLOCK,
        chain_id=DEMO_CHAIN_ID,
        observed_at=at,
        sender=sender,
        recipient=recipient,
        amount=amount,
        is_ghost=True,
    )


def _bucket_time(rng: random.Random, start: datetime, index: int, params: SimulationParams) -> datetime:
    bucket_seconds = params.bucket_minutes * 60
    return start + timedelta(seconds=index * bucket_seconds + rng.randrange(bucket_seconds))


def legit_addresses(rng: random.Random, n: int) -> list[str]:
    """`n` adresses fictives distinctes."""
    addresses: list[str] = []
    while len(addresses) < n:
        address = _fake_address(rng)
        if address not in addresses:
            addresses.append(address)
    return addresses


def legit_traffic(
    rng: random.Random,
    addresses: list[str],
    start: datetime,
    buckets: int,
    params: SimulationParams,
    growth: float = 1.0,
) -> list[TransferEvent]:
    """Trafic legitime large : destinataires tires uniformement (dispersion haute).

    `growth` multiplie progressivement (geometriquement) le nombre de transferts
    par tranche, de x1 a la premiere tranche jusqu'a x`growth` a la derniere (N2).
    """
    transfers: list[TransferEvent] = []
    for index in range(buckets):
        factor = growth ** (index / max(1, buckets - 1))
        for _ in range(round(params.legit_transfers_per_bucket * factor)):
            sender, recipient = rng.sample(addresses, 2)
            amount = rng.randint(params.legit_amount_min, params.legit_amount_max)
            at = _bucket_time(rng, start, index, params)
            transfers.append(_transfer(rng, start, at, sender, recipient, amount))
    return sorted(transfers, key=lambda t: t.observed_at)


def attacker_transfers(
    rng: random.Random, attackers: list[str], start: datetime, params: SimulationParams
) -> list[TransferEvent]:
    """Mints de l'attaquant SOUS le plafond on-chain, concentres sur peu d'adresses neuves.

    La tranche k credite `attackers[k % len(attackers)]` : la dispersion s'effondre.
    """
    transfers: list[TransferEvent] = []
    for index in range(params.attack_buckets):
        recipient = attackers[index % len(attackers)]
        for _ in range(params.attack_transfers_per_bucket):
            at = _bucket_time(rng, start, index, params)
            transfers.append(
                _transfer(rng, start, at, MINT_SENDER, recipient, params.attack_amount_per_tx)
            )
    return sorted(transfers, key=lambda t: t.observed_at)


def consolidation_burst(
    rng: random.Random,
    sender_pool: list[str],
    sink: str,
    start: datetime,
    params: SimulationParams,
    amounts: list[int] | None = None,
) -> list[TransferEvent]:
    """Burst LEGITIME concentre vers une adresse ancienne (ex. consolidation de tresorerie, N3).

    Tout tombe dans la tranche qui commence a `start`. Montants tires dans `amounts`
    (ex. montants du trafic legitime du generateur `data/`) s'il est fourni, sinon
    uniformement dans [legit_amount_min, legit_amount_max].
    """
    senders = [address for address in sender_pool if address != sink]

    def amount() -> int:
        if amounts:
            return rng.choice(amounts)
        return rng.randint(params.legit_amount_min, params.legit_amount_max)

    transfers = [
        _transfer(rng, start, _bucket_time(rng, start, 0, params), rng.choice(senders), sink,
                  amount())
        for _ in range(params.consolidation_transfers)
    ]
    return sorted(transfers, key=lambda t: t.observed_at)
