"""Tests du branchement monitor -> detection (issue #86).

Donnees fictives uniquement, aucun appel reseau (faux flux du monitor, JSONL
ecrits dans `tmp_path`), aucun LLM.
"""

from __future__ import annotations

import io
import json
import logging
import random
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from detection.detector import RuleBasedMonitor
from detection.params import (
    DEMO_BASELINE_PERIOD_SECONDS,
    DEMO_MIN_HISTORY_SLOTS,
    ENV_DETECTION_PROFILE,
    PROFILE_DEFAULT,
    PROFILE_DEMO,
    SLOT_SECONDS,
    TRANSFER_PROFILES,
    TransferRuleParams,
    resolve_profile,
    transfer_params_for_profile,
)
from detection.pipeline import (
    DetectionPipeline,
    main,
    parse_replay_line,
    run_live,
    run_replay,
)
from monitor.config import MonitorConfig
from shared.models import Alert, MintEvent, MintRequest, TransferEvent

UNIT = 10**6
SUPPLY = 1_000_000 * UNIT
T0 = datetime(2026, 10, 10, tzinfo=timezone.utc)
HISTORY_SLOTS = DEMO_MIN_HISTORY_SLOTS
TOKEN = "0x" + "aa" * 20


def _address(n: int) -> str:
    return "0x" + f"{n:040x}"


POOL = [_address(i + 1) for i in range(60)]
ATTACKER = _address(10_000)
RELAYS = [_address(10_001 + i) for i in range(3)]
BRIDGES = [_address(20_000 + i) for i in range(4)]
ATTACK_TOTAL = 90_000 * UNIT

_counter = 0


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _slot_start(slot: int) -> datetime:
    return T0 + timedelta(seconds=SLOT_SECONDS * slot)


def _transfer(sender: str, recipient: str, amount: int, at: datetime) -> TransferEvent:
    n = _next()
    return TransferEvent(
        tx_hash="0x" + f"{n:064x}",
        log_index=0,
        block_number=n,
        chain_id=43113,
        observed_at=at,
        sender=sender,
        recipient=recipient,
        amount=amount,
        is_ghost=False,
    )


def _mint(recipient: str, amount: int, at: datetime) -> MintEvent:
    n = _next()
    return MintEvent(
        tx_hash="0x" + f"{n:064x}",
        log_index=0,
        block_number=n,
        chain_id=43113,
        observed_at=at,
        recipient=recipient,
        amount=amount,
        request_id=n,
    )


def _normal_slot(rng: random.Random, slot: int) -> list[TransferEvent]:
    """Trafic legitime disperse : 20 transferts entre adresses du pool."""
    start = _slot_start(slot)
    events = []
    for _ in range(20):
        sender, recipient = rng.sample(POOL, 2)
        at = start + timedelta(seconds=rng.randrange(SLOT_SECONDS))
        events.append(_transfer(sender, recipient, rng.randint(100, 1_000) * UNIT, at))
    return sorted(events, key=lambda e: e.observed_at)


def _attack(slot: int) -> list[TransferEvent]:
    """Attaquant neuf -> 3 relais neufs -> 4 bridges, en 2 min."""
    start = _slot_start(slot) + timedelta(seconds=30)
    share = ATTACK_TOTAL // len(RELAYS)
    events = [
        _transfer(ATTACKER, relay, share, start + timedelta(seconds=5 * i))
        for i, relay in enumerate(RELAYS)
    ]
    for i, relay in enumerate(RELAYS):
        for j, bridge in enumerate(BRIDGES):
            at = start + timedelta(seconds=30 + 10 * i + 2 * j)
            events.append(_transfer(relay, bridge, share // len(BRIDGES), at))
    return events


def _history(rng: random.Random, slots: int = HISTORY_SLOTS) -> list[TransferEvent]:
    return [e for slot in range(slots) for e in _normal_slot(rng, slot)]


def _demo_pipeline(
    emitted: list[Alert], supply: int | None = SUPPLY
) -> DetectionPipeline:
    monitor = RuleBasedMonitor(
        transfer_params=transfer_params_for_profile(PROFILE_DEMO, BRIDGES),
        circulating_supply=supply,
    )
    return DetectionPipeline(monitor, emitted.append)


def _write_jsonl(path: Path, events: list[Any]) -> Path:
    path.write_text(
        "".join(e.model_dump_json() + "\n" for e in events), encoding="utf-8"
    )
    return path


# --- Profils (DEMO vs defaut) ---


def test_profile_resolution_cli_then_env_then_default() -> None:
    assert resolve_profile(None, env={}) == PROFILE_DEFAULT
    assert resolve_profile(None, env={ENV_DETECTION_PROFILE: "DEMO"}) == PROFILE_DEMO
    assert (
        resolve_profile(PROFILE_DEFAULT, env={ENV_DETECTION_PROFILE: "demo"})
        == PROFILE_DEFAULT
    )
    with pytest.raises(ValueError, match="inconnu"):
        resolve_profile("prod", env={})


def test_default_profile_unchanged_and_demo_warms_up_faster() -> None:
    default = TRANSFER_PROFILES[PROFILE_DEFAULT]
    demo = TRANSFER_PROFILES[PROFILE_DEMO]
    assert default == TransferRuleParams()
    assert demo.baseline_period_seconds == DEMO_BASELINE_PERIOD_SECONDS
    assert demo.min_history_slots == DEMO_MIN_HISTORY_SLOTS
    warm_up = lambda p: p.min_history_slots * p.baseline_period_seconds  # noqa: E731
    assert warm_up(demo) < warm_up(default)
    # Seuils non touches par le profil DEMO.
    assert demo.volume_z_threshold == default.volume_z_threshold
    assert demo.hhi_z_threshold == default.hhi_z_threshold


def test_profile_params_add_exit_points() -> None:
    params = transfer_params_for_profile(PROFILE_DEMO, BRIDGES)
    assert params.exit_points == frozenset(BRIDGES)
    assert params.min_history_slots == DEMO_MIN_HISTORY_SLOTS
    assert transfer_params_for_profile(PROFILE_DEMO) is TRANSFER_PROFILES[PROFILE_DEMO]


def test_main_uses_profile_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rng = random.Random(7)
    path = _write_jsonl(tmp_path / "attack.jsonl", _history(rng) + _attack(HISTORY_SLOTS))
    argv = ["--replay", str(path), "--initial-supply", str(SUPPLY)]
    for bridge in BRIDGES:
        argv += ["--exit-point", bridge]

    monkeypatch.setenv(ENV_DETECTION_PROFILE, PROFILE_DEMO)
    demo_out = io.StringIO()
    assert main(argv, out=demo_out) == 0
    monkeypatch.setenv(ENV_DETECTION_PROFILE, PROFILE_DEFAULT)
    default_out = io.StringIO()
    assert main(argv, out=default_out) == 0

    assert len(demo_out.getvalue().splitlines()) == 1
    # Profil par defaut : 5 jours d'historique du meme creneau requis.
    assert default_out.getvalue() == ""


# --- REPLAY : JSONL synthetique de bout en bout ---


def test_replay_normal_no_alert_attack_alert_with_seeds(tmp_path: Path) -> None:
    rng = random.Random(7)
    history = _history(rng)
    tail = _normal_slot(rng, HISTORY_SLOTS)
    request = MintRequest(
        request_id=1,
        requester=POOL[0],
        deposit_token="0x" + "d0" * 20,
        deposit_amount=10 * UNIT,
        created_at=T0,
        chain_id=43113,
        signature="0x" + "ab" * 65,
    )
    normal = _write_jsonl(tmp_path / "normal.jsonl", [request, *history, *tail])
    attack = _write_jsonl(tmp_path / "attack.jsonl", history + _attack(HISTORY_SLOTS))
    common = ["--profile", "demo", "--initial-supply", str(SUPPLY)]
    for bridge in BRIDGES:
        common += ["--exit-point", bridge]

    normal_out = io.StringIO()
    assert main(["--replay", str(normal), *common], out=normal_out) == 0
    assert normal_out.getvalue() == ""

    attack_out = io.StringIO()
    assert main(["--replay", str(attack), *common], out=attack_out) == 0
    lines = attack_out.getvalue().splitlines()
    # L'attaque est en fin de fichier : seule la cloture de fin de replay
    # (horloge) peut la faire remonter.
    assert len(lines) == 1
    alert = Alert.model_validate(json.loads(lines[0]))
    assert alert.kind.value == "transfer"
    assert {s.address for s in alert.seeds} == set(BRIDGES)
    assert sum(s.suspect_amount for s in alert.seeds) == ATTACK_TOTAL // 3 // 4 * 12
    assert lines[0].isascii()


def test_replay_supply_from_mints_evaluated_before_counting_next_mint() -> None:
    emitted: list[Alert] = []
    pipeline = _demo_pipeline(emitted, supply=None)
    lines = [
        _mint(POOL[0], 500 * UNIT, _slot_start(0)).model_dump_json(),
        _transfer(POOL[0], POOL[1], 10 * UNIT, _slot_start(0)).model_dump_json(),
        _mint(POOL[2], 700 * UNIT, _slot_start(1)).model_dump_json(),
    ]
    summary = run_replay(lines, pipeline, initial_supply=0)

    stats = pipeline.monitor.last_slot_stats
    assert stats is not None and stats.slot_start == _slot_start(0)
    assert stats.circulating_supply == 500 * UNIT
    assert summary.mints == 2 and summary.transfers == 1
    assert summary.final_supply == 1_200 * UNIT


def test_parse_replay_line_ignores_other_models_and_rejects_bad_json() -> None:
    assert parse_replay_line('{"foo": 1}') is None
    with pytest.raises(ValueError, match="ligne 2"):
        run_replay(['{"foo": 1}', "not json"], _demo_pipeline([]))


# --- LIVE : faux flux du monitor ---


class FakeListener:
    """Faux `ChainListener` : lots scriptes + offre totale fixe."""

    def __init__(self, batches: list[list[Any]], supply: int, log: list[str]) -> None:
        self._batches = batches
        self._supply = supply
        self._log = log

    def stream_event_batches(self, max_polls: int | None = None) -> Iterator[list[Any]]:
        for batch in self._batches[:max_polls]:
            self._log.append(f"batch:{len(batch)}")
            yield batch

    def read_total_supply(self) -> int:
        self._log.append("supply")
        return self._supply


class SpyMonitor:
    """Surveillant espion : enregistre l'ordre des appels du pipeline."""

    transfer_params = TransferRuleParams()

    def __init__(self, log: list[str]) -> None:
        self._log = log

    def update_circulating_supply(self, supply: int) -> None:
        self._log.append(f"update:{supply}")

    def close_slot_if_due(self, now: datetime) -> Alert | None:
        self._log.append("tick")
        return None

    def check_mint(self, event: MintEvent, context: Any = None) -> Alert | None:
        self._log.append(f"mint:{event.amount}")
        return None

    def check_transfer(self, event: TransferEvent) -> Alert | None:
        self._log.append(f"transfer:{event.amount}")
        return None


def test_live_wiring_feeds_monitor_from_fake_streams() -> None:
    log: list[str] = []
    batches = [
        [_mint(POOL[0], 5, T0), _transfer(POOL[0], POOL[1], 3, T0)],
        [],
    ]
    pipeline = DetectionPipeline(SpyMonitor(log), lambda a: None)  # type: ignore[arg-type]
    listener = FakeListener(batches, supply=SUPPLY, log=log)

    code = run_live(
        pipeline,
        MonitorConfig(rpc_url=None, token_address=TOKEN),
        listener,  # type: ignore[arg-type]
        max_polls=2,
        now=lambda: T0,
    )

    assert code == 0
    assert log == [
        "batch:2",
        "supply",
        f"update:{SUPPLY}",
        "tick",
        "mint:5",
        "tick",
        "transfer:3",
        "tick",
        "batch:0",
        "supply",
        f"update:{SUPPLY}",
        "tick",
    ]


def test_live_closes_slot_on_clock_without_new_transfer() -> None:
    rng = random.Random(7)
    emitted: list[Alert] = []
    pipeline = _demo_pipeline(emitted)
    for event in _history(rng):
        pipeline.process(event)
    attack_slot = HISTORY_SLOTS
    clock = iter(
        [
            _slot_start(attack_slot) + timedelta(minutes=3),
            _slot_start(attack_slot + 1) + timedelta(seconds=1),
        ]
    )
    log: list[str] = []
    listener = FakeListener([_attack(attack_slot), []], supply=SUPPLY, log=log)

    run_live(
        pipeline,
        MonitorConfig(rpc_url=None, token_address=TOKEN),
        listener,  # type: ignore[arg-type]
        max_polls=2,
        now=lambda: next(clock),
    )

    # Le 2e poll n'apporte aucun transfert : c'est l'horloge qui cloture.
    assert log == ["batch:15", "supply", "batch:0", "supply"]
    assert len(emitted) == 1
    assert {s.address for s in emitted[0].seeds} == set(BRIDGES)


def test_live_without_token_exits_cleanly(caplog: pytest.LogCaptureFixture) -> None:
    # On capture sur le logger emetteur (detection.pipeline) et on force sa
    # propagation : un autre test de la suite peut couper la propagation ou relever
    # le niveau du logger `detection.*` (cf. conformal_eval), ce qui laissait
    # caplog vide quand on capturait seulement sur le root logger -> echec non
    # deterministe selon l'ordre d'execution.
    pipeline_logger = logging.getLogger("detection.pipeline")
    pipeline_logger.propagate = True
    caplog.set_level(logging.WARNING, logger="detection.pipeline")
    pipeline = _demo_pipeline([])
    code = run_live(pipeline, MonitorConfig(rpc_url=None, token_address=None))
    assert code == 0
    assert "MONITOR_TOKEN_ADDRESS" in caplog.text
    assert "FUJI_RPC_URL" in caplog.text


def test_main_without_args_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONITOR_TOKEN_ADDRESS", raising=False)
    monkeypatch.delenv(ENV_DETECTION_PROFILE, raising=False)
    out = io.StringIO()
    assert main([], out=out) == 0
    assert out.getvalue() == ""


# --- Tranches sautees : WARNING explicite ---


def test_skipped_slot_warns_when_supply_unknown(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="detection.detector")
    pipeline = _demo_pipeline([], supply=None)
    pipeline.process(_transfer(POOL[0], POOL[1], 10 * UNIT, _slot_start(0)))
    assert pipeline.tick(_slot_start(1)) == []
    assert "offre en circulation inconnue" in caplog.text
    assert "2026-10-10 00:00" in caplog.text


def test_skipped_slot_warns_when_history_insufficient(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="detection.detector")
    pipeline = _demo_pipeline([])
    pipeline.process(_transfer(POOL[0], POOL[1], 10 * UNIT, _slot_start(0)))
    pipeline.tick(_slot_start(1))
    assert f"historique insuffisant (0/{DEMO_MIN_HISTORY_SLOTS}" in caplog.text


def test_mint_without_context_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="detection.pipeline")
    pipeline = _demo_pipeline([])
    pipeline.process(_mint(POOL[0], 5, T0))
    pipeline.process(_mint(POOL[0], 6, T0))
    assert caplog.text.count("aucun MintContext") == 1
