# AUDIT.md — audit de cohérence avant le pitch

> Audit **en lecture seule** du dépôt, fait le 2026-10-11 sur `origin/main` au commit `ce2beaa`
> (tests et rejeux). Pendant l'audit, `main` est passé à `891f14c` (PR #155, README seul) : le
> README a été relu sur ce commit, le reste n'a pas changé.
> Aucun code ni fichier existant n'a été modifié : ce fichier est le seul ajout.
> Fait par un assistant IA (Claude) pour @Yannis1307. Tout ce qui suit est **à relire par les
> propriétaires** : quand un point n'a pas pu être vérifié, c'est écrit.

## Résumé (5 lignes)

1. **Les chiffres de faux positifs du pitch ne ressortent plus.** `make calibrate` (seed 42) relancé
   sur `main` donne, au profil « gros transferts », **7 / 864** à z = 2/2 (le pitch dit 5) et
   **1 / 864** à z volume = 6 (le pitch dit 0). Règle de l'équipe : aucun chiffre non mesuré.
2. **Faille dans le routeur §10bis** : n'importe qui peut prendre le M' qu'un vendeur a approuvé au
   routeur, **au prix qu'il choisit** (1 unité, ou 0 via `sellPure`). Vérifié par un test jetable.
3. **La chaîne détection → réponse n'agit pas sur la chaîne.** `response/` est un miroir hors
   chaîne ; dans la démo B, la partie « vrais contrats » est une séquence fixe, indépendante des
   alertes. Rien n'est déployé sur Fuji. Le pitch le dit en partie : il faut le dire précisément.
4. Le reste : textes « sous les plafonds » contraires à une décision, `CLAIMS.md` en retard sur le
   code, README et pitch qui présentent des propositions non actées, décimales 6 / 18 mélangées.
5. Tests : **pytest 477 OK, 2 échecs (encodage Windows seulement), 6 ignorés** ; **forge 246 OK, 0 échec**.

## Méthode et limites de cet audit

- **Lu en entier** : `CLAUDE.md`, `README.md`, `docs/OPEN_ANSWERS.md`, `docs/CLAIMS.md`,
  `docs/TEAM.md`, `.github/` (CI, CODEOWNERS), `livrables/SCRIPT_PITCH.md`,
  `livrables/DEFENSE_SHEET.md`, `docs-site/promesses-jury.mdx`, tous les contrats de
  `contracts/src/` (sauf `MaturityBuckets.sol` et `MockUSDC.sol`), `detection/params.py`,
  `dashboard/scenarios/real_ghost.py`, les points d'entrée `__main__.py`.
- **Parcouru par recherches ciblées, pas ligne à ligne** : `docs/CONTRACTS.md`,
  `docs/OPEN_QUESTIONS.md`, `docs/ROADMAP.md`, `docs-site/` (autres pages), `.kiro/steering/`,
  `shared/models.py`, `monitor/`, `detection/` (autres fichiers), `response/`, `llm/`, `data/`,
  `dashboard/` (autres fichiers), les tests. Un problème peut donc m'avoir échappé dans ces fichiers.
- **Exécuté** : `pytest` complet, `forge build` + `forge test`, `python -m dashboard.demo run` pour
  A, B, C, D, N1, N2, N3 (simulation et anvil), `python -m data.calibrate --seed 42`,
  `python -m data.late_marking`.
- **Machine** : Windows 11, Python 3.12.10, Foundry 1.5.1 (la CI utilise Python 3.11 et une autre
  version de Foundry). Les chiffres relancés sont donc **à confirmer** sur la machine de démo.
- **GitHub** : PR et issues ouvertes lues ; les PR fermées n'ont été vérifiées que pour celles citées
  dans `CLAIMS.md`.

## Tableau des constats (triés par gravité)

Propriétaires d'après `docs/TEAM.md` / `.github/CODEOWNERS`.

| # | Gravité | Où | Ce qui ne va pas | Propriétaire |
|---|---------|----|------------------|--------------|
| C1 | **CRITIQUE** | `docs/CLAIMS.md` (ligne « taux de faux positifs »), `data/DECISION_SUPPORT_3.md` l.16 et l.40, `livrables/SCRIPT_PITCH.md` slide 5 + questions, `livrables/DEFENSE_SHEET.md` §4 | Les faux positifs annoncés (5 puis 0) ne sont pas ceux que la commande produit aujourd'hui (7 puis 1) | `data` @EnzoFB06, `docs` @marceaupatu123 |
| C2 | **CRITIQUE** | `contracts/src/SettlementRouter.sol` l.52-68 (`buyWithAsset`) et l.73-88 (`sellPure`) | Le vendeur ne valide ni l'acheteur ni le prix : un tiers vide son allowance | `contracts` @denybs |
| C3 | **CRITIQUE** | `response/orchestrator.py` l.25-28, `detection/pipeline.py` l.5, `dashboard/scenarios/real_ghost.py`, `contracts/DEPLOYMENTS.md` | Aucune alerte ne déclenche un `delay()` on-chain ; rien sur Fuji ; pas de script de déploiement | `response` @EnzoFB06, `dashboard` @marceaupatu123, `monitor`/`detection` @Yannis1307 |
| M1 | MAJEUR | `dashboard/scenarios/catalog.py` l.1125, `dashboard/story.py` l.269, `dashboard/scenarios/config.py` l.90-91, `SCRIPT_PITCH.md` l.70, `DEFENSE_SHEET.md` l.16 | « Attaquant sous les plafonds » alors que la décision dit « pas de plafond fixe » | `dashboard` @marceaupatu123, `docs` |
| M2 | MAJEUR | `docs/CLAIMS.md`, `docs-site/promesses-jury.mdx` | Statuts « en attente de #8 / #111 / #112 » alors que tout est mergé ; site : tout « à mesurer » | `docs` @marceaupatu123 |
| M3 | MAJEUR | `contracts/src/GhostToken.sol` l.351 (`initRouting`), `dashboard/scenarios/real_ghost.py` (`_deploy_world`), `real_contracts.py`, `real_settlement.py` | Le routage §10bis-router (option b′) n'est jamais activé dans la démo | `dashboard` @marceaupatu123, `contracts` @denybs |
| M4 | MAJEUR | `data/generate.py` l.84 (`TOKEN_DECIMALS = 6`) vs `contracts/src/ProtectedMinter.sol` l.33 (M à 18 décimales) ; sortie du scénario B | M a 6 décimales dans les données et 18 dans les contrats ; les deux échelles sont affichées côte à côte | `data` @EnzoFB06, `dashboard` @marceaupatu123 |
| M5 | MAJEUR | `SCRIPT_PITCH.md` slide 7 vs `OPEN_ANSWERS.md` §10bis point 8 et « options écartées » vs §0 | Le pitch annonce une commission + un fonds d'assurance ; §10bis dit « aucun frais » et écarte ce fonds | décision d'équipe, `docs` @marceaupatu123 |
| M6 | MAJEUR | `detection/params.py` (`BASELINE_PERIOD_SECONDS = 86_400`, `MIN_HISTORY_SLOTS = 5`, `DEMO_MIN_HISTORY_SLOTS = 12`, `SLOT_SECONDS = 300`) | En direct, aucune alerte avant 1 h de trafic (profil `demo`) ou 5 jours (profil par défaut) | `detection` @Yannis1307 |
| M7 | MAJEUR | `monitor/protected.py` l.73-91, `monitor/listener.py` l.750-757, `monitor/README.md` l.86 | Le monitor ne lit les événements d'administration que sur le minter, pas sur le Ghost | `monitor` @Yannis1307 |
| M8 | MAJEUR | `contracts/src/ProtectedMinter.sol` l.38-41 et l.166-175, `GhostToken.sol` l.225 | Une seule clé `admin` : taux modifiable par pas de 5 % enchaînables, rôle surveillant donné ou retiré sans délai | `contracts` @denybs |
| M9 | MAJEUR | `dashboard/scenarios/real_report.py` l.48-49, `.env.example` (`BEDROCK_MODEL_ID` « à confirmer ») | Le « rapport d'incident » de la démo vient d'un bouchon hors ligne sauf si `LLM_LIVE=1` | `llm` @denybs, `dashboard` @marceaupatu123 |
| M10 | MAJEUR | `README.md` §1 (après #155, l.40-46), `docs/GHOST_MARKET_SEIZURE.md` | Le README présente comme acquis « séquestre à la source, lignée d'origine, saisie » : c'est une **proposition** non actée, absente des contrats | `docs` @marceaupatu123, `data` @EnzoFB06 |
| m1 | MINEUR | `data/tests/test_calibrate.py`, `data/tests/test_late_marking.py` | 2 tests échouent sous Windows (encodage), passent avec `PYTHONUTF8=1` | `data` @EnzoFB06 |
| m2 | MINEUR | `contracts/src/GhostToken.sol` l.681-683, `AssetVault.sol` l.132-137 | Destruction par racine de Merkle non implémentée côté Ghost ; aucune période de contestation côté coffre | `contracts` @denybs |
| m3 | MINEUR | `contracts/src/SettlementRouter.sol` l.110-116, `interfaces/ISettlementTypes.sol` | Le statut `CHEQUE` existe mais n'est jamais écrit ; un don donne `PUR` | `contracts` @denybs |
| m4 | MINEUR | `response/orchestrator.py` (verdict `release`), `GhostToken.sol` l.95 | Le miroir Python peut lever un retard ; le contrat ne raccourcit jamais une fenêtre. Pas de budget de quarantaine côté Python | `response` @EnzoFB06 |
| m5 | MINEUR | sortie de `python -m dashboard.demo run B` avec anvil | Bandeau « simulation hors chaîne, à remplacer par #8 » affiché au-dessus d'un bloc « vrais contrats #8 » | `dashboard` @marceaupatu123 |
| m6 | MINEUR | `shared/config.py` l.70 | `GUARDIAN_PRIVATE_KEY` est obligatoire mais aucun module ne s'en sert | `shared` @marceaupatu123 |
| m7 | MINEUR | `.kiro/steering/module-detection.md` l.13, `.kiro/steering/module-shared.md` l.13, `docs-site/modules/contracts.mdx` l.12, `contracts/README.md` l.408, `monitor/README.md` l.62, `contracts/test/ScenarioSettlement.t.sol` l.14-15, `CLAUDE.md` | Phrases en retard sur le code ou sur les décisions | `docs` @marceaupatu123 + propriétaires |
| m8 | MINEUR | `detection/conformal.py`, `OPEN_ANSWERS.md` §0 | Prédiction conforme « écartée » mais présente dans le code (non branchée, déjà signalée dans `docs-site`) | `detection` @Yannis1307 |
| m9 | MINEUR | `detection/params.py` (z = 3 / 3), `data/DECISION_SUPPORT_3.md` (proposé : 6 / 3), issue #3 ouverte | Les seuils de la démo ne sont pas ceux proposés ; aucun n'est acté | `detection` @Yannis1307, `data` @EnzoFB06 |
| m10 | MINEUR | PR #153 (Streamlit Cloud) | Sans Foundry, tous les scénarios retombent sur la simulation | `dashboard` @marceaupatu123 |

## Détail des constats

### C1 — Les faux positifs annoncés ne sont pas reproduits (CRITIQUE)

- **Constat.** `python -m data.calibrate --seed 42` relancé sur `main`, profil `gros_transferts`,
  colonne « FP / tranches » :

  | z volume | z HHI | Mesuré aujourd'hui | Ce que disent les docs |
  |----------|-------|--------------------|------------------------|
  | 2 | 2 | **7 / 864** | 5 (`CLAIMS.md`, pitch, defense sheet) |
  | 3 | 3 (défaut du code) | **2 / 864** | non cité |
  | 6 | 2, 3 ou 4 | **1 / 864** | 0 « à partir de z volume = 6 » |

  Le profil `petits_transferts` donne bien **0 / 864** partout. La friction (3,2 % / 5,7 % à
  10 min ; 1,6 % / 3,2 % à 5 min) ressort à l'identique.
- **Autre écart, même ligne de `CLAIMS.md`** : « plus petite attaque vue avant conversion = 0,5 %
  […] marge ~5 min ». Mesuré : à 0,5 % (petits transferts) la marge est **+0,1 min** ; elle vaut
  ~5 min à partir de 2 %.
- **Cause probable (non vérifiée)** : `data/DECISION_SUPPORT_3.md` a été écrit avant des changements
  de `detection/` et `data/` mergés ensuite.
- **Réserve** : mesuré sous Windows / Python 3.12. À relancer sur la machine de démo avant de
  corriger.
- **Pourquoi c'est grave.** La slide 5 dit « chaque chiffre sort d'une commande du dépôt, rejouable ».
  Un juré qui relance la commande trouve autre chose.
- **Correction.** Relancer `make calibrate`, puis corriger `CLAIMS.md`, `DECISION_SUPPORT_3.md`,
  la slide 5, la réponse « Vos faux positifs ? » et le tableau §4 de la defense sheet.
  `CLAIMS.md` le prévoit déjà : « corriger ce tableau, pas les chiffres ».

### C2 — Le routeur laisse un tiers fixer le prix (CRITIQUE)

- **Constat.** `buyWithAsset(seller, mGhostAmount, asset, assetAmount)` et
  `sellPure(seller, mGhostAmount, paymentGhost, paymentAmount)` sont appelées par l'**acheteur**.
  Le contrat vérifie seulement que le vendeur a donné une allowance de M' au routeur. Rien ne dit
  que le vendeur accepte cet acheteur ni ce prix.
- **Vérifié.** Test Foundry jetable (non commité) : un vendeur approuve 1 000 M' au routeur ; un
  inconnu appelle `buyWithAsset(vendeur, 1000 M', USDC, 1)` et reçoit tout pour 1 unité d'USDC ;
  même résultat avec `sellPure(vendeur, 1000 M', 0x0, 0)` pour **zéro**. Les deux tests passent.
- **Pourquoi c'est grave.** Ici pas besoin de clé volée : toute personne qui prépare une vente peut
  se faire prendre son M'. Un juré sécurité qui lit le contrat le voit vite. Le scénario D passe
  par ce routeur.
- **Correction.** Faire valider l'offre par le vendeur : soit le vendeur enregistre une offre
  (acheteur, montant, actif, prix) que l'achat doit respecter, soit une signature du vendeur.
  Ajouter le test. Si ce n'est pas faisable avant le pitch : le dire comme limite (voir plus bas).

### C3 — La détection ne commande aucun contrat (CRITIQUE pour ce qu'on dit, pas pour le code)

- **Constat.**
  - `response/orchestrator.py` se décrit lui-même comme un « miroir hors chaîne » ; aucun module
    hors `monitor/` n'utilise `web3`. Aucune alerte n'appelle `GhostToken.delay()`.
  - `detection/pipeline.py` : « Aucune intégration avec `response/` ici ». Le seul endroit où
    détection, réponse et rapport sont reliés est le dashboard (rejeu de trafic synthétique).
  - Scénario B avec anvil : le message affiché dit lui-même « séquence fixe […] INDÉPENDANTE de la
    seed et du trafic simulé ». Le `delay` on-chain est lancé par le script, pas par l'alerte.
  - `contracts/DEPLOYMENTS.md` : tableau vide. Pas de dossier `contracts/script/`.
- **Pourquoi ça compte.** La slide 4 dit « la réponse retarde uniquement le périmètre suspect […]
  le Ghost suspect est détruit ». C'est vrai dans la simulation ; sur les vrais contrats c'est une
  démonstration séparée. La slide 8 dit déjà « pas de déploiement Fuji ».
- **Correction.** Pas de correctif rapide. Dire la phrase exacte (voir « À dire au jury »).

### M1 — « Sous les plafonds » contredit une décision

- `OPEN_ANSWERS.md` §0 : « Pas de plafond fixe par opération ». §1 : le scénario « l'attaquant
  reste sous les plafonds » « n'a plus de sens » (#49). `data/README.md` l.39 et
  `docs-site/le-parcours-dune-attaque.mdx` l.104 sont déjà corrigés.
- Restent : titre du scénario B (`catalog.py` l.1125), page animée (`story.py` l.269 : « Et si le
  pirate reste sous tous les plafonds ? »), `config.py` l.90-91 (`onchain_cap_per_tx`), pitch
  (slide 4) et defense sheet (§1).
- **Risque** : « quels plafonds ? » — le contrat n'en a aucun.
- **Correction rapide** : remplacer par « détournement à 1:1 : le contrat seul ne rejette rien ».

### M2 — `CLAIMS.md`, le site et le README sont en retard

- `CLAIMS.md` : « En attente de #8 », « En attente de #111 », « PR #112, en attente ». Les PR #111,
  #112, #120, #123, #132, #146 sont **mergées**. L'affirmation **principale** (solvabilité du Ghost)
  est encore « en attente » alors que `Ghost.invariant.t.sol::invariant_e_solvency`,
  `invariant_a_nothingOutBeforeW`, `invariant_c_suspicionConserved` et `invariant_f_watcherBounds`
  existent et passent. On se sous-vend.
- `docs-site/promesses-jury.mdx` : toutes les lignes sont « à mesurer » et le texte dit que les
  cases sont vides, alors que `CLAIMS.md` contient des chiffres.
- `README.md` : les phrases périmées (« rien n'est encore tranché », « Foundry pas encore
  initialisé ») ont été **corrigées pendant l'audit** par la PR #155 (@EnzoFB06). Voir M10 pour ce
  que cette PR a ajouté.
- **Correction rapide** : passer les lignes de `CLAIMS.md` à « vérifié par tests d'invariants » en
  citant les tests ; aligner `promesses-jury.mdx`.

### M3 — Le routage b′ n'est jamais activé dans la démo

- Décision §10bis-router : le M' non échu ne bouge que par des contrats autorisés, après
  `initRouting`. Le code existe et est testé (`contracts/test/ghost/GhostRouting.t.sol`).
- Aucun déploiement du dashboard n'appelle `initRouting`. Dans B, l'attaquant déplace son M' non
  échu par un `transfer` direct, ce que la décision interdit. `OPEN_ANSWERS.md` le liste en « reste
  ouvert ».
- **Risque** : dire « le M' ne bouge que via le routeur » alors que la démo montre l'inverse.

### M4 — Décimales 6 et 18 mélangées

- `data/generate.py` : le token M a 6 décimales. Contrats : M et M-Ghost ont 18 décimales, le
  collatéral 6.
- À l'écran, scénario B avec anvil : « Ghost suspect détruit : 200 000 000 000 base units » (6
  décimales) puis « Ghost suspect détruit (on-chain) : 100 000 000 000 000 000 000 base units
  (18 déc.) ». Même libellé, deux montants, deux échelles.
- Les surveillants travaillent en ratios : je n'ai **pas** trouvé d'erreur de calcul due à cela,
  mais je n'ai pas tout vérifié (ex. `data/ghost_ledger.py` l.59, seuil en 6 décimales).
- **Correction** : afficher les montants en unités entières avec le symbole, et préciser l'échelle.

### M5 — Modèle économique : trois versions

- §0 : marge prélevée à la conversion **dans les deux sens** (décidé).
- §10bis point 8 : « **Aucun frais de protocole** », marge « plus nécessaire » (à confirmer) ; fonds
  alimenté par des frais : **option écartée**.
- Pitch slide 7 : commission à la sortie + **fonds d'assurance**, « transferts gratuits » (noté
  « proposé, à valider »). Le contrat sait prélever (`entryFeeBps`, `convertFee*`), mais toutes les
  marges valent **0** dans les démos (`GHOST_FIXTURE_CONFIG`).
- **Correction** : trancher en équipe avant de monter la slide ; sinon dire « modèle proposé, non
  tranché, non mesuré ».

### M6 — Temps de chauffe de la détection

- Profil par défaut : la baseline compare au même créneau des jours précédents et demande 5
  tranches d'historique, donc **5 jours** avant toute alerte. Profil `demo` : 12 tranches de 5 min,
  donc **1 h**. Une alerte ne sort qu'à la clôture d'une tranche de 5 min.
- **Risque** : toute démo « en direct » (Fuji ou anvil alimenté à la main) reste muette. Seul le
  rejeu fonctionne. La defense sheet le dit pour la marge (« bornée par la tranche de 5 min »).

### M7 — Le monitor ne voit pas l'administration du Ghost

- Les filtres d'administration (`RoleGranted`, `RoleRevoked`, `RateChanged`) portent sur l'adresse du
  **minter** seulement. Sur le Ghost, seuls `GhostIssued` et `GhostConverted` sont lus.
- Non lus : don ou retrait de `WATCHER_ROLE` sur le Ghost, `AllowedMoverSet`, `RateProposed`
  (l'annonce 1 h avant un changement de taux), `PerimeterDelayed`, `GhostDestroyed`.
- **Risque** : une clé admin volée peut retirer tous les surveillants sans qu'aucune alerte ne parte.

### M8 — Pouvoirs de la clé d'administration

- Le même compte `admin` reçoit `DEFAULT_ADMIN_ROLE` sur le minter **et** sur le Ghost, plus
  `RATE_ADMIN_ROLE`.
- Taux : pas de ±5 % (`MAX_RATE_STEP_BPS`), délai de 1 h (`RATE_DELAY`), un guardian seul peut
  annuler. Mais les pas **s'enchaînent** sans borne cumulée (5 % par heure, composés), et
  `RateGuard.t.sol` ne teste pas l'enchaînement.
- `WATCHER_ROLE` : donné ou retiré par l'admin, sans délai ni multisig. Un surveillant ne peut que
  retarder, dans la limite du budget (vérifié par `invariant_f_watcherBounds`).
- `CLAIMS.md` pose déjà l'hypothèse « clés d'administration non compromises » : c'est cohérent, il
  faut juste le dire.

### M9 — Rapport d'incident : IA ou bouchon ?

- Sans `LLM_LIVE=1`, le dashboard utilise un client hors ligne (`MODE_OFFLINE`). Le mode est
  affiché, mais le pitch dit « le rapport d'incident est pré-rempli » sans préciser.
- `BEDROCK_MODEL_ID` est encore « à confirmer » (`.env.example`, `OPEN_QUESTIONS.md` §8).
- Le limiteur 1 requête/seconde est bien appelé avant chaque appel, sans nouvelle tentative
  automatique (`llm/client.py`).
- **Correction** : décider avant le pitch (live ou hors ligne), tester une fois, et le dire.

### M10 — Le README présente une proposition comme un fait

- Depuis #155, le README dit que le Ghost sert à récupérer des fonds par « séquestre à la source,
  lignée d'origine, saisie/clawback multisig », et que `data/` contient le « marché du Ghost
  (décote/commission) + séquestre/saisie ».
- Ces mécanismes viennent de `docs/GHOST_MARKET_SEIZURE.md`, dont l'en-tête dit : « **PROPOSITION**
  — à valider en équipe », qui « étend et, sur un point, contredit » les décisions actées. Sa §5
  liste elle-même les conflits : commission « bénéfice » contre §0, « dernier acheteur perd tout »
  contre §10bis (où le dernier porteur est restitué), lignage d'origine rendu obligatoire alors
  que §11 a retenu le recalcul hors chaîne (piste b) et écarté le stockage du lignage on-chain.
- Rien de cela n'est dans `contracts/src/` ni dans `OPEN_ANSWERS.md` ; c'est un registre hors
  chaîne (`data/ghost_ledger.py`).
- Le README garde aussi « les surveillants publient un gel » / « peuvent demander un gel »
  (vocabulaire remplacé par « retarder », §3) et « la perte max est de X $ » (X jamais chiffré en
  dollars : la borne testée est « 0 pour la clé de service »).
- **Correction rapide** : ajouter « proposé, non acté, simulation hors chaîne » sur ces lignes.

### Constats mineurs (m1 à m10)

Voir le tableau. Précisions utiles :

- **m2** : la décision §11 dit que la liste des destructions passe par une racine de Merkle
  « contestable ». Côté Ghost c'est un commentaire « point d'extension (non implémenté) » ; la
  destruction passe par le semis du surveillant puis le 2/3 (64 comptes au plus par appel). Côté
  coffre, la racine s'applique dès le 2/3, sans délai de contestation. Ne pas dire « contestable ».
- **m7** : `.kiro/steering/module-detection.md` l.13 dit que les surveillants « peuvent demander un
  gel » (vocabulaire remplacé par « retarder », §3). `CLAUDE.md` et la slide 8 disent « perte
  reportée sur les acheteurs de Ghost » ; §10bis dit « sur les acteurs du M' pur » (l'acheteur
  protégé ne perd rien).
- **m9** : beaucoup de décisions sont « validée en session, à relire par l'équipe » ; l'issue #3
  (valeurs des seuils) est la seule issue ouverte.

## Sécurité : ce qui a été cherché

- **Secrets** : recherche dans l'arbre et dans l'historique git (toutes branches) de clés privées,
  de clés AWS, de fichiers `.env` / `.pem` / `.key` / `broadcast/`. **Rien trouvé.** Les chaînes
  hexadécimales de 64 caractères présentes sont des hash d'exemple. Recherche par motifs : ce n'est
  pas une garantie.
- **Contrôle d'accès** : `completeSwap` (clé de service) ne choisit ni montant ni destinataire ;
  pause en 3/3 ; destruction, restitution, blanchiment, liste des appelants en 2/3 ; coffre : deux
  sorties seulement (`redeem`, `restitute`). Conforme aux décisions §0, §3, §10bis.
- **Ce qu'une seule clé volée permet** : clé de service → rien de plus que traiter des demandes
  existantes (testé). Clé surveillant → retarder jusqu'au budget. Clé d'un guardian → annuler un
  changement de taux, proposer (sans exécuter). Clé admin → voir M8. **Aucune clé** → voir C2.
- **Pouvoir du 2/3** : `proposeExtend` (montant libre) puis `proposeDestroy` permettent à deux
  guardians de brûler le Ghost de n'importe quelle adresse. C'est le « pouvoir de reprendre » déjà
  listé en limite (§9).

## Chiffres du pitch relancés

| Chiffre annoncé | Relancé | Résultat |
|-----------------|---------|----------|
| A : vulnérable = ×1000 le dépôt, protégé = dépôt | `dashboard.demo run A` (anvil) | conforme |
| B : alerte à 296 s (seed 20) | `dashboard.demo run B --seed 20` | 296,023 s — conforme (287 s seed 42, 294 s seed 7) |
| B : 1,4 % à 1,7 % de l'offre retardée | seeds 20, 7, 42 | 1,52 % / 1,73 % / 1,43 % — conforme |
| N3 : 8,1 % à 8,5 % | seeds 20, 7, 42 | 8,47 % / 8,14 % / 8,42 % — conforme |
| C : 21 250 mUSDC sans balise, 0 avec | `dashboard.demo run C` (anvil) | conforme |
| D : protocole 0, voleur 0, 10 USDC restitués, 5 USDC perdus par le spéculateur | `dashboard.demo run D` (anvil) | conforme au cas 2bis de §10bis |
| Friction 3,2 % / 5,7 % à 10 min | `data.calibrate --seed 42` | conforme |
| Mints d'attaque détectés : 2 sur 2 | `data.calibrate --seed 42` | conforme |
| 0 faux positif sur 864 (petits transferts) | `data.calibrate --seed 42` | conforme |
| 5 puis 0 faux positif (gros transferts) | `data.calibrate --seed 42` | **non conforme : 7 puis 1** (C1) |
| Récupération 100 % / 0 % | `data.late_marking` | conforme |
| C : 76 000 mUSDC (test Foundry) | `forge test` passe | chiffre non relu dans le test |
| N1 : 1 faux positif, profil gros transferts, seed 20 | — | non relancé |

## À corriger avant le pitch

Seulement ce qui est grave **et** rapide.

1. **C1** — relancer `make calibrate` sur la machine de démo et corriger les chiffres de faux
   positifs partout (slide 5, questions, defense sheet, `CLAIMS.md`). ~20 min. @EnzoFB06,
   @marceaupatu123.
2. **M1** — retirer « sous les plafonds » du pitch, de la defense sheet et, si possible, du titre du
   scénario B et de la page animée. ~10 min. @marceaupatu123.
3. **M2 + M10** — `CLAIMS.md` : remplacer « en attente » par « vérifié par tests d'invariants »
   avec le nom des tests ; README : marquer « séquestre / lignée d'origine / saisie » comme
   proposition. ~15 min. @marceaupatu123, @EnzoFB06.
4. **M5** — décider en deux minutes ce qu'on dit sur la commission ; sinon marquer la slide 7
   « proposé, non tranché ». Équipe.
5. **M9** — choisir live ou hors ligne pour le rapport, tester une fois. @denybs.
6. **C2** — si @denybs a le temps : faire valider l'offre par le vendeur + un test. Sinon, le dire.
7. **Avant de monter sur scène** : lancer chaque scénario une fois sur la machine de démo avec
   `SH_DEMO_CONTRACTS_BACKEND=anvil` (mesuré ici : 5 à 14 s par scénario) et vérifier le bandeau
   « implémentation réelle ». Sous Windows, lancer avec `PYTHONUTF8=1`.

## À dire au jury comme limite assumée

Ce qu'on ne corrigera pas, dit simplement.

- **Rien n'est déployé sur Fuji.** Les contrats tournent en tests Foundry et sur une chaîne locale.
- **La réponse automatique n'écrit pas encore sur la chaîne.** Détection, réponse et rapport sont
  reliés dans une simulation rejouable ; les vrais contrats sont montrés à part, sur une séquence
  fixe.
- **La détection a besoin d'un historique** (1 h en profil démo, plusieurs jours sinon) et ne
  décide qu'à la fin d'une tranche de 5 minutes. La latence réseau réelle n'est pas mesurée.
- **Une clé d'administration volée est hors périmètre** : elle peut retirer les surveillants et
  faire dériver le taux de 5 % par heure. La borne testée porte sur la clé de service.
- **Deux guardians sur trois peuvent reprendre des fonds** : c'est une hypothèse de confiance.
- **Le routeur de règlement est une maquette** : il ne vérifie pas encore l'accord du vendeur sur le
  prix (si C2 n'est pas corrigé).
- **La contestation d'une restitution et la destruction par racine de Merkle ne sont pas codées.**
- **Les faux positifs dépendent du profil de trafic** : zéro sur un profil, quelques-uns sur l'autre,
  même en montant le seuil. Une seule graine, données fictives.
- **Les seuils ne sont pas actés** (issue #3) ; le multisig est simulé ; le modèle économique est
  une proposition.
- **Le fuzzing explore, il ne prouve pas** (256 exécutions par défaut).

## Tests manquants

- Routeur : un tiers ne doit pas pouvoir acheter au prix qu'il choisit (C2).
- Bout en bout : une alerte de `detection` qui provoque un `delay()` sur un vrai contrat.
- Démo : déploiement avec `initRouting` activé, et B / N3 rejoués à travers le routeur.
- Taux : enchaînement de plusieurs `proposeRate` / `executeRate` (dérive cumulée).
- Monitor : événements d'administration émis par le Ghost.
- Budget de quarantaine : la valeur X de `CLAIMS.md` reste « à mesurer » (fixture : 20 %).
- Tests de `data/` indépendants de l'encodage de la machine.

## Résultats des tests

| Suite | Commande | Résultat |
|-------|----------|----------|
| Python | `python -m pytest -q` (Windows, Python 3.12.10) | **477 passés, 2 échecs, 6 ignorés** (96 s) |
| Python, échecs | `data/tests/test_calibrate.py::test_cli_writes_json_and_markdown`, `data/tests/test_late_marking.py::test_cli_writes_reports` | encodage Windows (tiret « — » mal relu). Les deux fichiers passent en entier avec `PYTHONUTF8=1` |
| Python, ignorés | 6 tests `real_anvil` du dashboard | Foundry absent du `PATH` lors de ce passage ; couverts par le job CI « scenario A (anvil) » |
| Foundry | `forge build` puis `forge test` (Foundry 1.5.1, dépendances aux tags de la CI) | **246 passés, 0 échec, 0 ignoré**, 25 suites (43 s) |
| Démo, simulation | `python -m dashboard.demo run <A\|B\|C\|D\|N1\|N2\|N3> --seed 20` | 7 sur 7 terminés, code 0 |
| Démo, anvil | idem avec `SH_DEMO_CONTRACTS_BACKEND=anvil` | 7 sur 7 terminés ; A, C, D en « implémentation réelle » ; B et N3 affichent un bloc on-chain sous un bandeau « simulation » (voir m5) |
| Calibration | `python -m data.calibrate --seed 42` | terminé ; écart avec les docs (C1) |
| Lignage tardif | `python -m data.late_marking` | terminé ; conforme |

La CI GitHub (Linux, Python 3.11) reste la référence : elle est **verte** sur `main` pour les
commits `ce2beaa` et `891f14c` (`gh run list`). Elle ne voit pas les deux échecs Windows.
