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
    assert run.vulnerable_loss > 0  # le contrat classique a cru la signature
    assert run.protected_loss == 0  # chaque jeton protege est adosse a un depot
    assert run.protected_inflated_rejected
    assert run.attacker_ghost_before > 0 and run.attacker_ghost_after == 0
    assert run.observed_mints  # le vrai ChainListener a relu les mints
    assert all(tx.url.startswith(fuji_live.EXPLORER_URL + "/tx/0x") for tx in run.transactions)


def test_rejeu_enregistre_sans_secret():
    raw = fuji_live.LATEST_RUN_PATH.read_text(encoding="utf-8") if fuji_live.LATEST_RUN_PATH.is_file() else "{}"
    lowered = raw.lower()
    assert "private" not in lowered and "secret" not in lowered
    assert "key" not in json.loads(raw)


def test_histoire_fuji(run):
    story = build_fuji_story(run)
    assert story.tx_count == len(run.transactions)
    assert sum(len(s.txs) for s in story.steps) == story.tx_count
    assert story.vulnerable_minted_tokens > story.vulnerable_collateral_tokens
    assert story.protected_minted_tokens <= story.protected_collateral_tokens
    assert story.live_block is None and story.live_matches_record is None
    assert all(c.url.startswith(fuji_live.EXPLORER_URL + "/address/0x") for c in story.contracts)
