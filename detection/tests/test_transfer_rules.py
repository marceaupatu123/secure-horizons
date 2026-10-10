"""Tests du surveillant de transferts (#12, OPEN_ANSWERS §9, OPEN_QUESTIONS §2).

Donnees fictives uniquement (adresses et montants synthetiques). Aucun appel
reseau / LLM. Les parametres sont les defauts PROVISOIRES de
`detection/params.py` (tranches de 5 min, 7 tranches du meme creneau, z >= 3).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from detection.detector import RuleBasedMonitor
from detection.params import TransferRuleParams
from shared.models import Alert, AlertKind, TransferEvent

UNIT = 10**6  # base units par token (fictif)
SUPPLY = 1_000_000_000 * UNIT  # offre en circulation fictive
ATTACK_TOTAL = 50_000_000 * UNIT
NORMAL_RECIPIENTS = 150
HISTORY_DAYS = 7
DAY0_SLOT = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def _address(n: int) -> str:
    return "0x" + f"{n:040x}"


POOL = [_address(i + 1) for i in range(1_000)]  # utilisateurs anciens
ATTACKER = _address(10_000)
RELAYS = [_address(10_001 + i) for i in range(3)]  # adresses neuves
BRIDGES = [_address(20_000 + i) for i in range(4)]  # points de sortie

_tx_counter = 0


def _transfer(sender: str, recipient: str, amount: int, at: datetime) -> TransferEvent:
    global _tx_counter
    _tx_counter += 1
    return TransferEvent(
        tx_hash="0x" + f"{_tx_counter:064x}",
        log_index=0,
        block_number=_tx_counter,
        chain_id=43113,
        observed_at=at,
        sender=sender,
        recipient=recipient,
        amount=amount,
        is_ghost=False,
    )


def _slot_start(day: int) -> datetime:
    return DAY0_SLOT + timedelta(days=day)


def _normal_traffic(
    rng: random.Random, day: int, recipients: int = NORMAL_RECIPIENTS
) -> list[TransferEvent]:
    """Trafic legitime large : `recipients` destinataires distincts anciens,
    montants 1 000 - 10 000 tokens, repartis sur la tranche de 5 min."""
    start = _slot_start(day)
    return [
        _transfer(
            rng.choice(POOL),
            recipient,
            rng.randint(1_000, 10_000) * UNIT,
            start + timedelta(seconds=rng.randrange(300)),
        )
        for recipient in rng.sample(POOL, recipients)
    ]


def _split(total: int, parts: int) -> list[int]:
    share, rest = divmod(total, parts)
    return [share] * (parts - 1) + [share + rest]


def _attack(day: int) -> list[TransferEvent]:
    """50M : attaquant -> 3 adresses neuves -> 4 bridges, en 2 min."""
    start = _slot_start(day) + timedelta(minutes=1)
    events: list[TransferEvent] = []
    relay_amounts = _split(ATTACK_TOTAL, len(RELAYS))
    for i, (relay, amount) in enumerate(zip(RELAYS, relay_amounts)):
        events.append(_transfer(ATTACKER, relay, amount, start + timedelta(seconds=10 * i)))
    for i, (relay, amount) in enumerate(zip(RELAYS, relay_amounts)):
        for j, (bridge, part) in enumerate(zip(BRIDGES, _split(amount, len(BRIDGES)))):
            at = start + timedelta(seconds=40 + 20 * i + 5 * j)
            events.append(_transfer(relay, bridge, part, at))
    assert max(e.observed_at for e in events) - start < timedelta(minutes=2)
    return events


def _monitor() -> RuleBasedMonitor:
    return RuleBasedMonitor(
        transfer_params=TransferRuleParams(exit_points=frozenset(BRIDGES)),
        circulating_supply=SUPPLY,
        known_addresses=POOL,
    )


def _feed(monitor: RuleBasedMonitor, events: list[TransferEvent]) -> list[Alert]:
    alerts = []
    for event in sorted(events, key=lambda e: e.observed_at):
        alert = monitor.check_transfer(event)
        if alert is not None:
            alerts.append(alert)
    return alerts


def _with_history(rng: random.Random, days: int = HISTORY_DAYS) -> RuleBasedMonitor:
    monitor = _monitor()
    for day in range(days):
        assert _feed(monitor, _normal_traffic(rng, day)) == []
    return monitor


def _close(monitor: RuleBasedMonitor, day: int) -> Alert | None:
    return monitor.close_slot_if_due(_slot_start(day) + timedelta(minutes=5))


def test_normal_user_bridging_5000_no_alert() -> None:
    rng = random.Random(12)
    monitor = _with_history(rng)
    day = HISTORY_DAYS
    events = _normal_traffic(rng, day)
    events.append(
        _transfer(POOL[0], BRIDGES[0], 5_000 * UNIT, _slot_start(day) + timedelta(minutes=2))
    )
    assert _feed(monitor, events) == []
    assert _close(monitor, day) is None
    stats = monitor.last_slot_stats
    assert stats is not None and stats.volume_zscore is not None


def test_attack_50m_three_new_addresses_four_bridges_alerts_with_seeds() -> None:
    rng = random.Random(12)
    monitor = _with_history(rng)
    day = HISTORY_DAYS
    # Rien avant la cloture de la tranche : l'alerte part a la fin des 5 min,
    # donc avant la fin de la fenetre Ghost normale (10 min).
    assert _feed(monitor, _normal_traffic(rng, day) + _attack(day)) == []
    alert = _close(monitor, day)

    assert alert is not None
    assert alert.kind is AlertKind.TRANSFER
    assert alert.monitor_name == "rule_transfer"
    assert "retarder" in alert.reason
    assert {s.address for s in alert.seeds} == set(BRIDGES)
    assert sum(s.suspect_amount for s in alert.seeds) == ATTACK_TOTAL
    assert alert.suspect_amount == ATTACK_TOTAL
    assert all(s.contamination_ratio == 1.0 for s in alert.seeds)
    assert alert.subject_address in BRIDGES
    assert alert.volume_zscore is not None and alert.volume_zscore >= 3.0

    stats = monitor.last_slot_stats
    assert stats is not None
    assert stats.herfindahl_zscore is not None and stats.herfindahl_zscore >= 3.0
    # Limite documentee : le nombre de destinataires distincts bouge a peine
    # (150 -> 157) alors que la dispersion effective s'effondre.
    assert stats.distinct_recipients == NORMAL_RECIPIENTS + len(RELAYS) + len(BRIDGES)
    assert alert.dispersion_score is not None and alert.dispersion_score < 10


def test_attack_alert_also_raised_by_next_slot_transfer() -> None:
    rng = random.Random(12)
    monitor = _with_history(rng)
    day = HISTORY_DAYS
    assert _feed(monitor, _normal_traffic(rng, day) + _attack(day)) == []
    late = _transfer(POOL[1], POOL[2], 1_000 * UNIT, _slot_start(day) + timedelta(minutes=6))
    alert = monitor.check_transfer(late)
    assert alert is not None
    assert {s.address for s in alert.seeds} == set(BRIDGES)


def test_legit_broad_growth_no_alert() -> None:
    rng = random.Random(12)
    monitor = _with_history(rng)
    day = HISTORY_DAYS
    # Volume x4 mais sur 4x plus de destinataires anciens : dispersion haute.
    assert _feed(monitor, _normal_traffic(rng, day, recipients=600)) == []
    assert _close(monitor, day) is None
    stats = monitor.last_slot_stats
    assert stats is not None
    assert stats.volume_zscore is not None and stats.volume_zscore >= 3.0
    assert stats.herfindahl_zscore is not None and stats.herfindahl_zscore < 3.0


def test_insufficient_history_no_alert() -> None:
    """Moins de `min_history_slots` (5, PROVISOIRE) tranches du meme creneau :
    la tranche nourrit la baseline mais n'alerte jamais, meme sur l'attaque."""
    rng = random.Random(12)
    monitor = _with_history(rng, days=2)
    day = 2
    assert _feed(monitor, _normal_traffic(rng, day) + _attack(day)) == []
    assert _close(monitor, day) is None
    stats = monitor.last_slot_stats
    assert stats is not None
    assert stats.history_size == 2
    assert stats.volume_zscore is None and stats.herfindahl_zscore is None


def test_no_circulating_supply_no_alert() -> None:
    rng = random.Random(12)
    monitor = RuleBasedMonitor(known_addresses=POOL)
    for day in range(HISTORY_DAYS):
        _feed(monitor, _normal_traffic(rng, day))
    day = HISTORY_DAYS
    assert _feed(monitor, _normal_traffic(rng, day) + _attack(day)) == []
    assert _close(monitor, day) is None
    assert monitor.last_slot_stats is None
