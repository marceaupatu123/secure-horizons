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

| Scénario | Attendu (issue #47) | Branché sur le vrai code (#70) | Encore simulé |
|----------|---------------------|--------------------------------|---------------|
| A | Le vulnérable se fait vider, le protégé borne la perte. | contrats Foundry #4/#5 sur anvil local, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) | tout, par défaut (repli automatique si Foundry absent) |
| B | Détection + alerte + allongement de fenêtre Ghost. | trafic #24, surveillants #11/#12, réponse #17 | Ghost (#8) |
| C (optionnel) | Moins de pertes en aval quand la balise est lue. | — | tout (#7, #25) |
| D (optionnel) | Pertes côté protocole ≈ zéro (à vérifier) vs pertes côté spéculateurs. | — | tout (#8, #25) |
| N1 | Zéro alerte, zéro gel. | trafic #24, surveillants #11/#12, réponse #17 | rien |
| N2 | Pas de déclenchement (volume élevé sans dispersion effondrée). | trafic #24, surveillants #11/#12, réponse #17 | rien |
| N3 | La fenêtre revient seule à la normale, aucun gel définitif. | trafic #24 (+ burst injecté), #11/#12, #17 | Ghost (#8) |

### Rejouer A sur les vrais contrats (anvil)

```bash
# Foundry v1.8.5 (même version que la CI) dans le PATH ou ~/.foundry/bin, puis :
cd contracts && forge install --no-git foundry-rs/forge-std@v1.17.0 OpenZeppelin/openzeppelin-contracts@v5.4.0 && cd ..
SH_DEMO_CONTRACTS_BACKEND=anvil python -m dashboard.demo run A        # PowerShell : $env:SH_DEMO_CONTRACTS_BACKEND="anvil"
SH_DEMO_CONTRACTS_BACKEND=anvil make run-dashboard
```

Une chaîne anvil jetable est lancée sur `127.0.0.1` (port libre), `MockUSDC`, `VulnerableMinter` et
`ProtectedMinter` y sont déployés, et l'attaque de `contracts/test/ScenarioA.t.sol` est rejouée
avec les comptes **déverrouillés** d'anvil (aucune clé privée manipulée). Si Foundry manque ou si
le rejeu échoue, A retombe sur la simulation et le message le dit. Le job CI `scenario A (anvil)`
rejoue ce chemin sur chaque PR.

À garder en tête :

- **Rapport d'incident DORA (#15, #113)** : sur l'alerte d'attaque confirmée par le multisig, le
  scénario B appelle `llm.report.build_incident_report` avec les vraies actions et le vrai journal
  de l'orchestrateur (`scenarios/real_report.py`). Hors ligne par défaut (faux client, aucun
  appel AWS, déterministe) ; Bedrock réel avec `LLM_LIVE=1` (un seul appel, via le limiteur).
  Affichage : `python -m dashboard.demo run B --report`, ou l'encadré « Rapport d'incident DORA »
  de la page.

- B, N1, N2, N3 appellent le **vrai** code (`scenarios/real_pipeline.py`) : `data.generate`
  (#24), `detection.detector.RuleBasedMonitor` (#11, #12) aux seuils par défaut de
  `detection/params.py`, `response.orchestrator.ResponseOrchestrator` (#17). Le Ghost (#8, non
  livré) et l'audit humain qui confirme une destruction restent simulés (bandeau « à remplacer
  par #8 »).
- **Profil de trafic légitime** : la démo utilise le profil « petits transferts » (1–10 % du
  solde, `data/DECISION_SUPPORT_3.md` §2), à valider en équipe. Avec le profil « gros
  transferts » du générateur (5–50 %), le même surveillant lève 1 faux positif sur N1 (seed 20) :
  c'est une mesure à montrer, pas à cacher. Changer `real_transfer_fraction_*` dans
  `scenarios/config.py` pour la reproduire.
- Les paramètres de `scenarios/config.py` (volumes, délais) sont des valeurs de départ
  **à calibrer** (`docs/OPEN_QUESTIONS.md` §6) : aucun seuil n'est acté.
- Les grandeurs affichées sont des **comptages** sur trafic synthétique ou chaîne locale, pas des
  mesures du contrat déployé (cf. `docs/CLAIMS.md`). Les « attendus » sont constatés
  (`OK` / `KO`), pas garantis.

Brancher une vraie implémentation : remplacer, dans `scenarios/catalog.py`, le `runner` du
`ScenarioSpec` concerné par une fonction `(seed, params) -> ScenarioResult` qui appelle le vrai
module, et retirer son numéro de `REPLACE_BY` (le bandeau « simulation hors chaîne » disparaît
dès qu'il ne reste plus de brique simulée). `scenarios.registry.register` sert à ajouter un
**nouvel** id : il refuse un id déjà enregistré. Un runner qui lève `NotImplementedError` donne
automatiquement « non disponible (dépend de #X) ». La CLI et la page n'ont pas à changer.

## Modèles `shared/` consommés

`Alert`, `AlertSeed`, `AlertKind`, `AlertSeverity`, `ResponseAction`, `ResponseActionType`,
`ResponseActionStatus`, `AuditLogEntry`, `QuarantineRecord`, `QuarantineStatus`,
`RiskBeaconUpdate`, `BeaconRiskLevel`, `ReleaseDecision`, `ReleaseVerdict`,
`GhostTokenMintEvent`, `GhostTokenRedemptionEvent`, `GhostTokenBurnEvent`.

L'état d'un périmètre (`PerimeterState`) est une enum **locale** : `shared/` n'en définit pas.
