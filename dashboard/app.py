"""Interface de demo (Streamlit) — SQUELETTE.

Point d'entree minimal pour `make run-dashboard` (= `streamlit run dashboard/app.py`).
Aucune logique metier ni aucun branchement aux autres modules ici : le contenu
reel (alertes, reponse graduee, journal) est a implementer par le proprietaire
du module `dashboard`.

Lancer en local :  make run-dashboard
"""

from __future__ import annotations

import streamlit as st


def main() -> None:
    """Rend la page de demo (squelette)."""
    st.set_page_config(page_title="Secure Horizons — Guardians of Value", page_icon="🛡️")
    st.title("Secure Horizons — démo (squelette)")
    st.write(
        "Interface de démonstration à implémenter. "
        "Voir docs/OPEN_QUESTIONS.md pour les décisions en attente."
    )
    st.info("Aucune donnée réelle n'est affichée : données synthétiques uniquement.")


if __name__ == "__main__":
    main()
else:
    # Streamlit execute le script au niveau module (pas via __main__).
    main()
