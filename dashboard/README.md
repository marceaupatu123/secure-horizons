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
- `scenarios/` : moteur des scénarios de démo (#47) : modèles de résultat, registre branchable,
  paramètres de simulation (`config.py`), briques simulées hors chaîne (`sim_*.py`), catalogue
  des 7 scénarios (`catalog.py`) et mise en tableau pure (`view.py`).
- `demo.py` : CLI `python -m dashboard.demo list|run`.
- `pages/1_Scenarios_de_demo.py` : page Streamlit « Scénarios de démo » (rendu uniquement).

Aucun chiffre affiché n'est écrit en dur : tout est calculé à partir du jeu synthétique. Ce sont
des comptages, pas des mesures de performance.

## Scénarios de démo (#47)

Forme retenue : **CLI + page Streamlit du dashboard existant — à valider en équipe**.

```bash
python -m dashboard.demo list                                   # catalogue
python -m dashboard.demo run A --seed 20 [--json] [--disable C] # rejoue un scénario
make demo ARGS="run B"                                          # idem via make
make run-dashboard                                              # page « Scénarios de démo » dans la barre latérale
```

Même seed = même résultat (JSON identique). Un scénario optionnel désactivé (`--disable C`, ou
case décochée sur la page) affiche « désactivé » sans aucune métrique ; un scénario dont la
brique n'est pas disponible afficherait « non disponible (dépend de #X) ».

| Scénario | Attendu (issue #47) | Dépend de | À remplacer par |
|----------|---------------------|-----------|-----------------|
| A | Le vulnérable se fait vider, le protégé borne la perte. | #4, #5 | #4, #5, #24 |
| B | Détection + alerte + allongement de fenêtre Ghost. | #11, #12, #17 | #11, #12, #17, #24 |
| C (optionnel) | Moins de pertes en aval quand la balise est lue. | #7, #25 | #7, #25 |
| D (optionnel) | Pertes côté protocole ≈ zéro (à vérifier) vs pertes côté spéculateurs. | #8, #25 | #8, #25 |
| N1 | Zéro alerte, zéro gel. | #11, #12 | #11, #12 |
| N2 | Pas de déclenchement (volume élevé sans dispersion effondrée). | #11, #12 | #11, #12 |
| N3 | La fenêtre revient seule à la normale, aucun gel définitif. | #11, #12, #17 | #11, #12, #17 |

À garder en tête :

- Tout est **simulation hors chaîne** (contrats, surveillant, réponse) : les modules amont sont
  encore des squelettes. Chaque résultat porte le bandeau « simulation hors chaîne, à remplacer
  par #… ».
- Les paramètres de `scenarios/config.py` (seuils, volumes, délais) sont des valeurs de départ
  **à calibrer** (`docs/OPEN_QUESTIONS.md` §6) : aucun seuil n'est acté.
- Les grandeurs affichées sont **mesurées sur la simulation uniquement**, pas sur le contrat
  déployé (cf. `docs/CLAIMS.md`). Les « attendus » sont constatés (`OK` / `KO`), pas garantis.

Brancher une vraie implémentation : remplacer, dans `scenarios/catalog.py`, le `runner` du
`ScenarioSpec` concerné par une fonction `(seed, params) -> ScenarioResult` qui appelle le vrai
module (`scenarios.registry.register` sert à ajouter un **nouvel** id : il refuse un id déjà
enregistré). Un runner qui lève
`NotImplementedError` donne automatiquement « non disponible (dépend de #X) ». La CLI et la page
n'ont pas à changer.

## Modèles `shared/` consommés

`Alert`, `AlertSeed`, `AlertKind`, `AlertSeverity`, `ResponseAction`, `ResponseActionType`,
`ResponseActionStatus`, `AuditLogEntry`, `QuarantineRecord`, `QuarantineStatus`,
`RiskBeaconUpdate`, `BeaconRiskLevel`, `ReleaseDecision`, `ReleaseVerdict`,
`GhostTokenMintEvent`, `GhostTokenRedemptionEvent`, `GhostTokenBurnEvent`.

L'état d'un périmètre (`PerimeterState`) est une enum **locale** : `shared/` n'en définit pas.
