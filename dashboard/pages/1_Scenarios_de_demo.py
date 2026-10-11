"""Page Streamlit « Scénarios de démo » (#47), ajoutee au dashboard #20 (multipage).

Rendu uniquement : le moteur vit dans `dashboard/scenarios/` (simulation hors
chaîne), la mise en tableau dans `dashboard/scenarios/view.py` et les tableaux
alertes / reponse / journal dans `dashboard/view_model.py`.

Lancer : make run-dashboard, puis « Scénarios de démo » dans la barre laterale.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run dashboard/app.py` ne met que `dashboard/` sur sys.path :
# on ajoute la racine du repo pour importer `dashboard.*` et `shared.*`.
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import dashboard.scenarios  # noqa: E402,F401  (peuple le registre)
from dashboard.demo import run_scenario_quietly  # noqa: E402
from dashboard.demo_data import DEMO_SEED  # noqa: E402
from dashboard.scenarios import (  # noqa: E402
    STATUS_LABELS,
    ScenarioResult,
    ScenarioStatus,
    ScenarioVariant,
    get_spec,
    list_specs,
)
from dashboard.scenarios.view import (  # noqa: E402
    checks_to_frame,
    common_metric_keys,
    metrics_to_frame,
    scenarios_to_frame,
    side_by_side_frame,
    simulation_banner,
)
from dashboard.view_model import (  # noqa: E402
    actions_to_frame,
    alerts_to_frame,
    audit_log_to_frame,
    derive_perimeter_states,
    ghost_events_to_frame,
    perimeters_to_frame,
)

RESULT_KEY = "scenario_result"
RESULT_PARAMS_KEY = "scenario_result_params"
OPTIONAL_TOGGLES = {
    "C": "Inclure C (optionnel, volet 3)",
    "D": "Inclure D (optionnel, quarantaine liquide)",
}


def _table(frame: pd.DataFrame) -> None:
    st.dataframe(frame, width="stretch", hide_index=True)


def _render_variant_summary(variant: ScenarioVariant) -> None:
    st.subheader(variant.label)
    _table(metrics_to_frame(variant))
    if variant.checks:
        _table(checks_to_frame(variant))


def _render_variant_details(variant: ScenarioVariant) -> None:
    data = variant.dataset
    at = variant.end_time
    with st.expander(f"Alertes, réponse et journal — {variant.label}"):
        st.caption(f"État à la fin du scénario : {at.isoformat()}")
        st.markdown("**Alertes**")
        _table(alerts_to_frame(data.alerts))
        st.markdown("**État des périmètres**")
        _table(perimeters_to_frame(derive_perimeter_states(data.alerts, data.actions, at),
                                   data.quarantine, data.beacons))
        st.markdown("**Actions de réponse**")
        _table(actions_to_frame(data.actions, at))
        st.markdown("**Événements Ghost**")
        _table(ghost_events_to_frame(data.ghost_mints, data.ghost_redemptions,
                                     data.ghost_burns, at))
        st.markdown("**Journal d'audit**")
        _table(audit_log_to_frame(data.audit_log))
    if variant.incident_report:
        with st.expander(f"Rapport d'incident DORA (#15) — {variant.label}"):
            st.markdown(variant.incident_report)


def _render_result(result: ScenarioResult) -> None:
    spec = get_spec(result.scenario_id)
    st.header(f"{spec.id} — {spec.title}")
    st.markdown(spec.description)
    st.markdown(f"Attendu : {spec.expected}")
    st.caption(f"Statut : {STATUS_LABELS[result.status]}")
    if result.status != ScenarioStatus.COMPLETED:
        st.warning(result.message)
        return
    st.caption(simulation_banner(result))
    variants = result.variants
    if len(variants) > 1:
        keys = common_metric_keys(result)
        if keys:
            st.markdown("**Comparaison côte à côte**")
            _table(side_by_side_frame(result, keys))
        for column, variant in zip(st.columns(len(variants)), variants, strict=True):
            with column:
                _render_variant_summary(variant)
    else:
        for variant in variants:
            _render_variant_summary(variant)
    for variant in variants:
        _render_variant_details(variant)


def main() -> None:
    """Rend la page des scenarios de demo."""
    st.set_page_config(page_title="Scénarios de démo — Secure Horizons", layout="wide")
    st.title("Scénarios de démo")
    st.info(
        "Données synthétiques et fictives : aucune vraie adresse ni clé. Le bandeau de chaque "
        "scénario dit quelles briques tournent sur le vrai code et lesquelles restent simulées ; "
        "les chiffres sont des comptages, pas des mesures du contrat déployé."
    )

    specs = list_specs()
    ids = [spec.id for spec in specs]
    with st.sidebar:
        st.header("Scénario")
        scenario_id = st.selectbox(
            "Scénario à lancer",
            options=ids,
            format_func=lambda i: f"{i} — {get_spec(i).title}",
            key="scenario_id",
        )
        seed = int(st.number_input("Seed", value=DEMO_SEED, step=1, key="scenario_seed"))
        enabled = {
            sid: st.checkbox(label, value=True, key=f"enable_{sid}")
            for sid, label in OPTIONAL_TOGGLES.items()
        }
        clicked = st.button("Lancer le scénario", key="run_scenario")
    disabled = frozenset(sid for sid, on in enabled.items() if not on)

    st.header("Catalogue")
    _table(scenarios_to_frame(specs, disabled))

    params = (scenario_id, seed, disabled)
    stored = st.session_state.get(RESULT_KEY)
    if clicked or (stored is not None and st.session_state.get(RESULT_PARAMS_KEY) != params):
        stored = run_scenario_quietly(scenario_id, seed=seed, disabled=disabled)
        st.session_state[RESULT_KEY] = stored
        st.session_state[RESULT_PARAMS_KEY] = params

    if stored is None:
        st.caption("Choisir un scénario dans la barre latérale puis « Lancer le scénario ».")
        return
    _render_result(stored)


main()
