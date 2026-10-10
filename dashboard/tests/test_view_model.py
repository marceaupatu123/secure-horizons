"""Tests de la couche logique du dashboard (sans Streamlit)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dashboard.demo_data import DEMO_EXTENDED_WINDOW, generate_demo_dataset
from dashboard.view_model import (
    ACTION_COLUMNS,
    ALERT_COLUMNS,
    AUDIT_COLUMNS,
    PERIMETER_COLUMNS,
    PERIMETER_STATE_LABELS,
    SEVERITY_LABELS,
    THOUSANDS_SEPARATOR,
    PerimeterState,
    actions_to_frame,
    alerts_to_frame,
    audit_log_to_frame,
    compute_summary,
    derive_perimeter_states,
    filter_alerts,
    format_base_units,
    known_perimeters,
    perimeters_to_frame,
    short_address,
)
from shared.models import (
    Alert,
    AlertKind,
    AlertSeverity,
    QuarantineStatus,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


def _alert(address: str = ADDR_A, severity: AlertSeverity = AlertSeverity.CRITICAL,
           kind: AlertKind = AlertKind.TRANSFER, minutes: int = 0) -> Alert:
    return Alert(alert_id=f"alert-{address[-1]}-{minutes}", kind=kind, severity=severity,
                 created_at=T0 + timedelta(minutes=minutes), monitor_name="test",
                 subject_address=address, contamination_ratio=0.5, suspect_amount=10,
                 reason="test")


def _action(action_type: ResponseActionType, status: ResponseActionStatus,
            address: str | None = ADDR_A, minutes: int = 0,
            expires_in: int | None = None) -> ResponseAction:
    created = T0 + timedelta(minutes=minutes)
    return ResponseAction(
        action_id=f"action-{action_type.value}-{minutes}", action_type=action_type,
        status=status, created_at=created,
        expires_at=None if expires_in is None else created + timedelta(minutes=expires_in),
        perimeter_address=address,
    )


DELAY, DESTROY, PAUSE = (ResponseActionType.DELAY, ResponseActionType.DESTROY,
                         ResponseActionType.GLOBAL_PAUSE)
APPLIED, EXPIRED, PROPOSED = (ResponseActionStatus.APPLIED, ResponseActionStatus.EXPIRED,
                              ResponseActionStatus.PROPOSED)


def test_active_delay_is_delayed() -> None:
    states = derive_perimeter_states([], [_action(DELAY, APPLIED, expires_in=60)], T0)
    assert states == {ADDR_A: PerimeterState.DELAYED}


def test_delay_past_expiry_is_normal() -> None:
    states = derive_perimeter_states([], [_action(DELAY, APPLIED, expires_in=60)],
                                     T0 + timedelta(minutes=60))
    assert states[ADDR_A] == PerimeterState.NORMAL


def test_expired_delay_is_normal() -> None:
    states = derive_perimeter_states([], [_action(DELAY, EXPIRED, expires_in=60)], T0)
    assert states[ADDR_A] == PerimeterState.NORMAL


def test_applied_destroy_is_destroyed() -> None:
    states = derive_perimeter_states([], [_action(DESTROY, APPLIED)], T0)
    assert states[ADDR_A] == PerimeterState.DESTROYED


def test_proposed_global_pause_has_no_effect() -> None:
    actions = [_action(DELAY, APPLIED, expires_in=60), _action(PAUSE, PROPOSED, None, 1)]
    states = derive_perimeter_states([_alert(ADDR_B)], actions, T0 + timedelta(minutes=2))
    assert states == {ADDR_A: PerimeterState.DELAYED, ADDR_B: PerimeterState.NORMAL}


def test_applied_global_pause_affects_all() -> None:
    actions = [_action(DELAY, APPLIED, expires_in=60), _action(PAUSE, APPLIED, None, 1)]
    states = derive_perimeter_states([_alert(ADDR_B)], actions, T0 + timedelta(minutes=2))
    assert set(states.values()) == {PerimeterState.GLOBAL_PAUSE}
    assert set(states) == {ADDR_A, ADDR_B}


def test_action_created_after_at_is_ignored() -> None:
    states = derive_perimeter_states([], [_action(DESTROY, APPLIED, minutes=5)], T0)
    assert states[ADDR_A] == PerimeterState.NORMAL


def test_destroy_has_priority_over_delay() -> None:
    actions = [_action(DESTROY, APPLIED), _action(DELAY, APPLIED, minutes=1, expires_in=60)]
    states = derive_perimeter_states([], actions, T0 + timedelta(minutes=2))
    assert states[ADDR_A] == PerimeterState.DESTROYED


def test_address_only_in_alert_is_normal() -> None:
    assert derive_perimeter_states([_alert(ADDR_B)], [], T0) == {ADDR_B: PerimeterState.NORMAL}


def test_compute_summary_matches_independent_recount() -> None:
    d = generate_demo_dataset()
    at = d.reference_time
    s = compute_summary(d, at)
    for severity in AlertSeverity:
        expected = len([a for a in d.alerts if a.severity == severity and a.created_at <= at])
        assert s.alert_count_by_severity[severity.value] == expected
    assert sum(s.perimeter_count_by_state.values()) == len(known_perimeters(d.alerts, d.actions))
    active = [q for q in d.quarantine
              if q.status in {QuarantineStatus.ACTIVE, QuarantineStatus.EXTENDED}]
    assert s.active_quarantine_ghost_balance == sum(q.ghost_balance for q in active)
    assert s.active_suspect_amount == sum(q.suspect_amount for q in active)
    assert s.burned_ghost_total == sum(b.burned_amount for b in d.ghost_burns)
    assert s.redeemed_ghost_total == sum(r.ghost_amount for r in d.ghost_redemptions)
    assert s.pending_multisig_actions == len(
        [a for a in d.actions
         if a.action_type in {DESTROY, PAUSE} and a.status == PROPOSED]
    )


def test_demo_delayed_perimeter_returns_to_normal() -> None:
    d = generate_demo_dataset()
    before = derive_perimeter_states(d.alerts, d.actions, d.reference_time)
    delayed = [addr for addr, st in before.items() if st == PerimeterState.DELAYED]
    assert delayed
    later = d.reference_time + DEMO_EXTENDED_WINDOW + timedelta(minutes=1)
    after = derive_perimeter_states(d.alerts, d.actions, later)
    assert all(after[addr] == PerimeterState.NORMAL for addr in delayed)


def test_frames_columns_order_and_labels() -> None:
    d = generate_demo_dataset()
    at = d.reference_time
    alerts = alerts_to_frame(d.alerts)
    assert list(alerts.columns) == ALERT_COLUMNS
    assert list(alerts["Créée le"]) == sorted(alerts["Créée le"], reverse=True)
    assert set(alerts["Gravité"]) <= set(SEVERITY_LABELS.values())

    states = derive_perimeter_states(d.alerts, d.actions, at)
    perimeters = perimeters_to_frame(states, d.quarantine, d.beacons)
    assert list(perimeters.columns) == PERIMETER_COLUMNS
    assert len(perimeters) == len(states)
    assert set(perimeters["État"]) <= set(PERIMETER_STATE_LABELS.values())

    assert list(actions_to_frame(d.actions, at).columns) == ACTION_COLUMNS
    audit = audit_log_to_frame(d.audit_log)
    assert list(audit.columns) == AUDIT_COLUMNS
    assert list(audit["Horodatage"]) == sorted(audit["Horodatage"])


def test_filter_alerts() -> None:
    alerts = [_alert(severity=AlertSeverity.INFO, kind=AlertKind.MINT),
              _alert(ADDR_B, AlertSeverity.CRITICAL, AlertKind.TRANSFER)]
    kept = filter_alerts(alerts, {AlertSeverity.CRITICAL}, set(AlertKind))
    assert [a.subject_address for a in kept] == [ADDR_B]
    assert filter_alerts(alerts, set(AlertSeverity), {AlertKind.MINT}) == alerts[:1]


def test_formatting_helpers() -> None:
    assert format_base_units(1234567) == f"1{THOUSANDS_SEPARATOR}234{THOUSANDS_SEPARATOR}567"
    assert format_base_units(12) == "12"
    assert short_address("0x1234" + "0" * 30 + "abcd") == "0x1234…abcd"
