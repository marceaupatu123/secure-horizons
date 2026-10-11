"""Tests hors reseau du rejeu Fuji (#148) : derivation des roles, rejeu enregistre, histoire."""

from __future__ import annotations

import json

import pytest

from dashboard.scenarios import fuji_live
from dashboard.story import build_fuji_story

MASTER = "0x" + "11" * 32


def test_cles_derivees_deterministes_et_distinctes():
    keys = {role: fuji_live.derive_key(MASTER, role) for role in fuji_live.ROLES}
    assert keys == {role: fuji_live.derive_key(MASTER, role) for role in fuji_live.ROLES}
    assert len(set(keys.values())) == len(fuji_live.ROLES)
    assert MASTER not in keys.values()
    assert all(len(k) == 66 and k.startswith("0x") for k in keys.values())


def test_cle_absente_refusee(monkeypatch):
    monkeypatch.setenv(fuji_live.KEY_ENV, "<compte de TEST Fuji uniquement>")
    monkeypatch.setattr(fuji_live, "CONTRACTS_DIR", fuji_live.RUNS_DIR)  # pas de .env ici
    with pytest.raises(fuji_live.FujiLiveError):
        fuji_live.master_key_from_env()
    assert fuji_live.key_available() is False


@pytest.fixture(scope="module")
def run() -> fuji_live.FujiRun:
    recorded = fuji_live.load_run()
    if recorded is None:
        pytest.skip("aucun rejeu Fuji enregistré")
    return recorded


def test_rejeu_enregistre_coherent(run):
    assert run.chain_id == fuji_live.FUJI_CHAIN_ID
    assert run.vulnerable_loss > 0  # cas 1 : le contrat classique a cru la signature
    assert run.protected_loss == 0  # cas 2 : chaque jeton protege est adosse
    assert run.protected_inflated_rejected
    assert run.seller_usdc_final == 0  # cas 3 : le vendeur ne garde rien
    assert run.buyer_mprime_after == 0  # tout le Ghost suspect detruit
    assert run.seller_payment_after == 0  # Ghost de paiement brule
    assert run.observed_mints  # le vrai ChainListener a relu les mints
    assert all(tx.url.startswith(fuji_live.EXPLORER_URL + "/tx/0x") for tx in run.transactions)


def test_rejeu_enregistre_sans_secret():
    raw = fuji_live.LATEST_RUN_PATH.read_text(encoding="utf-8") if fuji_live.LATEST_RUN_PATH.is_file() else "{}"
    lowered = raw.lower()
    assert "private" not in lowered and "secret" not in lowered
    assert "key" not in json.loads(raw)


def test_etapes_couvrent_les_cas(run):
    cases = {s.case for s in run.steps}
    known = {fuji_live.CASE_MINT_PASSES, fuji_live.CASE_MINT_BLOCKED,
             fuji_live.CASE_RECOVERY_WINDOW, fuji_live.CASE_SPECULATIVE,
             fuji_live.CASE_GHOST_SELLER, fuji_live.CASE_CONTAGION}
    assert cases <= known and fuji_live.CASE_CONTAGION in cases
    for step in run.steps:
        assert step.command and step.effect and step.contract
        assert step.contract in run.contracts  # chaque etape pointe un contrat deploye
        assert step.tx_urls and all(u.startswith(fuji_live.EXPLORER_URL) for u in step.tx_urls)


def test_histoire_fuji(run):
    story = build_fuji_story(run)
    assert story.tx_count == len(run.transactions)
    assert story.step_count == len(run.steps)
    ids = [c.id for c in story.cases]
    from dashboard.story import FUJI_CASE_ORDER
    assert ids == [c for c in FUJI_CASE_ORDER if c in ids]  # ordre respecté
    assert "contagion" in ids
    assert all(c.verdict for c in story.cases)
    assert sum(len(c.steps) for c in story.cases) == story.step_count
    assert story.live_block is None and story.live_matches_record is None
    assert all(c.url.startswith(fuji_live.EXPLORER_URL + "/address/0x") for c in story.contracts)



def test_rapport_dora_fuji(run):
    from dashboard.scenarios.fuji_report import (
        DEMO_RULE_NAME,
        build_fuji_incident,
        fuji_incident_report,
    )

    alert, actions, audit = build_fuji_incident(run)
    inflated = next(t for t in run.transactions if t.actor == "attacker" and not t.success)
    assert alert.source_tx_hash == inflated.tx_hash
    assert alert.monitor_name == DEMO_RULE_NAME
    assert [a.action_type.value for a in actions] == ["delay", "destroy"]
    assert actions[1].suspect_amount == run.sell_mprime
    assert all(e.related_tx_hash for e in audit)
    report = fuji_incident_report(run)
    assert "Rapport d'incident" in report
    assert inflated.url in report
    assert "hors ligne" in report  # aucun appel AWS par defaut


def test_rapport_dora_fuji_incomplet(run):
    from dashboard.scenarios.fuji_report import FujiReportError, build_fuji_incident

    partial = run.model_copy(update={"transactions": [
        t for t in run.transactions if not (t.actor == "guardian2" and "validation" in t.label.lower())]})
    with pytest.raises(FujiReportError):
        build_fuji_incident(partial)
