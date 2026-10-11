"""Page Streamlit « Démo interactive » (#148) : le pitch anime, sur les vrais scenarios.

Onglet « En vrai sur Avalanche » : rejeu en VRAIES transactions sur Fuji
(`dashboard/scenarios/fuji_live.py`), relu en direct sur la chaine a chaque affichage ;
un bouton le rejoue de bout en bout si un compte de TEST Fuji est configure dans `.env`.
Onglets suivants : scenarios A et B rejoues par le moteur #47 a chaque lancement.
Logique et HTML dans `dashboard/story.py` ; cette page ne fait que lancer et afficher.

Lancer : make run-dashboard, puis « Demo interactive » dans la barre laterale.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

import dashboard.scenarios  # noqa: E402,F401  (peuple le registre)
from dashboard.demo import run_scenario_quietly  # noqa: E402
from dashboard.demo_data import DEMO_SEED  # noqa: E402
from dashboard.scenarios import fuji_live  # noqa: E402
from dashboard.scenarios.fuji_report import FujiReportError, fuji_incident_report  # noqa: E402
from dashboard.story import FujiStory, Story, build_fuji_story, build_story, render_story_html  # noqa: E402

STORY_KEY = "story"
STORY_SEED_KEY = "story_seed"
STORY_SECONDS_KEY = "story_seconds"
REPORT_KEY = "story_report"
COMPONENT_HEIGHT = 900


def _replay(seed: int) -> tuple[Story, str | None, float]:
    """Rejoue A et B pour `seed` ; renvoie l'histoire, le rapport DORA de B et la duree."""
    start = time.perf_counter()
    with st.status("Rejeu des attaques sur le moteur de démo…", expanded=False) as status:
        status.write("🔑 Acte 1 : la clé volée, sur un contrat classique et sur Secure Horizons")
        result_a = run_scenario_quietly("A", seed=seed, disabled=frozenset())
        status.write("🕵️ Acte 2 : le pirate discret, dans du trafic synthétique analysé par "
                     "les vrais surveillants")
        result_b = run_scenario_quietly("B", seed=seed, disabled=frozenset())
        story = build_story(result_a, result_b)
        report = next((v.incident_report for v in result_b.variants if v.incident_report), None)
        status.update(label="Rejeu terminé", state="complete")
    return story, report, time.perf_counter() - start


def _fuji_story(replay_now: bool) -> tuple[FujiStory | None, fuji_live.FujiRun | None]:
    """Rejeu Fuji : enregistre (ou rejoue en direct), puis relu sur la chaine si possible."""
    run = fuji_live.load_run()
    if replay_now:
        with st.status("Rejeu en vraies transactions sur Avalanche Fuji (~1 à 2 min)…",
                       expanded=True) as status:
            try:
                run = fuji_live.replay_on_fuji(fuji_live.connect(), fuji_live.master_key_from_env(),
                                               progress=status.write)
                fuji_live.save_run(run)
                status.update(label=f"Rejeu Fuji terminé : {len(run.transactions)} transactions",
                              state="complete")
            except Exception as exc:  # noqa: BLE001 - RPC/transaction : on garde le dernier rejeu
                status.update(label=f"Rejeu Fuji interrompu : {exc}", state="error")
    if run is None:
        return None, None
    try:
        live = fuji_live.read_live_state(fuji_live.connect(), run)
    except Exception:  # noqa: BLE001 - RPC injoignable : on affiche le rejeu enregistre
        live = None
    return build_fuji_story(run, live), run


def main() -> None:
    """Rend la page de demo interactive."""
    st.set_page_config(page_title="Démo interactive — Secure Horizons", page_icon="🛡️",
                       layout="wide")
    st.title("🛡️ Secure Horizons : une clé volée ne rapporte presque rien")
    st.caption("Démo interactive : le premier onglet montre de vraies transactions sur le testnet "
               "Avalanche Fuji ; les suivants rejouent nos scénarios à chaque lancement. Aucune "
               "vraie valeur en jeu.")

    with st.sidebar:
        st.header("Rejeu")
        seed = int(st.number_input("Seed (même seed = même résultat)", value=DEMO_SEED, step=1,
                                   key="story_seed_input"))
        clicked = st.button("🔁 Rejouer les scénarios", key="replay_story")
        st.header("Avalanche Fuji")
        can_replay = fuji_live.key_available()
        fuji_clicked = st.button("⛓️ Rejouer sur Fuji maintenant", key="replay_fuji",
                                 disabled=not can_replay)
        if not can_replay:
            st.caption("Compte de TEST Fuji absent du .env : affichage du dernier rejeu enregistré.")

    if clicked or st.session_state.get(STORY_SEED_KEY) != seed:
        story, report, seconds = _replay(seed)
        st.session_state[STORY_KEY] = story
        st.session_state[REPORT_KEY] = report
        st.session_state[STORY_SEED_KEY] = seed
        st.session_state[STORY_SECONDS_KEY] = seconds

    fuji_story, run = _fuji_story(fuji_clicked)
    story = st.session_state[STORY_KEY].model_copy(update={"fuji": fuji_story})
    st.caption(f"Scénarios rejoués en {st.session_state[STORY_SECONDS_KEY]:.1f} s "
               f"(seed {story.seed}). Clique sur les onglets puis sur ▶ pour lancer chaque animation.")
    components.html(render_story_html(story), height=COMPONENT_HEIGHT, scrolling=True)
    _render_reports(_fuji_report(run), st.session_state.get(REPORT_KEY), story.seed)


def _fuji_report(run: fuji_live.FujiRun | None) -> str | None:
    """Rapport DORA de l'incident reel Fuji (None sans rejeu ou rejeu incomplet)."""
    if run is None:
        return None
    try:
        return fuji_incident_report(run)
    except FujiReportError:
        return None


def _render_reports(fuji_report: str | None, report: str | None, seed: int) -> None:
    """Rapports d'incident DORA (#15) : incident reel Fuji, puis acte 2."""
    st.header("📄 Le rapport réglementaire, rédigé tout seul")
    st.markdown(
        "En Europe, le règlement **DORA** oblige les acteurs financiers à déclarer chaque incident "
        "informatique majeur, avec un rapport structuré. C'est comme le **constat amiable** après un "
        "accrochage : il faut le remplir vite et bien. Dès que les humains confirment une attaque, "
        "notre IA rédige ce rapport à partir des vraies alertes et du vrai journal d'audit. Elle "
        "**rédige seulement** : elle ne décide d'aucune action."
    )
    st.caption("Mode hors ligne par défaut (aucun appel AWS, résultat reproductible) ; "
               "`LLM_LIVE=1` fait rédiger le rapport par Bedrock.")
    tab_fuji, tab_b = st.tabs(["⛓️ Incident réel sur Avalanche Fuji", "🕵️ Acte 2 (pirate discret)"])
    with tab_fuji:
        _render_report(fuji_report, "rapport-dora-incident-fuji.md", "download_dora_fuji",
                       "Aucun rejeu Fuji enregistré : pas encore de rapport.")
    with tab_b:
        _render_report(report, f"rapport-dora-scenario-B-seed{seed}.md", "download_dora",
                       "Aucun rapport : aucune alerte confirmée dans ce rejeu.")


def _render_report(report: str | None, file_name: str, key: str, empty: str) -> None:
    if report is None:
        st.info(empty)
        return
    with st.container(border=True):
        st.markdown(report)
    st.download_button("⬇️ Télécharger le rapport DORA (Markdown)", report, file_name=file_name,
                       mime="text/markdown", key=key)


main()
