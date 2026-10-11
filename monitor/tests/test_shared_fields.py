"""#104 : le monitor remplit les champs partages de `shared/` (#135).

- `MintEvent` : demande rattachee (`via_protected_path`, deposant, depot, taux,
  source, montant annonce) en mode contrat protege ;
- `AdminObservation` -> `shared.models.AdminEvent` (champs types).

Logs synthetiques de `monitor.tests.test_protected`. Donnees FICTIVES.
"""

from __future__ import annotations

import pytest

from monitor.config import MonitorConfig
from monitor.listener import ChainListener
from monitor.protected import (
    RATE_CHANGED_TOPIC,
    AdminObservation,
    admin_event_from_observation,
    decode_admin,
    event_topic,
    with_provenance,
)
from monitor.tests.test_protected import (
    ALICE,
    ATTACKER,
    BOB,
    FIXED_NOW,
    MINTER,
    TOKEN,
    WAD,
    ZERO,
    FakeEth,
    FakeWeb3,
    _addr_topic,
    _data,
    _listener,
    _log,
    role_granted,
    swap_completed,
    swap_requested,
    transfer,
)
from shared.models import AdminEventKind, MintEvent, MintProvenanceSource

SERVICE_ROLE = event_topic("SERVICE_ROLE")


def _mints(logs: list[dict]) -> list[MintEvent]:  # type: ignore[type-arg]
    listener, _ = _listener(logs)
    return [e for e in listener.fetch_events(0, 100) if isinstance(e, MintEvent)]


# ------------------------------------------------------------ MintEvent


def test_mint_rattache_porte_la_demande_complete() -> None:
    logs = [
        swap_requested(0, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        transfer(ZERO, ALICE, 10**18, block=11, index=0, tx=2),
        swap_completed(0, ALICE, ALICE, 1_000_000, 10**18, WAD, block=11, index=1, tx=2),
    ]
    (mint,) = _mints(logs)
    assert mint.via_protected_path is True
    assert mint.request_id == 0
    assert mint.depositor is not None and mint.depositor.lower() == ALICE
    assert mint.deposit_amount == 1_000_000
    assert mint.rate_wad == WAD
    assert mint.provenance_source is MintProvenanceSource.REQUEST
    assert mint.claimed_minted == 10**18
    # La verite du solde credite reste le log du token.
    assert mint.recipient.lower() == ALICE and mint.amount == 10**18


def test_depot_enregistre_prime_sur_ce_que_le_contrat_annonce() -> None:
    """Le contrat ment dans SwapCompleted : le MintEvent garde le depot de SwapRequested."""
    logs = [
        swap_requested(3, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        transfer(ZERO, ATTACKER, 400 * 10**18, block=11, index=0, tx=2),
        swap_completed(3, ALICE, ATTACKER, 400_000_000, 400 * 10**18, WAD, block=11, index=1, tx=2),
    ]
    (mint,) = _mints(logs)
    assert mint.deposit_amount == 1_000_000
    assert mint.depositor is not None and mint.depositor.lower() == ALICE
    assert mint.recipient.lower() == ATTACKER  # I3 visible dans le seul MintEvent
    assert mint.claimed_minted == 400 * 10**18


def test_mint_sans_swapcompleted_est_marque_hors_chemin() -> None:
    (mint,) = _mints([transfer(ZERO, ATTACKER, 10**24, block=11, index=0, tx=9)])
    assert mint.via_protected_path is False
    assert mint.request_id is None
    assert mint.provenance_source is None and mint.depositor is None


def test_demande_anterieure_a_l_ecoute_marquee_completion() -> None:
    logs = [
        transfer(ZERO, ALICE, 10**18, block=11, index=0, tx=2),
        swap_completed(5, ALICE, ALICE, 1_000_000, 10**18, WAD, block=11, index=1, tx=2),
    ]
    (mint,) = _mints(logs)
    assert mint.via_protected_path is True
    assert mint.provenance_source is MintProvenanceSource.COMPLETION
    assert mint.request_id == 5


def test_mode_generique_ne_renseigne_rien() -> None:
    eth = FakeEth([transfer(ZERO, ALICE, 1, block=1, index=0, tx=1)], 10)
    config = MonitorConfig(rpc_url=None, token_address=TOKEN, start_block=0)
    listener = ChainListener(config, FakeWeb3(eth), sleep=lambda _: None, now=lambda: FIXED_NOW)
    (mint,) = listener.fetch_events(0, 10)
    assert isinstance(mint, MintEvent)
    assert mint.via_protected_path is None and mint.depositor is None


def test_champs_partages_ne_consomment_pas_la_provenance() -> None:
    """Le fournisseur de contexte du pipeline doit encore pouvoir liberer l'entree."""
    logs = [
        swap_requested(0, ALICE, 1_000_000, WAD, block=10, index=0, tx=1),
        transfer(ZERO, ALICE, 10**18, block=11, index=0, tx=2),
        swap_completed(0, ALICE, ALICE, 1_000_000, 10**18, WAD, block=11, index=1, tx=2),
    ]
    listener, _ = _listener(logs)
    (mint,) = [e for e in listener.fetch_events(0, 100) if isinstance(e, MintEvent)]
    assert listener.correlator is not None
    assert listener.correlator.provenance_for(mint.tx_hash, mint.log_index) is not None


def test_with_provenance_depot_ou_taux_nul_devient_inconnu() -> None:
    from monitor.protected import MintProvenance

    base = MintEvent(
        tx_hash="0x" + "ab" * 32,
        log_index=0,
        block_number=1,
        chain_id=43113,
        observed_at=FIXED_NOW,
        recipient=ALICE,
        amount=1,
        request_id=None,
    )
    out = with_provenance(
        base,
        MintProvenance(
            request_id=2, depositor=ALICE, deposit_amount=0, rate_wad=0,
            source="request", claimed_minted=1,
        ),
        tracked=True,
    )
    assert out.deposit_amount is None and out.rate_wad is None
    assert out.via_protected_path is True and out.request_id == 2
    # Non suivi : rien ne change.
    assert with_provenance(base, None, tracked=False) == base


# ------------------------------------------------------------ AdminEvent


def test_role_granted_vers_admin_event_partage() -> None:
    obs = decode_admin(role_granted(SERVICE_ROLE, ATTACKER, BOB, block=5, index=2, tx=1))
    assert obs.role == SERVICE_ROLE and obs.actor is not None and obs.actor.lower() == BOB
    event = admin_event_from_observation(
        obs, chain_id=43113, observed_at=FIXED_NOW, contract_address=MINTER
    )
    assert event.kind is AdminEventKind.ROLE_GRANTED
    assert event.role == SERVICE_ROLE  # id brut, pas le nom
    assert event.subject_address.lower() == ATTACKER
    assert event.actor is not None and event.actor.lower() == BOB
    assert event.old_rate_wad is None and event.log_index == 2


def test_rate_changed_vers_admin_event_partage() -> None:
    log = _log(MINTER, [RATE_CHANGED_TOPIC, _addr_topic(BOB)], _data(WAD, 2 * WAD), 4, 0, 4)
    obs = decode_admin(log)
    assert (obs.old_rate_wad, obs.new_rate_wad) == (WAD, 2 * WAD)
    assert obs.role is None and obs.actor is None
    event = admin_event_from_observation(
        obs, chain_id=43113, observed_at=FIXED_NOW, contract_address=MINTER
    )
    assert event.kind is AdminEventKind.RATE_CHANGED
    assert (event.old_rate_wad, event.new_rate_wad) == (WAD, 2 * WAD)
    assert event.role is None


def test_admin_event_invalide_est_refuse() -> None:
    obs = AdminObservation(
        kind="rate_changed",
        subject_address=BOB,
        tx_hash="0x" + "01" * 32,
        block_number=1,
        log_index=0,
        old_rate_wad=0,  # taux nul : refuse par le modele partage (gt=0)
        new_rate_wad=WAD,
    )
    with pytest.raises(ValueError):
        admin_event_from_observation(
            obs, chain_id=43113, observed_at=FIXED_NOW, contract_address=MINTER
        )
