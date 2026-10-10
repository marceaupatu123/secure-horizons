"""Tests du generateur de donnees synthetiques du dashboard."""

from __future__ import annotations

from dashboard.demo_data import DemoDataset, generate_demo_dataset
from shared.models import ReleaseVerdict, ResponseActionStatus, ResponseActionType


def test_deterministic_for_same_seed() -> None:
    assert generate_demo_dataset(20).model_dump() == generate_demo_dataset(20).model_dump()


def test_different_seeds_give_different_addresses() -> None:
    a = {x.subject_address for x in generate_demo_dataset(1).alerts}
    b = {x.subject_address for x in generate_demo_dataset(2).alerts}
    assert a != b


def test_dataset_revalidates() -> None:
    d = generate_demo_dataset()
    assert DemoDataset.model_validate(d.model_dump()) == d


def test_referential_integrity() -> None:
    d = generate_demo_dataset()
    alert_ids = {a.alert_id for a in d.alerts}
    decisions = {x.decision_id: x for x in d.decisions}
    for action in d.actions:
        if action.triggering_alert_id is not None:
            assert action.triggering_alert_id in alert_ids
        if (action.action_type in {ResponseActionType.DESTROY, ResponseActionType.GLOBAL_PAUSE}
                and action.status == ResponseActionStatus.APPLIED):
            assert action.decision_id in decisions
        if action.action_type == ResponseActionType.DELAY:
            assert action.expires_at is not None
    for burn in d.ghost_burns:
        assert decisions[burn.decision_id].verdict == ReleaseVerdict.CONFIRM_DESTROY


def test_each_action_type_present_and_audited() -> None:
    d = generate_demo_dataset()
    assert {a.action_type for a in d.actions} == set(ResponseActionType)
    audited = {e.related_action_id for e in d.audit_log}
    for action in d.actions:
        assert action.action_id in audited


def test_audit_log_sorted_and_timezone_aware() -> None:
    d = generate_demo_dataset()
    times = [e.recorded_at for e in d.audit_log]
    assert times == sorted(times)
    all_times = (
        times
        + [a.created_at for a in d.alerts]
        + [a.created_at for a in d.actions]
        + [a.expires_at for a in d.actions if a.expires_at is not None]
        + [q.window_expires_at for q in d.quarantine]
    )
    assert all(t.tzinfo is not None for t in all_times)
