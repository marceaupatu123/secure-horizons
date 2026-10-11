"""Page Streamlit « Démo interactive » (#148) : le pitch anime, sur les vrais scenarios.

A chaque lancement, la page REJOUE les scenarios A et B avec le moteur #47 (vrai
code de detection/reponse pour B), puis anime le resultat. Logique et HTML dans
`dashboard/story.py` ; cette page ne fait que lancer et afficher.

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
from dashboard.story import Story, build_story, render_story_html  # noqa: E402

STORY_KEY = "story"
STORY_SEED_KEY = "story_seed"
STORY_SECONDS_KEY = "story_seconds"
COMPONENT_HEIGHT = 860


def _replay(seed: int) -> tuple[Story, float]:
    """Rejoue A et B pour `seed` en montrant la progression ; renvoie l'histoire et la duree."""
    start = time.perf_counter()
    with st.status("Rejeu des attaques sur le moteur de démo…", expanded=False) as status:
        status.write("🔑 Acte 1 : la clé volée, sur un contrat classique et sur Secure Horizons")
        result_a = run_scenario_quietly("A", seed=seed, disabled=frozenset())
        status.write("🕵️ Acte 2 : le pirate discret, dans du trafic synthétique analysé par "
                     "les vrais surveillants")
        result_b = run_scenario_quietly("B", seed=seed, disabled=frozenset())
        story = build_story(result_a, result_b)
        status.update(label="Rejeu terminé", state="complete")
    return story, time.perf_counter() - start


def main() -> None:
    """Rend la page de demo interactive."""
    st.set_page_config(page_title="Démo interactive — Secure Horizons", page_icon="🛡️",
                       layout="wide")
    st.title("🛡️ Secure Horizons : une clé volée ne rapporte presque rien")
    st.caption("Démo interactive : chaque lancement rejoue réellement les attaques. Données "
               "synthétiques et fictives, aucune vraie adresse ni clé.")

    with st.sidebar:
        st.header("Rejeu")
        seed = int(st.number_input("Seed (même seed = même résultat)", value=DEMO_SEED, step=1,
                                   key="story_seed_input"))
        clicked = st.button("🔁 Rejouer les attaques", key="replay_story")

    if clicked or st.session_state.get(STORY_SEED_KEY) != seed:
        story, seconds = _replay(seed)
        st.session_state[STORY_KEY] = story
        st.session_state[STORY_SEED_KEY] = seed
        st.session_state[STORY_SECONDS_KEY] = seconds

    story = st.session_state[STORY_KEY]
    st.caption(f"Rejeu calculé en {st.session_state[STORY_SECONDS_KEY]:.1f} s (seed {story.seed}). "
               "Clique sur les onglets puis sur ▶ pour lancer chaque animation.")
    components.html(render_story_html(story), height=COMPONENT_HEIGHT, scrolling=True)


main()
