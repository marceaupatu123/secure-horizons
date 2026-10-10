"""Tests du generateur de donnees synthetiques (#24, #59, decision §6)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from data.generate import (
    EXIT_POINT,
    GenerationParams,
    event_time,
    generate_normal,
    generate_scenario_a,
    generate_scenario_b,
    load_jsonl,
    main,
    parse_line,
    write_scenario,
)
from shared.models import MintEvent, MintRequest, TransferEvent

PARAMS = GenerationParams(seed=7, hours=3, users=50)


def _mints_by_request(events: list) -> dict[int, tuple[MintRequest, MintEvent]]:  # type: ignore[type-arg]
    requests = {e.request_id: e for e in events if isinstance(e, MintRequest)}
    return {
        e.request_id: (requests[e.request_id], e) for e in events if isinstance(e, MintEvent)
    }


# --- reproductibilite et format ---------------------------------------------------


def test_same_seed_same_output(tmp_path: Path) -> None:
    a, _ = write_scenario(generate_normal(PARAMS), tmp_path / "a")
    b, _ = write_scenario(generate_normal(PARAMS), tmp_path / "b")
    other = GenerationParams(seed=8, hours=3, users=50)
    c, _ = write_scenario(generate_normal(other), tmp_path / "c")

    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes() != c.read_bytes()


def test_jsonl_roundtrip_validates_against_shared_models(tmp_path: Path) -> None:
    scenario = generate_scenario_b(PARAMS)
    jsonl, manifest = write_scenario(scenario, tmp_path)

    assert load_jsonl(jsonl) == scenario.events
    assert json.loads(manifest.read_text())["file"] == jsonl.name


def test_parse_line_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError):
        parse_line('{"foo": 1}')


def test_events_are_chronological_with_consistent_blocks() -> None:
    events = generate_normal(PARAMS).events
    times = [event_time(e) for e in events]
    blocks = [e.block_number for e in events if not isinstance(e, MintRequest)]

    assert times == sorted(times)
    assert blocks == sorted(blocks)
    assert all(t.tzinfo is not None for t in times)


# --- trafic normal (#59) -------------------------------------------------------------


def test_normal_traffic_has_no_attack_and_respects_volet_1() -> None:
    scenario = generate_normal(PARAMS)
    pairs = _mints_by_request(scenario.events)

    assert scenario.manifest["attack"] is None
    assert pairs
    for request, mint in pairs.values():
        assert mint.amount == request.deposit_amount  # I1 (taux 1:1)
        assert mint.recipient == request.requester  # I3
        assert mint.observed_at >= request.created_at


def test_normal_traffic_is_dispersed_and_uses_ghost() -> None:
    transfers = [e for e in generate_normal(PARAMS).events if isinstance(e, TransferEvent)]

    assert len({t.recipient for t in transfers}) > PARAMS.users // 2
    assert {t.is_ghost for t in transfers} == {True, False}


def test_traffic_covers_every_slot() -> None:
    events = generate_normal(PARAMS).events
    slots = {int((event_time(e) - PARAMS.start) / timedelta(minutes=5)) for e in events}

    assert slots == set(range(int(PARAMS.hours * 60 / 5)))


# --- scenario A ----------------------------------------------------------------------


def test_scenario_a_inflated_vs_protected_on_same_background() -> None:
    variants = generate_scenario_a(PARAMS)
    vuln, prot = variants["vulnerable"], variants["protected"]
    va, pa = vuln.manifest["attack"], prot.manifest["attack"]

    assert va["minted_total"] == va["deposit_total"] * PARAMS.attack_inflation
    assert pa["minted_total"] == pa["deposit_total"]
    assert len(va["request_ids"]) == 2

    def background(s):  # type: ignore[no-untyped-def]
        attack = set(s.manifest["attack"]["tx_hashes"])
        ids = set(s.manifest["attack"]["request_ids"])
        return [
            e.model_dump()
            for e in s.events
            if getattr(e, "tx_hash", None) not in attack and getattr(e, "request_id", None) not in ids
        ]

    assert background(vuln) == background(prot)


def test_scenario_a_attack_mint_goes_to_depositor() -> None:
    scenario = generate_scenario_a(PARAMS)["vulnerable"]
    attack = scenario.manifest["attack"]
    pairs = _mints_by_request(scenario.events)

    for request_id in attack["request_ids"]:
        request, mint = pairs[request_id]
        assert request.requester == mint.recipient == attack["attacker"]
        assert mint.amount == request.deposit_amount * PARAMS.attack_inflation


# --- scenario B ----------------------------------------------------------------------


def test_scenario_b_hijacks_recipient_at_one_to_one() -> None:
    scenario = generate_scenario_b(PARAMS)
    attack = scenario.manifest["attack"]
    (request_id,) = attack["request_ids"]
    request, mint = _mints_by_request(scenario.events)[request_id]

    assert request.requester == attack["victim"]
    assert mint.recipient == attack["attacker"] != attack["victim"]
    assert mint.amount == request.deposit_amount  # I1 respecte : bilan global 1:1


def test_scenario_b_exit_is_concentrated_fresh_and_before_conversion() -> None:
    scenario = generate_scenario_b(PARAMS)
    attack = scenario.manifest["attack"]
    attack_txs = set(attack["tx_hashes"])
    outflow = [e for e in scenario.events if isinstance(e, TransferEvent) and e.tx_hash in attack_txs]
    legit = {
        address
        for e in scenario.events
        if isinstance(e, TransferEvent) and e.tx_hash not in attack_txs
        for address in (e.sender, e.recipient)
    }
    fresh = {attack["attacker"], *attack["fresh_addresses"]}
    (request_id,) = attack["request_ids"]
    t0 = _mints_by_request(scenario.events)[request_id][0].created_at
    window = timedelta(minutes=PARAMS.ghost_window_minutes)

    assert len(outflow) == 2 * PARAMS.exit_hops
    assert fresh.isdisjoint(legit)  # adresses neuves, jamais vues dans le trafic legitime
    assert all(t.is_ghost for t in outflow)
    assert all(t.observed_at - t0 < window for t in outflow)  # tout se passe avant conversion
    assert sum(t.amount for t in outflow if t.recipient == EXIT_POINT) == attack["deposit_total"]


# --- parametres et CLI ----------------------------------------------------------------


def test_params_validation() -> None:
    with pytest.raises(ValueError):
        GenerationParams(users=1)
    with pytest.raises(ValueError):
        GenerationParams(attack_at_fraction=1.0)
    with pytest.raises(ValueError):
        GenerationParams(start=PARAMS.start.replace(tzinfo=None))


def test_cli_writes_all_files(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    main(["--scenario", "all", "--hours", "1", "--users", "20", "--out-dir", str(tmp_path)])

    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(
        f"{base}{ext}"
        for base in ("normal", "scenario_a_vulnerable", "scenario_a_protected", "scenario_b")
        for ext in (".jsonl", ".manifest.json")
    )
    assert "evenements" in capsys.readouterr().out
