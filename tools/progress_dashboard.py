"""Tableau de bord d'avancement du projet (lecture seule).

Lit l'etat reel des issues GitHub via la CLI `gh` et affiche l'avancement de
l'equipe : progression globale, par vague (wave:0..5) et par module.

Ce n'est PAS le dashboard metier (`dashboard/`, issue #20) : c'est un outil de
suivi d'equipe, volontairement place dans `tools/` pour ne marcher sur le
peripherique d'aucun module. Lecture seule : il ne modifie ni issue ni board.

Lancer :
    make dashboard-progress
    # ou directement :
    streamlit run tools/progress_dashboard.py

Prerequis : `gh` installe et authentifie (`gh auth status` vert). Sous Windows,
le binaire par defaut est "%ProgramFiles%\\GitHub CLI\\gh.exe" s'il n'est pas
dans le PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter

import pandas as pd
import streamlit as st

REPO = "marceaupatu123/secure-horizons"
WAVES = ["wave:0", "wave:1", "wave:2", "wave:3", "wave:4", "wave:5"]
WAVE_LABELS = {
    "wave:0": "Vague 0 - debloquer",
    "wave:1": "Vague 1 - decisions",
    "wave:2": "Vague 2 - fondations",
    "wave:3": "Vague 3 - metier",
    "wave:4": "Vague 4 - reponse + conformite",
    "wave:5": "Vague 5 - demo + options",
}


def _gh_path() -> str | None:
    """Retourne le chemin de l'executable `gh`, ou None s'il est introuvable."""
    found = shutil.which("gh")
    if found:
        return found
    # Emplacement d'installation par defaut sous Windows.
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidate = os.path.join(program_files, "GitHub CLI", "gh.exe")
    return candidate if os.path.isfile(candidate) else None


def fetch_issues() -> list[dict]:
    """Recupere toutes les issues (ouvertes + fermees) via `gh`.

    Returns:
        Liste de dicts avec les cles: number, title, state, labels (list[str]),
        assignees (list[str]).

    Raises:
        RuntimeError: si `gh` est introuvable, non authentifie, ou en erreur.
    """
    gh = _gh_path()
    if gh is None:
        raise RuntimeError(
            "GitHub CLI (gh) introuvable. Installe-le (winget install GitHub.cli) "
            "et connecte-toi (gh auth login)."
        )
    try:
        result = subprocess.run(
            [
                gh, "issue", "list",
                "--repo", REPO,
                "--state", "all",
                "--limit", "200",
                "--json", "number,title,state,labels,assignees",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Echec de l'appel a gh : {exc}") from exc

    if result.returncode != 0:
        raise RuntimeError(
            "gh a renvoye une erreur (es-tu authentifie ? `gh auth status`) :\n"
            + (result.stderr or "").strip()
        )

    raw = json.loads(result.stdout or "[]")
    issues: list[dict] = []
    for it in raw:
        issues.append(
            {
                "number": it["number"],
                "title": it["title"],
                "state": it["state"].lower(),
                "labels": [lbl["name"] for lbl in it.get("labels", [])],
                "assignees": [a["login"] for a in it.get("assignees", [])],
            }
        )
    return issues


def _wave_of(labels: list[str]) -> str:
    """Retourne le label de vague d'une issue, ou 'sans vague'."""
    for w in WAVES:
        if w in labels:
            return w
    return "sans vague"


def _module_of(labels: list[str]) -> str:
    """Retourne le module (label module:*) d'une issue, ou 'autre'."""
    for lbl in labels:
        if lbl.startswith("module:"):
            return lbl.split(":", 1)[1]
    return "autre"


def render() -> None:
    """Rend le tableau de bord Streamlit."""
    st.set_page_config(page_title="Crypto-Secure - Avancement", page_icon="📊", layout="wide")
    st.title("📊 Crypto-Secure - Avancement du projet")
    st.caption(f"Source : issues GitHub de {REPO} (lecture seule via gh). Rafraichir la page pour actualiser.")

    try:
        issues = fetch_issues()
    except RuntimeError as exc:
        st.error(str(exc))
        st.info("Ce tableau de bord lit l'etat des issues ; il ne modifie rien.")
        return

    if not issues:
        st.warning("Aucune issue trouvee.")
        return

    done = [i for i in issues if i["state"] == "closed"]
    total = len(issues)
    pct = round(100 * len(done) / total) if total else 0

    # --- Indicateurs globaux ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Tâches totales", total)
    c2.metric("Terminées", len(done))
    c3.metric("Restantes", total - len(done))
    st.progress(pct / 100, text=f"Avancement global : {pct}%")

    st.divider()

    # --- Avancement par vague ---
    st.subheader("Avancement par vague")
    rows = []
    for w in WAVES + ["sans vague"]:
        in_wave = [i for i in issues if _wave_of(i["labels"]) == w]
        if not in_wave:
            continue
        closed = sum(1 for i in in_wave if i["state"] == "closed")
        rows.append(
            {
                "Vague": WAVE_LABELS.get(w, w),
                "Faites": closed,
                "Total": len(in_wave),
                "%": round(100 * closed / len(in_wave)),
            }
        )
    if rows:
        df_wave = pd.DataFrame(rows).set_index("Vague")
        st.dataframe(df_wave, use_container_width=True)
        st.bar_chart(df_wave[["Faites", "Total"]])

    st.divider()

    # --- Repartition par module ---
    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("Tâches par module")
        mod_counts = Counter(_module_of(i["labels"]) for i in issues)
        df_mod = pd.DataFrame(
            sorted(mod_counts.items(), key=lambda kv: kv[0]), columns=["Module", "Tâches"]
        ).set_index("Module")
        st.bar_chart(df_mod)

    with col_right:
        st.subheader("Statut global")
        state_counts = Counter(i["state"] for i in issues)
        df_state = pd.DataFrame(
            [{"Statut": k, "Nombre": v} for k, v in state_counts.items()]
        ).set_index("Statut")
        st.bar_chart(df_state)

    st.divider()

    # --- Tâches en cours (assignees) et restantes de la prochaine vague ---
    st.subheader("Tâches en cours (assignées, non terminées)")
    in_progress = [i for i in issues if i["assignees"] and i["state"] != "closed"]
    if in_progress:
        st.table(
            pd.DataFrame(
                [
                    {
                        "#": i["number"],
                        "Titre": i["title"],
                        "Assigné à": ", ".join(i["assignees"]),
                        "Module": _module_of(i["labels"]),
                        "Vague": _wave_of(i["labels"]).replace("wave:", "V"),
                    }
                    for i in sorted(in_progress, key=lambda x: x["number"])
                ]
            )
        )
    else:
        st.info("Aucune tâche assignée en cours. Pense à t'assigner ton issue : gh issue edit <N> --add-assignee \"@me\"")


# Streamlit execute le script au niveau module.
render()
