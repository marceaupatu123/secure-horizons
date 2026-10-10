# dashboard

- **Rôle** : interface de **démo** (Streamlit) : alertes, état de la réponse graduée
  (retarder / détruire / pause globale), quarantaine Ghost et journal d'audit.
- **Propriétaire** : @marceaupatu123 (voir `docs/TEAM.md`).
- **Lancer** : `make run-dashboard` (sans make, sous Windows : `python -m streamlit run dashboard/app.py`).
- **Tests** : `python -m pytest dashboard/`.

## Découpage

- `demo_data.py` : jeu de données **synthétique et seedé** (`DEMO_SEED`), déterministe.
  Adresses, hash et montants sont fictifs. Fenêtres 10 min / 1 h = valeurs de démo (§3.1), à mesurer.
- `view_model.py` : logique pure (sans Streamlit) : état des périmètres dérivé des
  `ResponseAction`, compteurs de la vue d'ensemble, tableaux `pandas` avec libellés texte.
- `app.py` : rendu Streamlit uniquement. Un curseur « instant simulé » montre l'expiration
  automatique d'un retard.

Aucun chiffre affiché n'est écrit en dur : tout est calculé à partir du jeu synthétique. Ce sont
des comptages, pas des mesures de performance.

## Modèles `shared/` consommés

`Alert`, `AlertSeed`, `AlertKind`, `AlertSeverity`, `ResponseAction`, `ResponseActionType`,
`ResponseActionStatus`, `AuditLogEntry`, `QuarantineRecord`, `QuarantineStatus`,
`RiskBeaconUpdate`, `BeaconRiskLevel`, `ReleaseDecision`, `ReleaseVerdict`,
`GhostTokenMintEvent`, `GhostTokenRedemptionEvent`, `GhostTokenBurnEvent`.

L'état d'un périmètre (`PerimeterState`) est une enum **locale** : `shared/` n'en définit pas.
