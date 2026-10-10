"""#18 : gel et levee (veto asymetrique, multisig 2/3 et 3/3)."""

from __future__ import annotations

from datetime import timedelta

from response.orchestrator import PerimeterState, ResponseOrchestrator
from response.tests.conftest import (
    GUARDIANS,
    OUTSIDER,
    START,
    SUSPECT,
    FakeClock,
    make_alert,
    make_decision,
    make_freeze,
)
from shared.models import (
    FreezeDirection,
    ReleaseVerdict,
    ResponseActionStatus,
    ResponseActionType,
)

TWO = list(GUARDIANS[:2])
ALL = list(GUARDIANS)


# --- Surveillants : ralentir oui, accelerer non --------------------------------


def test_extend_creates_delay(orchestrator: ResponseOrchestrator) -> None:
    action = orchestrator.request_freeze(make_freeze(extend_minutes=30))

    assert action.status is ResponseActionStatus.APPLIED
    assert action.expires_at == START + timedelta(minutes=30)


def test_extend_never_shortens(orchestrator: ResponseOrchestrator) -> None:
    first = orchestrator.request_freeze(make_freeze(extend_minutes=50))
    again = orchestrator.request_freeze(make_freeze(extend_minutes=5, request_id="fr-2"))

    assert again.action_id == first.action_id
    assert again.expires_at == first.expires_at


def test_extend_lengthens_up_to_monitor_cap(
    make_orchestrator, clock: FakeClock  # type: ignore[no-untyped-def]
) -> None:
    orch = make_orchestrator(max_monitor_delay_minutes=90)
    orch.request_freeze(make_freeze(extend_minutes=60))
    clock.advance(40)
    longer = orch.request_freeze(make_freeze(extend_minutes=60, request_id="fr-2"))

    # Voulu : 40 + 60 = 100 min ; plafond : 90 min depuis le debut du retard.
    assert longer.status is ResponseActionStatus.APPLIED
    assert longer.expires_at == START + timedelta(minutes=90)


def test_extend_beyond_cap_is_only_proposed(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.request_freeze(make_freeze(extend_minutes=60))
    beyond = orchestrator.request_freeze(make_freeze(extend_minutes=120, request_id="fr-2"))

    assert beyond.status is ResponseActionStatus.PROPOSED
    assert orchestrator.active_delay(SUSPECT).expires_at == START + timedelta(minutes=60)  # type: ignore[union-attr]


def test_ai_confirm_request_is_only_a_proposal(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    proposal = orchestrator.request_freeze(
        make_freeze(FreezeDirection.CONFIRM, requested_by="llm", request_id="fr-ai")
    )

    assert proposal.action_type is ResponseActionType.DESTROY
    assert proposal.status is ResponseActionStatus.PROPOSED
    assert proposal.decision_id is None
    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.DELAYED


# --- Multisig : destruction 2/3 ------------------------------------------------


def test_destroy_with_two_of_three_applies_and_links_proposal(
    orchestrator: ResponseOrchestrator,
) -> None:
    orchestrator.handle_alert(make_alert())
    proposal = orchestrator.request_freeze(
        make_freeze(FreezeDirection.CONFIRM, requested_by="llm", request_id="fr-ai")
    )
    action = orchestrator.apply_release(
        make_decision(
            ReleaseVerdict.CONFIRM_DESTROY, TWO, burn_ratio=0.87, related_freeze_id="fr-ai"
        )
    )

    assert action.action_id == proposal.action_id
    assert action.action_type is ResponseActionType.DESTROY
    assert action.status is ResponseActionStatus.APPLIED
    assert action.decision_id == "rd-1"
    assert action.contamination_ratio == 0.87
    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.DESTROYED
    assert not orchestrator.is_conversion_suspended(SUSPECT)


def test_destroy_with_single_signer_is_rejected(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    action = orchestrator.apply_release(
        make_decision(ReleaseVerdict.CONFIRM_DESTROY, TWO[:1], burn_ratio=0.5)
    )

    assert action.status is ResponseActionStatus.REJECTED
    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.DELAYED


def test_non_guardian_signer_is_rejected(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    action = orchestrator.apply_release(
        make_decision(ReleaseVerdict.CONFIRM_DESTROY, [GUARDIANS[0], OUTSIDER], burn_ratio=0.5)
    )

    assert action.status is ResponseActionStatus.REJECTED


def test_duplicate_signer_does_not_count_twice(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    action = orchestrator.apply_release(
        make_decision(
            ReleaseVerdict.CONFIRM_DESTROY,
            [GUARDIANS[0], GUARDIANS[0].upper().replace("0X", "0x")],
            burn_ratio=0.5,
        )
    )

    assert action.status is ResponseActionStatus.REJECTED


def test_declared_threshold_above_quorum_is_enforced(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    action = orchestrator.apply_release(
        make_decision(ReleaseVerdict.CONFIRM_DESTROY, TWO, burn_ratio=0.5, threshold=3)
    )

    assert action.status is ResponseActionStatus.REJECTED


def test_destroy_requires_delayed_state(orchestrator: ResponseOrchestrator) -> None:
    action = orchestrator.apply_release(
        make_decision(ReleaseVerdict.CONFIRM_DESTROY, TWO, burn_ratio=0.5)
    )

    assert action.status is ResponseActionStatus.REJECTED
    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.NORMAL


def test_destroy_requires_burn_ratio(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    action = orchestrator.apply_release(make_decision(ReleaseVerdict.CONFIRM_DESTROY, TWO))

    assert action.status is ResponseActionStatus.REJECTED


def test_destroy_rejects_freeze_of_other_perimeter(orchestrator: ResponseOrchestrator) -> None:
    other = "0x4444444444444444444444444444444444444444"
    orchestrator.handle_alert(make_alert())
    orchestrator.request_freeze(
        make_freeze(FreezeDirection.CONFIRM, request_id="fr-other", perimeter=other)
    )
    action = orchestrator.apply_release(
        make_decision(
            ReleaseVerdict.CONFIRM_DESTROY, TWO, burn_ratio=0.5, related_freeze_id="fr-other"
        )
    )

    assert action.status is ResponseActionStatus.REJECTED


def test_destroy_after_expiry_is_too_late(
    orchestrator: ResponseOrchestrator, clock: FakeClock
) -> None:
    orchestrator.handle_alert(make_alert())
    clock.advance(61)
    action = orchestrator.apply_release(
        make_decision(ReleaseVerdict.CONFIRM_DESTROY, TWO, burn_ratio=0.5)
    )

    assert action.status is ResponseActionStatus.REJECTED


# --- Multisig : levee et confirmation d'un retard -------------------------------


def test_release_with_multisig_lifts_delay(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    action = orchestrator.apply_release(make_decision(ReleaseVerdict.RELEASE, TWO))

    assert action.action_type is ResponseActionType.DELAY
    assert action.status is ResponseActionStatus.EXPIRED
    assert action.decision_id == "rd-1"
    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.NORMAL


def test_single_actor_cannot_release(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.handle_alert(make_alert())
    action = orchestrator.apply_release(make_decision(ReleaseVerdict.RELEASE, TWO[:1]))

    assert action.status is ResponseActionStatus.REJECTED
    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.DELAYED


def test_release_without_delay_is_rejected(orchestrator: ResponseOrchestrator) -> None:
    action = orchestrator.apply_release(make_decision(ReleaseVerdict.RELEASE, TWO))

    assert action.status is ResponseActionStatus.REJECTED


def test_confirm_freeze_extends_beyond_monitor_cap(
    orchestrator: ResponseOrchestrator, clock: FakeClock
) -> None:
    orchestrator.handle_alert(make_alert())
    clock.advance(30)
    action = orchestrator.apply_release(make_decision(ReleaseVerdict.CONFIRM_FREEZE, TWO))

    assert action.status is ResponseActionStatus.APPLIED
    assert action.decision_id == "rd-1"
    assert action.expires_at == START + timedelta(minutes=90)


def test_confirmed_freeze_still_expires(
    orchestrator: ResponseOrchestrator, clock: FakeClock
) -> None:
    orchestrator.apply_release(make_decision(ReleaseVerdict.CONFIRM_FREEZE, TWO))
    clock.advance(60)

    assert orchestrator.perimeter_state(SUSPECT) is PerimeterState.NORMAL


def test_confirm_freeze_requires_perimeter(orchestrator: ResponseOrchestrator) -> None:
    action = orchestrator.apply_release(
        make_decision(ReleaseVerdict.CONFIRM_FREEZE, TWO, perimeter=None)
    )

    assert action.status is ResponseActionStatus.REJECTED


# --- Multisig : pause globale 3/3 -------------------------------------------------


def test_global_pause_requires_unanimity(orchestrator: ResponseOrchestrator) -> None:
    rejected = orchestrator.apply_release(
        make_decision(ReleaseVerdict.GLOBAL_PAUSE, TWO, perimeter=None)
    )
    assert rejected.status is ResponseActionStatus.REJECTED
    assert not orchestrator.global_pause_active

    applied = orchestrator.apply_release(
        make_decision(ReleaseVerdict.GLOBAL_PAUSE, ALL, perimeter=None, decision_id="rd-2")
    )
    assert applied.action_type is ResponseActionType.GLOBAL_PAUSE
    assert applied.status is ResponseActionStatus.APPLIED
    assert applied.perimeter_address is None
    assert orchestrator.global_pause_active
    assert orchestrator.is_conversion_suspended(SUSPECT)


def test_global_pause_is_idempotent(orchestrator: ResponseOrchestrator) -> None:
    first = orchestrator.apply_release(
        make_decision(ReleaseVerdict.GLOBAL_PAUSE, ALL, perimeter=None)
    )
    second = orchestrator.apply_release(
        make_decision(ReleaseVerdict.GLOBAL_PAUSE, ALL, perimeter=None, decision_id="rd-2")
    )

    assert second.action_id == first.action_id


def test_lifting_global_pause_needs_same_quorum(orchestrator: ResponseOrchestrator) -> None:
    orchestrator.apply_release(make_decision(ReleaseVerdict.GLOBAL_PAUSE, ALL, perimeter=None))

    rejected = orchestrator.apply_release(
        make_decision(ReleaseVerdict.RELEASE, TWO, perimeter=None, decision_id="rd-2")
    )
    assert rejected.status is ResponseActionStatus.REJECTED
    assert orchestrator.global_pause_active

    lifted = orchestrator.apply_release(
        make_decision(ReleaseVerdict.RELEASE, ALL, perimeter=None, decision_id="rd-3")
    )
    assert lifted.action_type is ResponseActionType.GLOBAL_PAUSE
    assert lifted.status is ResponseActionStatus.EXPIRED
    assert not orchestrator.global_pause_active


def test_global_pause_does_not_expire_by_itself(
    orchestrator: ResponseOrchestrator, clock: FakeClock
) -> None:
    orchestrator.apply_release(make_decision(ReleaseVerdict.GLOBAL_PAUSE, ALL, perimeter=None))
    clock.advance(10_000)

    assert orchestrator.global_pause_active
