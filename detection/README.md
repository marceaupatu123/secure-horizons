# detection

- **Rôle** : un ou plusieurs **surveillants** indépendants (règles, ML, signaux de transferts anormaux) qui détectent une anomalie sur les **mints**/**transferts**, produisent des `Alert` et peuvent **demander un gel**. L'IA n'est qu'un surveillant parmi d'autres, jamais le décideur _(proposé, à valider)_.
- **Propriétaire** : @Yannis1307 (voir `docs/TEAM.md`).
- **Lancer** : `python -m detection` (écoute LIVE) ou
  `python -m detection --replay FICHIER.jsonl --profile demo` (voir ci-dessous) ;
  tests : `python -m pytest detection/`.

## Branchement monitor → detection (#86)

`detection/pipeline.py` alimente `RuleBasedMonitor` et écrit chaque `Alert` en **JSON lines**
sur la sortie standard (journaux sur la sortie d'erreur). Aucune intégration avec `response/`.

- **LIVE** (défaut) : flux `ChainListener.stream_event_batches` du monitor (mints + transferts).
  Sans `MONITOR_TOKEN_ADDRESS` / `FUJI_RPC_URL` (aucun contrat déployé), message et sortie
  propre (code 0).
- **REPLAY** : `--replay` rejoue un JSONL de `data/generate.py` ; seules les lignes `MintEvent`
  et `TransferEvent` sont consommées. Exemple (fichiers générés HORS du dépôt) :

  ```bash
  python -m data.generate --scenario B --seed 42 --out-dir /tmp/sh-data
  python -m detection --replay /tmp/sh-data/scenario_b.jsonl --profile demo \
    --exit-point 0xe1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1
  ```

- **Horloge** : les tranches sont clôturées à l'heure même sans transfert (LIVE : à chaque poll ;
  REPLAY : à l'horodatage de chaque événement, puis une fois après le dernier).
- **Offre en circulation** (_PROVISOIRE, à valider_) : LIVE = `totalSupply()` relu à chaque
  poll (offre **totale**, aucune définition de « en circulation » n'est actée) ; REPLAY =
  `--initial-supply` (défaut 0) + somme des `MintEvent` rejoués, car les soldes pré-existants du
  générateur n'ont pas d'événement. Le ratio volume/offre du replay est donc surestimé.
- **Tranches sautées** : un `WARNING` explicite est journalisé (offre inconnue, historique
  insuffisant) au lieu d'un `None` silencieux. Idem, une fois, pour les mints vérifiés sans
  `MintContext` (GAP : ni dépôt ni taux dans les événements, donc aucune règle de mint vérifiée).
- **Profils de chauffe** (`detection/params.py`) : `default` (valeurs PROVISOIRES ci-dessous,
  5 jours d'historique du même créneau) et `demo` — **DEMO, ne pas utiliser en production,
  PROVISOIRE** : chaque tranche est comparée aux 24 tranches précédentes, alerte possible après
  12 tranches (1 h). Sélection : `--profile`, sinon `DETECTION_PROFILE`, sinon `default`.
- **Points de sortie** : `--exit-point ADRESSE` (répétable, PROVISOIRE).
- **Mode contrat protégé (#104)** : avec `MONITOR_MINTER_ADDRESS`, chaque mint arrive avec sa
  demande (`detection/provenance.py`) : I1 et I3 sont **vérifiés en LIVE** contre le dépôt et le
  déposant lus dans `SwapRequested` (pas dans `SwapCompleted`, écrit par le contrat surveillé) ;
  un mint sans `SwapCompleted` lève **I4** (critique) ; `RoleGranted` / `RoleRevoked` /
  `RateChanged` non annoncés lèvent une alerte **dès leur lecture**
  (`RuleBasedMonitor.check_admin_event`). Détails et limites : `monitor/README.md`.
- **GAP pour `shared/` (@marceaupatu123, #79)** : aucun modèle partagé pour l'offre en
  circulation ni pour le contexte d'un mint (dépôt, taux) ; le pipeline les adapte dans
  `detection/`.

## Surveillant de mint à règles (#11)

`RuleBasedMonitor.check_mint(event, context)` suit `docs/OPEN_ANSWERS.md` §1 : **aucun seuil sur
la taille d'un mint**. Il vérifie I1 (`minted = dépôt × taux` à ε près), I3 (destinataire du
mint = déposant de la demande, #91 : détournement à 1:1 du scénario B, entrée
`MintContext.requester`), I5
(`Δ totalSupply = Σ Mint − Σ Burn`), I6 (`totalSupply ≤ collatéral × facteur`), les événements
d'administration non annoncés et l'écart du taux au-delà de δ vs une référence. Une `Alert`
signifie seulement **retarder** le périmètre (§3) ; détruire / pause globale = multisig.

- **I3 (#91)** : si l'appelant fournit `MintContext.requester` (le déposant de la demande) et que
  `event.recipient` en diffère, tout le montant minté est suspect. C'est le seul contrôle qui
  attrape le **détournement à 1:1 du scénario B** (OPEN_ANSWERS §1, piste 4 : la demande d'une
  victime est mintée vers l'attaquant) — I1 tient dans ce cas, seul le changement de destinataire
  trahit l'attaque, quelle que soit sa taille. `requester` reste **hors `shared/`** (fourni par
  l'appelant comme `deposit_amount`).

- **Paramètres** : un seul fichier, `detection/params.py` (ε, δ, facteur I6, gravités), tous
  **PROVISOIRES / À MESURER**, aucune valeur mesurée.
- **Entrées hors `MintEvent`** : `detection/inputs.py` (`MintContext`, `AdminEvent`,
  `AdminAnnouncement`). Une vérification dont les entrées manquent est sautée.
- **GAP pour `shared/` (@marceaupatu123)** : `MintEvent` ne porte ni dépôt ni taux ; aucun modèle
  partagé pour l'offre totale, le collatéral, les événements d'administration ni leur annonce.
- **Pas de corrélation par `request_id`** : depuis #79 (OPEN_ANSWERS §79), le monitor met
  `UNKNOWN_REQUEST_ID = None` (plus `0`, qui entrait en collision avec la vraie demande n°0) ;
  `MintEvent.request_id` est `int | None`. Le dépôt est fourni explicitement par l'appelant.

## Surveillant de transferts (#12)

`RuleBasedMonitor.check_transfer(event)` suit `docs/OPEN_ANSWERS.md` §9 (acté) : volume normalisé
par l'offre en circulation, baseline **médiane + MAD** glissante, alerte seulement si **volume
élevé ET dispersion effondrée**, jamais sur le volume seul. Les choix suivants viennent des
propositions **non actées** de `docs/OPEN_QUESTIONS.md` §2 et sont **PROVISOIRES** :

- **Tranches de 5 min** comparées à la baseline du **même créneau** (même heure les jours
  précédents). L'alerte part à la **clôture** de la tranche : au premier transfert de la tranche
  suivante, ou via `close_slot_if_due(now)` sur un minuteur (à appeler pour rester plus rapide que
  la fenêtre Ghost de 10 min).
- **Dispersion = indice de Herfindahl** (somme des parts au carré des soldes entrants **nets**).
  Dans l'`Alert`, `dispersion_score` = 1/HHI (« nombre effectif de destinataires », bas =
  concentré) ; le HHI brut est dans `reason` et `last_slot_stats`.
- **Rebonds comptés une fois (#87, PROVISOIRE)** : volume d'une tranche = somme des soldes
  entrants nets (reçu − envoyé). A → B → C compte une fois ; l'exemple de référence compte 50M et
  non 100M. Volume brut exposé (`gross_volume`). Limites et effet mesuré :
  `docs/OPEN_QUESTIONS.md` §2, point 5.
- **Destinataires distincts** : exposés (`last_slot_stats.distinct_recipients`, `reason`) mais
  **jamais** utilisés seuls : 50M vers 3 adresses neuves puis 4 bridges le font passer de 150 à
  157 seulement (testé), alors que le HHI explose.
- **Adresse neuve** = aucune transaction avant le début de la tranche dans nos données
  (`known_addresses` + tranches déjà vues). Variante future : moins de K transactions.
- **Points de sortie** = liste fixe `TransferRuleParams.exit_points` (vide par défaut), à fournir
  par le générateur de `data/` (@EnzoFB06, #24).
- **Signaux par transfert** (gros montant vers adresse neuve, découpage, sortie rapide, fan-out) :
  déjà captés par le HHI ; seulement exposés en descriptif, ils ne déclenchent rien seuls.
- **Graines** : où se trouvent, à la clôture, les fonds envoyés par des adresses neuves (les
  relais neufs tombent à 0, le soupçon arrive sur les bridges ; somme conservée). Un attaquant aux
  adresses « chauffées » à l'avance ne produit aucune graine (alerte quand même, sans graine).
- **Historique insuffisant** (< `min_history_slots` tranches du même créneau) : la tranche nourrit
  la baseline mais **n'alerte jamais**. Une tranche qui alerte n'entre pas dans la baseline.
- **Paramètres** : `TransferRuleParams` dans `detection/params.py` (longueur de tranche, période,
  fenêtre, historique minimal, seuils de z, MAD, points de sortie), tous **PROVISOIRES / À
  MESURER**.
- **GAP pour `shared/` (@marceaupatu123)** : aucun modèle partagé ne porte l'offre en circulation
  (passée via `circulating_supply` / `update_circulating_supply`) ; `Alert` n'a pas de champ pour
  le HHI brut ni pour le nombre de destinataires distincts (d'où 1/HHI dans `dispersion_score` et
  le détail dans `reason`).

## Surveillant ML + prédiction conforme (#13, optionnel, NON branché)

`detection/conformal.py` : `ConformalSlotMonitor` = `IsolationForest` (scikit-learn) entraîné sur des
tranches **normales**, puis p-valeur conforme « split » sur une calibration disjointe :
`p = (1 + #{scores calib ≥ s}) / (n + 1)`, signal si `p ≤ alpha`. Caractéristiques : ratios de
`TransferSlotStats` uniquement (volume/offre, HHI, part neuve, part sortie, log fan-out).

- **Garantie** : taux de faux positifs par tranche ≤ `alpha` **si** le trafic testé est échangeable
  avec la calibration. Elle tombe dès que le trafic change (croissance, usage nouveau), elle est
  marginale (pas une borne par journée) et ne dit **rien** sur la détection.
- **Ne déclenche rien** : renvoie un `ConformalVerdict`, pas d'`Alert` (OPEN_ANSWERS §1 a écarté la
  prédiction conforme pour la démo). Mesure : `python -m detection.conformal_eval` (~1 min).
- **Mesure (seed 42, simulation)** : FP mesuré ≈ alpha (0,7–1,0 % à α = 1 %, 3,8–4,5 % à α = 5 %),
  mais pas mieux que les règles : B 0,5 % non détecté sur `gros_transferts`. Détail et décision
  proposée : `docs/OPEN_QUESTIONS.md` §13.
