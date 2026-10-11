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
- `story.py` + `pages/0_Demo_interactive.py` : **démo interactive animée pour le pitch** (#148).
  La page rejoue réellement A et B à chaque lancement (même seed = même résultat), puis raconte
  l'histoire en 3 onglets animés (clé volée, pirate discret, bilan) avec des analogies pour
  novices. `story.py` extrait les grandeurs mesurées et produit un HTML autonome (sans ressource
  externe, respecte `prefers-reduced-motion`). C'est la page à ouvrir devant un jury ou des
  investisseurs : « Demo interactive » dans la barre latérale.
- `scenarios/fuji_live.py` : **rejeu en vraies transactions sur Avalanche Fuji** (#148), premier
  onglet de la démo interactive, raconté en **4 cas joués étape par étape dans un faux terminal**
  (chaque bouton tape et exécute une commande, l'effet renvoie à la transaction Snowtrace) : (1) *le
  mint passe* — contrat classique, mint gonflé accepté ; (2) *le mint est bloqué* — `ProtectedMinter`,
  mint gonflé rejeté on-chain puis seul le dépôt servi ; (3) *la fenêtre de reprise* — un échange
  donne du **M-Ghost** (pas du M-Coin), converti en **M-Coin** via `convert` seulement après la
  fenêtre de sécurité (raccourcie à 1 s pour jouer la conversion en direct), ce qui rend la reprise
  possible ; (4) *un vendeur de Ghost pose problème* — le
  Ghost est écoulé via le `SettlementRouter` (USDC de l'acheteur bloqué au coffre, vendeur payé en
  Ghost de paiement), le vendeur est signalé (méthode non divulguée), les gardiens 2/3 détruisent tout
  le Ghost suspect et brûlent le Ghost de paiement du vendeur (son USDC, gelé faute de conversion, est
  restitué à l'acheteur). Les gestes d'intendance (dépôts de collatéral, faucets) sont joués mais non
  exposés. Le vrai `monitor.ChainListener` relit les mints ; la page relit l'état on-chain à chaque
  affichage. Lancer : `python -m dashboard.scenarios.fuji_live` (`forge build` dans `contracts/` +
  `GUARDIAN_PRIVATE_KEY` d'un compte de **TEST** Fuji dans `.env`). Le signal de réponse est une règle
  de démo, pas un surveillant du module `detection`.
- `scenarios/fuji_report.py` : **rapport d'incident DORA de l'incident réel Fuji** (#148). Traduit
  les vraies transactions en `Alert` / `ResponseAction` / `AuditLogEntry` partagés et appelle
  `llm.report` tel quel (hors ligne par défaut, Bedrock avec `LLM_LIVE=1`), puis ajoute un tableau de
  preuves avec un lien Snowtrace par étape. Affiché (et téléchargeable) sous la démo interactive, à
  côté du rapport de l'acte 2.

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
| B | Détection + alerte + allongement de fenêtre Ghost. | trafic #24, surveillants #11/#12, réponse #17 ; démo on-chain séparée des contrats Ghost #8, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) | Ghost (#8) dans la variante principale |
| C (optionnel) | Moins de pertes en aval quand la balise est lue. | `RiskBeacon` + `MockLendingMarket` #7 **et le vrai M-Ghost `GhostToken` #8** sur anvil local, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) : tout vient de la chaîne | tout, par défaut (repli automatique si Foundry absent) |
| D (optionnel) | Pertes côté protocole ≈ zéro (à vérifier) vs pertes côté spéculateurs. | vrai M-Ghost #8 + couche de règlement §10bis #84 (`SettlementRouter`, `AssetVault`, `AssetGhost`) sur anvil local, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) | tout, par défaut (pool simulé ; repli automatique si Foundry absent) |
| N1 | Zéro alerte, zéro gel. | trafic #24, surveillants #11/#12, réponse #17 | rien |
| N2 | Pas de déclenchement (volume élevé sans dispersion effondrée). | trafic #24, surveillants #11/#12, réponse #17 | rien |
| N3 | La fenêtre revient seule à la normale, aucun gel définitif. | trafic #24 (+ burst injecté), #11/#12, #17 ; démo on-chain séparée des contrats Ghost #8, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) | Ghost (#8) dans la variante principale |

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

Le même backend rejoue **C** sur la balise de risque et le faux marché de prêt de #7
(`RiskBeacon`, `MockLendingMarket`) **et sur le vrai M-Ghost `GhostToken` (#8)** : un emprunteur
légitime (Ghost propre) et l'attaquant (Ghost 100 % suspect) empruntent sur deux marchés, sans et
avec lecture de la balise, puis la garantie suspecte du marché est détruite. Le soupçon n'est plus
posé par un setter de test : il vient de la vraie chaîne de sécurité (le surveillant `delay`
l'attaquant, le soupçon **suit la valeur** jusqu'au marché au dépôt, les guardians 2/3 détruisent
la garantie suspecte détenue par le marché). Comme **tout** vient alors de la chaîne, le bandeau
« simulation hors chaîne » **disparaît** sur ce chemin (`replace_by` vide, bandeau
« implémentation réelle : #7, #8 »). Paramètres du marché : `lending_ltv` et
`beacon_ratio_threshold` de `scenarios/config.py`, décotes du test de #7 (provisoires).

### Rejouer D sur les vrais contrats (anvil, #110)

Par défaut, **D** rejoue la revente du Ghost suspect à un **pool simulé** (produit constant,
`sim_contracts.ConstantProductPool`), bandeau « simulation hors chaîne, à remplacer par #8, #25,
#84 ». Avec le même opt-in (`SH_DEMO_CONTRACTS_BACKEND=anvil`), D est rejoué sur le **vrai M-Ghost
`GhostToken` (#8) + la couche de règlement §10bis (#84 : `SettlementRouter`, `AssetVault`,
`AssetGhost`)** (`scenarios/real_settlement.py`), avec repli automatique sur la simulation :

```bash
# Foundry v1.8.5 + contracts/lib installé (voir ci-dessus), puis :
SH_DEMO_CONTRACTS_BACKEND=anvil python -m dashboard.demo run D
```

Le cas rejoué est le **§10bis cas 2bis** (prix qui montent), modelé sur
`contracts/test/ScenarioSettlement.t.sol` : le voleur vend son M' frauduleux à un intermédiaire
via le routeur (l'acheteur bloque du vrai USDC au coffre, le voleur ne reçoit que du **Ghost de
paiement**), l'intermédiaire le revend plus cher à l'acheteur final (M' devenu « pur »), puis la
destruction 2/3 brûle le M' suspect, brûle le Ghost de paiement du voleur et restitue à l'acheteur
final l'argent bloqué du voleur par racine de Merkle. Lectures on-chain : **perte protocole = 0**
(aucun vrai M émis contre du suspect, §10bis), **perte spéculateur > 0** (la marge que l'acheteur
final a payée au-dessus de l'argent bloqué du voleur), le **voleur garde 0**, le coffre est vidé.
Comme tout vient de la chaîne sur ce chemin, le bandeau devient « implémentation réelle : #8, #84 ».
Si Foundry ou `contracts/lib` manquent, ou si le rejeu échoue, D retombe sur le pool simulé et le
message le dit (la CI ne dépend jamais d'anvil).

### Démontrer la partie Ghost de B et N3 sur les vrais contrats (anvil, #110)

Par défaut, la partie **Ghost** (#8) de B et N3 reste **simulée** (`GhostLedger`, bandeau
« simulation hors chaîne ») : friction, quarantaine, destruction et conversion de la variante
principale sont des chiffres du modèle Python. Avec le même opt-in que A
(`SH_DEMO_CONTRACTS_BACKEND=anvil`), on **ajoute une VARIANTE séparée `ghost-onchain`** qui
**démontre** les contrats Token Ghost `GhostToken` / `ProtectedMinter` / `GuardianActions` /
`GhostedStable` (#8) sur une chaîne anvil locale et jetable (`scenarios/real_ghost.py`) :

```bash
# Foundry v1.8.5 dans le PATH ou ~/.foundry/bin + contracts/lib installé (voir ci-dessus), puis :
SH_DEMO_CONTRACTS_BACKEND=anvil python -m dashboard.demo run B    # idem N3
```

**Honnêteté (docs/CLAIMS.md) — on n'annonce « réel » que ce qu'on mesure sur la chaîne :**

- la variante `ghost-onchain` joue une **séquence FIXE de démonstration**, à **montants fictifs**,
  **INDÉPENDANTE de la seed et du trafic simulé** : ce n'est PAS un rejeu du scénario de la seed.
  Son message le dit explicitement ; ses grandeurs portent la source « implémentation réelle (#8) » ;
- la **variante principale `main` reste inchangée** : ses chiffres Ghost viennent toujours du
  `GhostLedger` simulé, donc **#8 reste dans `replace_by`** et le bandeau « simulation hors chaîne,
  à remplacer par #8 » est **conservé**. #8 ne sortirait de `replace_by` que si TOUS les chiffres
  Ghost affichés venaient de la chaîne — ce qui n'est pas le cas tant que la détection/réponse
  nourrit la variante principale avec le ledger simulé ;
- le message ne parle de la seed que pour la partie simulée.

**Pourquoi une séquence fixe plutôt qu'un rejeu piloté par la seed ?** Piloter le rejeu on-chain
par les lots Ghost du run simulé de la seed demanderait des dizaines de transactions
(chaque mint d'attaque + chaque saut de contagion du générateur #24) et ferait dépasser le budget
mémoire et la cible de ~60 s du test anvil. On retient donc la **séquence fixe honnêtement
étiquetée** : elle démontre les mécanismes du contrat (émission, soupçon, contagion, destruction
2/3, conversion) sans se faire passer pour une mesure du scénario.

Si Foundry ou `contracts/lib` manquent, ou si le rejeu échoue, la variante `ghost-onchain` n'est
simplement **pas ajoutée** (repli automatique) : la CI ne dépend jamais d'anvil. Les grandeurs
lues on-chain (Ghost détruit, M converti, `supplyValue`, réserve) sont des **comptages** sur une
chaîne locale, pas des mesures du contrat déployé.

**Correspondance simulé → réel** (ce que `GhostLedger` modélise ↔ l'appel réel sur le `GhostToken`
dans la variante `ghost-onchain`) :

| Simulé (`sim_contracts.GhostLedger`)                     | Réel (contrats #8 sur anvil)                                             |
|----------------------------------------------------------|--------------------------------------------------------------------------|
| `credit(addr, montant, ratio)` d'un lot de Ghost         | `ProtectedMinter.requestSwap` + `completeSwap(id)` → `issueFromMinter`   |
| ratio de soupçon par lot (1,0 attaque / 0,0 légitime)    | `delay(accounts, suspectAmounts, W)` du surveillant (`WATCHER_ROLE`) : sème `Sp` |
| `transfer(...)` : saut de contagion, ratio conservé      | `ghost.transfer(from, to, montant)` (ERC-20) : le soupçon suit la valeur |
| `hold(addr, until)` : retard de la conversion            | fenêtre allongée posée par `delay` (`extendedUntil`)                     |
| audit humain confirme → `burn(addr, ratio)`              | `proposeDestroy(incidentId, targets)` (guardian1) + `approveAction` (guardian2) : **2/3** |
| avance du temps au-delà de `window`                      | `evm_increaseTime` + `evm_mine`                                          |
| `convert_after_window(...)` : conversion 1:1             | `ghost.convert(montant)` par les légitimes                              |

- **B** (séquence fixe) : le minter protégé émet du Ghost à l'attaquant et à des légitimes ;
  l'attaquant fait circuler son Ghost (un saut de contagion) ; le surveillant retarde les
  suspects ; les guardians confirment la destruction 2/3 ; on passe `W` ; les légitimes
  convertissent. Lectures : Ghost détruit > 0, M converti par l'attaquant = 0 (soupçon détruit),
  M converti par les légitimes > 0.
- **N3** (séquence fixe) : un légitime reçoit du Ghost ; le surveillant retarde **sans soupçon**
  (`delay(sink, 0, W)`, conversion suspendue mais rien marqué suspect) ; aucune confirmation 2/3 ;
  la fenêtre revient seule à la normale ; le légitime convertit. Lectures : aucune destruction,
  conversion après le retour > 0.
- Une **offre de fond** légitime (10 000 Ghost, comme `dave` dans `GhostWatcher.t.sol`) est émise
  d'abord : sans elle, retarder le seul porteur dépasserait le budget de quarantaine (2000 bps).

Le job CI `scenario A (anvil)` exécute aussi les tests anvil de B/N3, **de C et de D**
(`dashboard/tests/test_scenarios_real_*.py`, sélectionnés par `-k "real_anvil"`), dont un test
qui **verrouille l'honnêteté** : tant qu'un chiffre Ghost de la variante principale est simulé, #8
doit rester dans `replace_by`. Il vérifie aussi que les bandeaux on-chain de C (« implémentation
réelle : #7, #8 ») et de D (« implémentation réelle : #8, #84 ») apparaissent bien.

À garder en tête :

- **Rapport d'incident DORA (#15, #113)** : sur l'alerte d'attaque confirmée par le multisig, le
  scénario B appelle `llm.report.build_incident_report` avec les vraies actions et le vrai journal
  de l'orchestrateur (`scenarios/real_report.py`). Hors ligne par défaut (faux client, aucun
  appel AWS, déterministe) ; Bedrock réel avec `LLM_LIVE=1` (un seul appel, via le limiteur).
  Affichage : `python -m dashboard.demo run B --report`, ou l'encadré « Rapport d'incident DORA »
  de la page.

- B, N1, N2, N3 appellent le **vrai** code (`scenarios/real_pipeline.py`) : `data.generate`
  (#24), `detection.detector.RuleBasedMonitor` (#11, #12) aux seuils par défaut de
  `detection/params.py`, `response.orchestrator.ResponseOrchestrator` (#17). Le Ghost (#8) et
  l'audit humain qui confirme une destruction restent simulés dans la variante principale (bandeau
  « à remplacer par #8 ») ; pour B et N3, une **variante `ghost-onchain` séparée** démontre les
  vrais contrats Ghost (#8) via `SH_DEMO_CONTRACTS_BACKEND=anvil` (séquence fixe, montants fictifs,
  indépendante de la seed ; voir « Démontrer la partie Ghost de B et N3 sur les vrais contrats »),
  sans retirer #8 de la variante principale.
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
