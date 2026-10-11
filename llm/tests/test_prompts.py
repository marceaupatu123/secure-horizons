"""Tests des prompts du module llm (aucun appel reseau)."""

from __future__ import annotations

from shared.models import Alert

from llm.prompts import (
    REPORT_JSON_KEYS,
    SYSTEM_PROMPT_EXPLAIN,
    SYSTEM_PROMPT_REPORT,
    build_explain_prompt,
    build_report_prompt,
    format_alert_facts,
)


def test_system_prompts_state_ai_does_not_decide() -> None:
    for prompt in (SYSTEM_PROMPT_EXPLAIN, SYSTEM_PROMPT_REPORT):
        assert "français" in prompt
        assert "ne décide" in prompt
        assert "retard" in prompt
        assert "multisig 2/3" in prompt
        assert "multisig 3/3" in prompt
        assert "aucun chiffre" in prompt


def test_report_system_prompt_requires_json_keys() -> None:
    for key in REPORT_JSON_KEYS:
        assert f'"{key}"' in SYSTEM_PROMPT_REPORT


def test_format_alert_facts_contains_inputs(alert: Alert) -> None:
    facts = format_alert_facts(alert)
    assert alert.alert_id in facts
    assert alert.reason in facts
    assert str(alert.suspect_amount) in facts
    for seed in alert.seeds:
        assert seed.address in facts
        assert str(seed.suspect_amount) in facts


def test_format_alert_facts_na_when_missing(alert: Alert) -> None:
    bare = alert.model_copy(update={"source_tx_hash": None, "seeds": []})
    facts = format_alert_facts(bare)
    assert "source_tx_hash : n/a" in facts
    assert "seeds : aucune" in facts


def test_build_explain_prompt_contains_facts(alert: Alert) -> None:
    prompt = build_explain_prompt(alert)
    assert alert.alert_id in prompt
    assert alert.reason in prompt


def test_build_report_prompt_contains_keys_and_lines(alert: Alert) -> None:
    prompt = build_report_prompt(alert, ["T1 alerte créée"], ["D1 multisig 2/3"])
    for key in REPORT_JSON_KEYS:
        assert f'"{key}"' in prompt
    assert "T1 alerte créée" in prompt
    assert "D1 multisig 2/3" in prompt
    assert alert.alert_id in prompt
