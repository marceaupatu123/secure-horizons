# dashboard

- **RÃ´le** : interface de **dÃ©mo** (Streamlit) : alertes, Ã©tat de la rÃ©ponse graduÃ©e
  (retarder / dÃ©truire / pause globale), quarantaine Ghost et journal d'audit.
- **PropriÃ©taire** : @marceaupatu123 (voir `docs/TEAM.md`).
- **Lancer** : `make run-dashboard` (sans make, sous Windows : `python -m streamlit run dashboard/app.py`).
- **Tests** : `python -m pytest dashboard/`.

## DÃ©coupage

- `demo_data.py` : jeu de donnÃ©es **synthÃ©tique et seedÃ©** (`DEMO_SEED`), dÃ©terministe.
  Adresses, hash et montants sont fictifs. FenÃªtres 10 min / 1 h = valeurs de dÃ©mo (Â§3.1), Ã  mesurer.
- `view_model.py` : logique pure (sans Streamlit) : Ã©tat des pÃ©rimÃ¨tres dÃ©rivÃ© des
  `ResponseAction`, compteurs de la vue d'ensemble, tableaux `pandas` avec libellÃ©s texte.
- `app.py` : rendu Streamlit uniquement. Un curseur Â« instant simulÃ© Â» montre l'expiration
  automatique d'un retard.
- `scenarios/` : moteur des scÃ©narios de dÃ©mo (#47) : modÃ¨les de rÃ©sultat, registre branchable,
  paramÃ¨tres de simulation (`config.py`), briques simulÃ©es hors chaÃ®ne (`sim_*.py`), catalogue
  des 7 scÃ©narios (`catalog.py`) et mise en tableau pure (`view.py`).
- `demo.py` : CLI `python -m dashboard.demo list|run`.
- `pages/1_Scenarios_de_demo.py` : page Streamlit Â« ScÃ©narios de dÃ©mo Â» (rendu uniquement).
- `story.py` + `pages/0_Demo_interactive.py` : **dÃ©mo interactive animÃ©e pour le pitch** (#148).
  La page rejoue rÃ©ellement A et B Ã  chaque lancement (mÃªme seed = mÃªme rÃ©sultat), puis raconte
  l'histoire en 3 onglets animÃ©s (clÃ© volÃ©e, pirate discret, bilan) avec des analogies pour
  novices. `story.py` extrait les grandeurs mesurÃ©es et produit un HTML autonome (sans ressource
  externe, respecte `prefers-reduced-motion`). C'est la page Ã  ouvrir devant un jury ou des
  investisseurs : Â« Demo interactive Â» dans la barre latÃ©rale.
- `scenarios/fuji_live.py` : **rejeu en vraies transactions sur Avalanche Fuji** (#148), premier
  onglet de la dÃ©mo interactive, racontÃ© en **5 cas jouÃ©s Ã©tape par Ã©tape dans un faux terminal**
  (chaque bouton tape et exÃ©cute une commande, l'effet renvoie Ã  la transaction Snowtrace) : (1) *le
  mint passe* â€” contrat classique, mint gonflÃ© acceptÃ© ; (2) *le mint est bloquÃ©* â€” `ProtectedMinter`,
  mint gonflÃ© rejetÃ© on-chain puis seul le dÃ©pÃ´t servi ; (3) *la fenÃªtre de reprise* â€” un Ã©change
  donne du **M-Ghost** (pas du M-Coin), converti en **M-Coin** via `convert` seulement aprÃ¨s la
  fenÃªtre de sÃ©curitÃ© (raccourcie Ã  1 s pour jouer la conversion en direct), ce qui rend la reprise
  possible ; (4) *un vendeur de Ghost pose problÃ¨me* â€” le
  Ghost est Ã©coulÃ© via le `SettlementRouter` (USDC de l'acheteur bloquÃ© au coffre, vendeur payÃ© en
  Ghost de paiement), le vendeur est signalÃ© (mÃ©thode non divulguÃ©e), les gardiens 2/3 dÃ©truisent tout
  le Ghost suspect et brÃ»lent le Ghost de paiement du vendeur (son USDC, gelÃ© faute de conversion, est
  restituÃ© Ã  l'acheteur). (5) *le pare-feu de contagion* â€” le Ghost suspect sert de collatÃ©ral sur
  deux marchÃ©s de prÃªt : le marchÃ© aveugle prÃªte puis se retrouve avec une crÃ©ance douteuse quand le
  Ghost est dÃ©truit, tandis que le marchÃ© qui lit la `RiskBeacon` refuse l'emprunt on-chain
  (`BorrowRefused`) â†’ zÃ©ro perte, la fraude ne se propage pas. Les gestes d'intendance (dÃ©pÃ´ts de
  collatÃ©ral, faucets) sont jouÃ©s mais non
  exposÃ©s. Le vrai `monitor.ChainListener` relit les mints ; la page relit l'Ã©tat on-chain Ã  chaque
  affichage. Lancer : `python -m dashboard.scenarios.fuji_live` (`forge build` dans `contracts/` +
  `GUARDIAN_PRIVATE_KEY` d'un compte de **TEST** Fuji dans `.env`). Le signal de rÃ©ponse est une rÃ¨gle
  de dÃ©mo, pas un surveillant du module `detection`.
- `scenarios/fuji_report.py` : **rapport d'incident DORA de l'incident rÃ©el Fuji** (#148). Traduit
  les vraies transactions en `Alert` / `ResponseAction` / `AuditLogEntry` partagÃ©s et appelle
  `llm.report` tel quel (hors ligne par dÃ©faut, Bedrock avec `LLM_LIVE=1`), puis ajoute un tableau de
  preuves avec un lien Snowtrace par Ã©tape. AffichÃ© (et tÃ©lÃ©chargeable) sous la dÃ©mo interactive, Ã 
  cÃ´tÃ© du rapport de l'acte 2.

Aucun chiffre affichÃ© n'est Ã©crit en dur : tout est calculÃ© Ã  partir du jeu synthÃ©tique. Ce sont
des comptages, pas des mesures de performance.

## ScÃ©narios de dÃ©mo (#47)

Forme retenue : **CLI + page Streamlit du dashboard existant â€” Ã  valider en Ã©quipe**.

```bash
python -m dashboard.demo list                                   # catalogue
python -m dashboard.demo run A --seed 20 [--json] [--disable C] # rejoue un scÃ©nario
make demo ARGS="run B"                                          # idem via make
make run-dashboard                                              # page Â« ScÃ©narios de dÃ©mo Â» dans la barre latÃ©rale
```

MÃªme seed = mÃªme rÃ©sultat (JSON identique). Un scÃ©nario optionnel dÃ©sactivÃ© (`--disable C`, ou
case dÃ©cochÃ©e sur la page) affiche Â« dÃ©sactivÃ© Â» sans aucune mÃ©trique ; un scÃ©nario dont la
brique n'est pas disponible afficherait Â« non disponible (dÃ©pend de #X) Â».

| ScÃ©nario | Attendu (issue #47) | BranchÃ© sur le vrai code (#70) | Encore simulÃ© |
|----------|---------------------|--------------------------------|---------------|
| A | Le vulnÃ©rable se fait vider, le protÃ©gÃ© borne la perte. | contrats Foundry #4/#5 sur anvil local, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) | tout, par dÃ©faut (repli automatique si Foundry absent) |
| B | DÃ©tection + alerte + allongement de fenÃªtre Ghost. | trafic #24, surveillants #11/#12, rÃ©ponse #17 ; dÃ©mo on-chain sÃ©parÃ©e des contrats Ghost #8, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) | Ghost (#8) dans la variante principale |
| C (optionnel) | Moins de pertes en aval quand la balise est lue. | `RiskBeacon` + `MockLendingMarket` #7 **et le vrai M-Ghost `GhostToken` #8** sur anvil local, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) : tout vient de la chaÃ®ne | tout, par dÃ©faut (repli automatique si Foundry absent) |
| D (optionnel) | Pertes cÃ´tÃ© protocole â‰ˆ zÃ©ro (Ã  vÃ©rifier) vs pertes cÃ´tÃ© spÃ©culateurs. | vrai M-Ghost #8 + couche de rÃ¨glement Â§10bis #84 (`SettlementRouter`, `AssetVault`, `AssetGhost`) sur anvil local, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) | tout, par dÃ©faut (pool simulÃ© ; repli automatique si Foundry absent) |
| N1 | ZÃ©ro alerte, zÃ©ro gel. | trafic #24, surveillants #11/#12, rÃ©ponse #17 | rien |
| N2 | Pas de dÃ©clenchement (volume Ã©levÃ© sans dispersion effondrÃ©e). | trafic #24, surveillants #11/#12, rÃ©ponse #17 | rien |
| N3 | La fenÃªtre revient seule Ã  la normale, aucun gel dÃ©finitif. | trafic #24 (+ burst injectÃ©), #11/#12, #17 ; dÃ©mo on-chain sÃ©parÃ©e des contrats Ghost #8, **opt-in** (`SH_DEMO_CONTRACTS_BACKEND=anvil`) | Ghost (#8) dans la variante principale |

### Rejouer A sur les vrais contrats (anvil)

```bash
# Foundry v1.8.5 (mÃªme version que la CI) dans le PATH ou ~/.foundry/bin, puis :
cd contracts && forge install --no-git foundry-rs/forge-std@v1.17.0 OpenZeppelin/openzeppelin-contracts@v5.4.0 && cd ..
SH_DEMO_CONTRACTS_BACKEND=anvil python -m dashboard.demo run A        # PowerShell : $env:SH_DEMO_CONTRACTS_BACKEND="anvil"
SH_DEMO_CONTRACTS_BACKEND=anvil make run-dashboard
```

Une chaÃ®ne anvil jetable est lancÃ©e sur `127.0.0.1` (port libre), `MockUSDC`, `VulnerableMinter` et
`ProtectedMinter` y sont dÃ©ployÃ©s, et l'attaque de `contracts/test/ScenarioA.t.sol` est rejouÃ©e
avec les comptes **dÃ©verrouillÃ©s** d'anvil (aucune clÃ© privÃ©e manipulÃ©e). Si Foundry manque ou si
le rejeu Ã©choue, A retombe sur la simulation et le message le dit. Le job CI `scenario A (anvil)`
rejoue ce chemin sur chaque PR.

Le mÃªme backend rejoue **C** sur la balise de risque et le faux marchÃ© de prÃªt de #7
(`RiskBeacon`, `MockLendingMarket`) **et sur le vrai M-Ghost `GhostToken` (#8)** : un emprunteur
lÃ©gitime (Ghost propre) et l'attaquant (Ghost 100 % suspect) empruntent sur deux marchÃ©s, sans et
avec lecture de la balise, puis la garantie suspecte du marchÃ© est dÃ©truite. Le soupÃ§on n'est plus
posÃ© par un setter de test : il vient de la vraie chaÃ®ne de sÃ©curitÃ© (le surveillant `delay`
l'attaquant, le soupÃ§on **suit la valeur** jusqu'au marchÃ© au dÃ©pÃ´t, les guardians 2/3 dÃ©truisent
la garantie suspecte dÃ©tenue par le marchÃ©). Comme **tout** vient alors de la chaÃ®ne, le bandeau
Â« simulation hors chaÃ®ne Â» **disparaÃ®t** sur ce chemin (`replace_by` vide, bandeau
Â« implÃ©mentation rÃ©elle : #7, #8 Â»). ParamÃ¨tres du marchÃ© : `lending_ltv` et
`beacon_ratio_threshold` de `scenarios/config.py`, dÃ©cotes du test de #7 (provisoires).

### Rejouer D sur les vrais contrats (anvil, #110)

Par dÃ©faut, **D** rejoue la revente du Ghost suspect Ã  un **pool simulÃ©** (produit constant,
`sim_contracts.ConstantProductPool`), bandeau Â« simulation hors chaÃ®ne, Ã  remplacer par #8, #25,
#84 Â». Avec le mÃªme opt-in (`SH_DEMO_CONTRACTS_BACKEND=anvil`), D est rejouÃ© sur le **vrai M-Ghost
`GhostToken` (#8) + la couche de rÃ¨glement Â§10bis (#84 : `SettlementRouter`, `AssetVault`,
`AssetGhost`)** (`scenarios/real_settlement.py`), avec repli automatique sur la simulation :

```bash
# Foundry v1.8.5 + contracts/lib installÃ© (voir ci-dessus), puis :
SH_DEMO_CONTRACTS_BACKEND=anvil python -m dashboard.demo run D
```

Le cas rejouÃ© est le **Â§10bis cas 2bis** (prix qui montent), modelÃ© sur
`contracts/test/ScenarioSettlement.t.sol` : le voleur vend son M' frauduleux Ã  un intermÃ©diaire
via le routeur (l'acheteur bloque du vrai USDC au coffre, le voleur ne reÃ§oit que du **Ghost de
paiement**), l'intermÃ©diaire le revend plus cher Ã  l'acheteur final (M' devenu Â« pur Â»), puis la
destruction 2/3 brÃ»le le M' suspect, brÃ»le le Ghost de paiement du voleur et restitue Ã  l'acheteur
final l'argent bloquÃ© du voleur par racine de Merkle. Lectures on-chain : **perte protocole = 0**
(aucun vrai M Ã©mis contre du suspect, Â§10bis), **perte spÃ©culateur > 0** (la marge que l'acheteur
final a payÃ©e au-dessus de l'argent bloquÃ© du voleur), le **voleur garde 0**, le coffre est vidÃ©.
Comme tout vient de la chaÃ®ne sur ce chemin, le bandeau devient Â« implÃ©mentation rÃ©elle : #8, #84 Â».
Si Foundry ou `contracts/lib` manquent, ou si le rejeu Ã©choue, D retombe sur le pool simulÃ© et le
message le dit (la CI ne dÃ©pend jamais d'anvil).

### DÃ©montrer la partie Ghost de B et N3 sur les vrais contrats (anvil, #110)

Par dÃ©faut, la partie **Ghost** (#8) de B et N3 reste **simulÃ©e** (`GhostLedger`, bandeau
Â« simulation hors chaÃ®ne Â») : friction, quarantaine, destruction et conversion de la variante
principale sont des chiffres du modÃ¨le Python. Avec le mÃªme opt-in que A
(`SH_DEMO_CONTRACTS_BACKEND=anvil`), on **ajoute une VARIANTE sÃ©parÃ©e `ghost-onchain`** qui
**dÃ©montre** les contrats Token Ghost `GhostToken` / `ProtectedMinter` / `GuardianActions` /
`GhostedStable` (#8) sur une chaÃ®ne anvil locale et jetable (`scenarios/real_ghost.py`) :

```bash
# Foundry v1.8.5 dans le PATH ou ~/.foundry/bin + contracts/lib installÃ© (voir ci-dessus), puis :
SH_DEMO_CONTRACTS_BACKEND=anvil python -m dashboard.demo run B    # idem N3
```

**HonnÃªtetÃ© (docs/CLAIMS.md) â€” on n'annonce Â« rÃ©el Â» que ce qu'on mesure sur la chaÃ®ne :**

- la variante `ghost-onchain` joue une **sÃ©quence FIXE de dÃ©monstration**, Ã  **montants fictifs**,
  **INDÃ‰PENDANTE de la seed et du trafic simulÃ©** : ce n'est PAS un rejeu du scÃ©nario de la seed.
  Son message le dit explicitement ; ses grandeurs portent la source Â« implÃ©mentation rÃ©elle (#8) Â» ;
- la **variante principale `main` reste inchangÃ©e** : ses chiffres Ghost viennent toujours du
  `GhostLedger` simulÃ©, donc **#8 reste dans `replace_by`** et le bandeau Â« simulation hors chaÃ®ne,
  Ã  remplacer par #8 Â» est **conservÃ©**. #8 ne sortirait de `replace_by` que si TOUS les chiffres
  Ghost affichÃ©s venaient de la chaÃ®ne â€” ce qui n'est pas le cas tant que la dÃ©tection/rÃ©ponse
  nourrit la variante principale avec le ledger simulÃ© ;
- le message ne parle de la seed que pour la partie simulÃ©e.

**Pourquoi une sÃ©quence fixe plutÃ´t qu'un rejeu pilotÃ© par la seed ?** Piloter le rejeu on-chain
par les lots Ghost du run simulÃ© de la seed demanderait des dizaines de transactions
(chaque mint d'attaque + chaque saut de contagion du gÃ©nÃ©rateur #24) et ferait dÃ©passer le budget
mÃ©moire et la cible de ~60 s du test anvil. On retient donc la **sÃ©quence fixe honnÃªtement
Ã©tiquetÃ©e** : elle dÃ©montre les mÃ©canismes du contrat (Ã©mission, soupÃ§on, contagion, destruction
2/3, conversion) sans se faire passer pour une mesure du scÃ©nario.

Si Foundry ou `contracts/lib` manquent, ou si le rejeu Ã©choue, la variante `ghost-onchain` n'est
simplement **pas ajoutÃ©e** (repli automatique) : la CI ne dÃ©pend jamais d'anvil. Les grandeurs
lues on-chain (Ghost dÃ©truit, M converti, `supplyValue`, rÃ©serve) sont des **comptages** sur une
chaÃ®ne locale, pas des mesures du contrat dÃ©ployÃ©.

**Correspondance simulÃ© â†’ rÃ©el** (ce que `GhostLedger` modÃ©lise â†” l'appel rÃ©el sur le `GhostToken`
dans la variante `ghost-onchain`) :

| SimulÃ© (`sim_contracts.GhostLedger`)                     | RÃ©el (contrats #8 sur anvil)                                             |
|----------------------------------------------------------|--------------------------------------------------------------------------|
| `credit(addr, montant, ratio)` d'un lot de Ghost         | `ProtectedMinter.requestSwap` + `completeSwap(id)` â†’ `issueFromMinter`   |
| ratio de soupÃ§on par lot (1,0 attaque / 0,0 lÃ©gitime)    | `delay(accounts, suspectAmounts, W)` du surveillant (`WATCHER_ROLE`) : sÃ¨me `Sp` |
| `transfer(...)` : saut de contagion, ratio conservÃ©      | `ghost.transfer(from, to, montant)` (ERC-20) : le soupÃ§on suit la valeur |
| `hold(addr, until)` : retard de la conversion            | fenÃªtre allongÃ©e posÃ©e par `delay` (`extendedUntil`)                     |
| audit humain confirme â†’ `burn(addr, ratio)`              | `proposeDestroy(incidentId, targets)` (guardian1) + `approveAction` (guardian2) : **2/3** |
| avance du temps au-delÃ  de `window`                      | `evm_increaseTime` + `evm_mine`                                          |
| `convert_after_window(...)` : conversion 1:1             | `ghost.convert(montant)` par les lÃ©gitimes                              |

- **B** (sÃ©quence fixe) : le minter protÃ©gÃ© Ã©met du Ghost Ã  l'attaquant et Ã  des lÃ©gitimes ;
  l'attaquant fait circuler son Ghost (un saut de contagion) ; le surveillant retarde les
  suspects ; les guardians confirment la destruction 2/3 ; on passe `W` ; les lÃ©gitimes
  convertissent. Lectures : Ghost dÃ©truit > 0, M converti par l'attaquant = 0 (soupÃ§on dÃ©truit),
  M converti par les lÃ©gitimes > 0.
- **N3** (sÃ©quence fixe) : un lÃ©gitime reÃ§oit du Ghost ; le surveillant retarde **sans soupÃ§on**
  (`delay(sink, 0, W)`, conversion suspendue mais rien marquÃ© suspect) ; aucune confirmation 2/3 ;
  la fenÃªtre revient seule Ã  la normale ; le lÃ©gitime convertit. Lectures : aucune destruction,
  conversion aprÃ¨s le retour > 0.
- Une **offre de fond** lÃ©gitime (10 000 Ghost, comme `dave` dans `GhostWatcher.t.sol`) est Ã©mise
  d'abord : sans elle, retarder le seul porteur dÃ©passerait le budget de quarantaine (2000 bps).

Le job CI `scenario A (anvil)` exÃ©cute aussi les tests anvil de B/N3, **de C et de D**
(`dashboard/tests/test_scenarios_real_*.py`, sÃ©lectionnÃ©s par `-k "real_anvil"`), dont un test
qui **verrouille l'honnÃªtetÃ©** : tant qu'un chiffre Ghost de la variante principale est simulÃ©, #8
doit rester dans `replace_by`. Il vÃ©rifie aussi que les bandeaux on-chain de C (Â« implÃ©mentation
rÃ©elle : #7, #8 Â») et de D (Â« implÃ©mentation rÃ©elle : #8, #84 Â») apparaissent bien.

Ã€ garder en tÃªte :

- **Rapport d'incident DORA (#15, #113)** : sur l'alerte d'attaque confirmÃ©e par le multisig, le
  scÃ©nario B appelle `llm.report.build_incident_report` avec les vraies actions et le vrai journal
  de l'orchestrateur (`scenarios/real_report.py`). Hors ligne par dÃ©faut (faux client, aucun
  appel AWS, dÃ©terministe) ; Bedrock rÃ©el avec `LLM_LIVE=1` (un seul appel, via le limiteur).
  Affichage : `python -m dashboard.demo run B --report`, ou l'encadrÃ© Â« Rapport d'incident DORA Â»
  de la page.

- B, N1, N2, N3 appellent le **vrai** code (`scenarios/real_pipeline.py`) : `data.generate`
  (#24), `detection.detector.RuleBasedMonitor` (#11, #12) aux seuils par dÃ©faut de
  `detection/params.py`, `response.orchestrator.ResponseOrchestrator` (#17). Le Ghost (#8) et
  l'audit humain qui confirme une destruction restent simulÃ©s dans la variante principale (bandeau
  Â« Ã  remplacer par #8 Â») ; pour B et N3, une **variante `ghost-onchain` sÃ©parÃ©e** dÃ©montre les
  vrais contrats Ghost (#8) via `SH_DEMO_CONTRACTS_BACKEND=anvil` (sÃ©quence fixe, montants fictifs,
  indÃ©pendante de la seed ; voir Â« DÃ©montrer la partie Ghost de B et N3 sur les vrais contrats Â»),
  sans retirer #8 de la variante principale.
- **Profil de trafic lÃ©gitime** : la dÃ©mo utilise le profil Â« petits transferts Â» (1â€“10 % du
  solde, `data/DECISION_SUPPORT_3.md` Â§2), Ã  valider en Ã©quipe. Avec le profil Â« gros
  transferts Â» du gÃ©nÃ©rateur (5â€“50 %), le mÃªme surveillant lÃ¨ve 1 faux positif sur N1 (seed 20) :
  c'est une mesure Ã  montrer, pas Ã  cacher. Changer `real_transfer_fraction_*` dans
  `scenarios/config.py` pour la reproduire.
- Les paramÃ¨tres de `scenarios/config.py` (volumes, dÃ©lais) sont des valeurs de dÃ©part
  **Ã  calibrer** (`docs/OPEN_QUESTIONS.md` Â§6) : aucun seuil n'est actÃ©.
- Les grandeurs affichÃ©es sont des **comptages** sur trafic synthÃ©tique ou chaÃ®ne locale, pas des
  mesures du contrat dÃ©ployÃ© (cf. `docs/CLAIMS.md`). Les Â« attendus Â» sont constatÃ©s
  (`OK` / `KO`), pas garantis.

Brancher une vraie implÃ©mentation : remplacer, dans `scenarios/catalog.py`, le `runner` du
`ScenarioSpec` concernÃ© par une fonction `(seed, params) -> ScenarioResult` qui appelle le vrai
module, et retirer son numÃ©ro de `REPLACE_BY` (le bandeau Â« simulation hors chaÃ®ne Â» disparaÃ®t
dÃ¨s qu'il ne reste plus de brique simulÃ©e). `scenarios.registry.register` sert Ã  ajouter un
**nouvel** id : il refuse un id dÃ©jÃ  enregistrÃ©. Un runner qui lÃ¨ve `NotImplementedError` donne
automatiquement Â« non disponible (dÃ©pend de #X) Â». La CLI et la page n'ont pas Ã  changer.

## ModÃ¨les `shared/` consommÃ©s

`Alert`, `AlertSeed`, `AlertKind`, `AlertSeverity`, `ResponseAction`, `ResponseActionType`,
`ResponseActionStatus`, `AuditLogEntry`, `QuarantineRecord`, `QuarantineStatus`,
`RiskBeaconUpdate`, `BeaconRiskLevel`, `ReleaseDecision`, `ReleaseVerdict`,
`GhostTokenMintEvent`, `GhostTokenRedemptionEvent`, `GhostTokenBurnEvent`.

L'Ã©tat d'un pÃ©rimÃ¨tre (`PerimeterState`) est une enum **locale** : `shared/` n'en dÃ©finit pas.
