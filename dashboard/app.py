"""Interface de demo (Streamlit) : alertes, reponse graduee, quarantaine Ghost, journal.

Rendu uniquement : toute la logique (etats, compteurs, tableaux) vit dans
`dashboard/view_model.py`, les donnees synthetiques seedees dans
`dashboard/demo_data.py`.

Lancer en local :  make run-dashboard
(sans make :       python -m streamlit run dashboard/app.py)
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

# `streamlit run dashboard/app.py` ne met que `dashboard/` sur sys.path :
# on ajoute la racine du repo pour importer `dashboard.*` et `shared.*`.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st  # noqa: E402

from dashboard.demo_data import (  # noqa: E402
    DEMO_EXTENDED_WINDOW,
    DEMO_SEED,
    DemoDataset,
    generate_demo_dataset,
)
from dashboard.view_model import (  # noqa: E402
    ALERT_KIND_LABELS,
    PERIMETER_STATE_LABELS,
    SEVERITY_LABELS,
    PerimeterState,
    actions_to_frame,
    alerts_to_frame,
    audit_log_to_frame,
    compute_summary,
    derive_perimeter_states,
    filter_alerts,
    format_base_units,
    ghost_events_to_frame,
    perimeters_to_frame,
    quarantine_to_frame,
)
from shared.models import AlertKind, AlertSeverity  # noqa: E402

SIM_OFFSET_MAX_MINUTES = int(DEMO_EXTENDED_WINDOW.total_seconds() // 60) + 30

STATE_MACHINE_TEXT = f"""
- **{PERIMETER_STATE_LABELS[PerimeterState.NORMAL]} → {PERIMETER_STATE_LABELS[PerimeterState.DELAYED]}** :
  surveillant / IA, seul (direction sûre), sur « volume élevé ET dispersion effondrée ».
- **{PERIMETER_STATE_LABELS[PerimeterState.DELAYED]} → {PERIMETER_STATE_LABELS[PerimeterState.NORMAL]}** :
  automatique à l'expiration (silence = retour à la normale).
- **{PERIMETER_STATE_LABELS[PerimeterState.DELAYED]} → {PERIMETER_STATE_LABELS[PerimeterState.DESTROYED]}** :
  humains, multisig 2/3 ; détruit ratio × solde Ghost non converti.
- **{PERIMETER_STATE_LABELS[PerimeterState.DELAYED]} → {PERIMETER_STATE_LABELS[PerimeterState.GLOBAL_PAUSE]}** :
  escalade, humains, multisig 3/3.
"""


@st.cache_data
def load_dataset() -> DemoDataset:
    """Charge (une fois) le jeu de demo synthetique seede."""
    return generate_demo_dataset(DEMO_SEED)


def main() -> None:
    """Rend la page de demo."""
    st.set_page_config(page_title="Crypto-Secure — Guardians of Value", page_icon="🛡️",
                       layout="wide")
    dataset = load_dataset()

    st.title("Crypto-Secure — démo")
    st.info(
        f"Données synthétiques et fictives (seed {dataset.seed}) : aucune vraie adresse ni clé. "
        "Les chiffres affichés sont des comptages calculés sur ce jeu, pas des mesures de "
        "performance."
    )

    with st.sidebar:
        st.header("Simulation")
        offset = st.slider(
            "Instant simulé (minutes après la référence)",
            min_value=0,
            max_value=SIM_OFFSET_MAX_MINUTES,
            value=0,
            key="sim_offset",
        )
        at = dataset.reference_time + timedelta(minutes=offset)
        st.caption(f"Instant simulé : {at.isoformat()}")
        st.header("Filtres des alertes")
        severities = st.multiselect(
            "Gravité",
            options=[s.value for s in AlertSeverity],
            default=[s.value for s in AlertSeverity],
            format_func=lambda v: SEVERITY_LABELS[AlertSeverity(v)],
            key="filter_severity",
        )
        kinds = st.multiselect(
            "Type d'alerte",
            options=[k.value for k in AlertKind],
            default=[k.value for k in AlertKind],
            format_func=lambda v: ALERT_KIND_LABELS[AlertKind(v)],
            key="filter_kind",
        )

    summary = compute_summary(dataset, at)
    states = derive_perimeter_states(dataset.alerts, dataset.actions, at)

    st.header("Vue d'ensemble")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Alertes critiques",
                str(summary.alert_count_by_severity[AlertSeverity.CRITICAL.value]))
    col2.metric("Périmètres retardés",
                str(summary.perimeter_count_by_state[PerimeterState.DELAYED.value]))
    col3.metric("Ghost suspect détruit (base units)",
                format_base_units(summary.burned_ghost_total))
    col4.metric("Actions en attente multisig", str(summary.pending_multisig_actions))

    st.header("Alertes")
    visible = filter_alerts(
        dataset.alerts,
        {AlertSeverity(v) for v in severities},
        {AlertKind(v) for v in kinds},
    )
    st.dataframe(alerts_to_frame(visible), width="stretch", hide_index=True)
    st.caption("La gravité est indiquée en texte dans la colonne « Gravité ».")

    st.header("Réponse graduée")
    st.subheader("Machine à états d'un périmètre")
    st.markdown(STATE_MACHINE_TEXT)
    st.subheader("État des périmètres")
    st.dataframe(perimeters_to_frame(states, dataset.quarantine, dataset.beacons),
                 width="stretch", hide_index=True)
    st.subheader("Actions de réponse")
    st.dataframe(actions_to_frame(dataset.actions, at), width="stretch", hide_index=True)

    st.header("Quarantaine Ghost")
    st.caption("Enregistrements de quarantaine : instantané à l'heure de référence.")
    st.dataframe(quarantine_to_frame(dataset.quarantine), width="stretch", hide_index=True)
    st.subheader("Événements Ghost (émission, conversion, destruction)")
    st.dataframe(
        ghost_events_to_frame(dataset.ghost_mints, dataset.ghost_redemptions,
                              dataset.ghost_burns, at),
        width="stretch",
        hide_index=True,
    )

    st.header("Journal d'audit")
    st.dataframe(audit_log_to_frame(dataset.audit_log), width="stretch", hide_index=True)


main()
