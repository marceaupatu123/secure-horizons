# data — données synthétiques

- **Propriétaire** : @EnzoFB06 (voir `docs/TEAM.md`).
- **Lancer** : `make data` ou `python -m data.generate --scenario <normal|A|B|C|D|all> --seed <n>` ;
  tests : `python -m pytest data/`.

> **Toutes les données de ce dossier sont FICTIVES.** Aucune vraie donnée on-chain, aucune vraie
> adresse, aucune vraie clé. Faux secrets autorisés de type `FLAG{team20-canary}`.

Cadre : décision §6 de `docs/OPEN_ANSWERS.md` (format JSONL, scénarios recadrés, générateur
reproductible), mesures de la §5.

## Format

- **JSONL**, une ligne = un modèle de `shared.models` (`MintRequest`, `MintEvent`,
  `TransferEvent` ; pour C et D aussi `GhostTokenMintEvent`, `GhostTokenRedemptionEvent`,
  `GhostTokenBurnEvent`, `RiskBeaconUpdate`), validé en Pydantic strict. Relecture : `data.generate.load_jsonl(path)` ou
  `pd.read_json(path, lines=True)`.
- Chaque fichier a un **manifeste** `<nom>.manifest.json` : graine, paramètres, comptes, et la
  **vérité terrain** de l'attaque (adresses, `request_id`, tx, `started_at` = `t0`).
- Horodatage = temps simulé du bloc (`t0`, UTC) ; `block_number` en dérive (temps de bloc ~2 s,
  paramètre). Token fictif à **6 décimales** : les montants en base units tiennent en int64.
- Sortie par défaut : `data/generated/`. **Ne pas committer** ces fichiers tant que l'équipe n'a
  pas tranché (graine seule vs JSONL committés, `.gitignore`).

## Jeux produits

| Fichier | Contenu | Sert à |
|---------|---------|--------|
| `normal.jsonl` | trafic légitime seul : mints 1:1 vers le déposant (I1 + I3), transferts dispersés sur une population d'adresses anciennes, saisonnalité par créneau de 5 min, croissance progressive | baseline médiane + MAD (§9), **dénominateur du taux de faux positifs** (§5, #59) |
| `scenario_a_vulnerable.jsonl` / `scenario_a_protected.jsonl` | même fond de trafic ; l'attaquant fait deux demandes (dépôt total 200 000) ; mint ×400 sur le contrat vulnérable, 1:1 sur le protégé | volet 1 : montant mintable pour un même dépôt (#24) |
| `scenario_b.jsonl` | voir ci-dessous | surveillant hors chaîne, marge avant conversion (#24, #49) |

Tous les jeux portent la fenêtre Ghost (§0bis) : `is_ghost` vaut `true` quand l'expéditeur dépense
des fonds reçus il y a moins de `ghost_window_minutes`.

### Scénario B — une hypothèse du volet 1 tombe : détournement à 1:1 (I3)

Avec le volet 1 et sans plafond fixe, « rester sous les plafonds » ne rapporte rien (§0, §1). Le
scénario B suppose donc qu'**I3 (destinataire = déposant) n'est pas appliqué** :

1. **B1** : la demande d'une victime est traitée vers une **adresse neuve** de l'attaquant. Le
   bilan global reste à 1:1 (I1 tient), mais l'argent change de poche. Le surveillant de mint doit
   lever : destinataire ≠ déposant de la demande n°X.
2. **B2** : l'attaquant fait sortir les fonds vers `exit_hops` adresses neuves, puis vers un
   **point de sortie** fictif, le tout **avant la fin de la fenêtre Ghost**. Le surveillant de
   transferts doit lever : **volume élevé ET dispersion effondrée** (§9).

On mesure si l'alerte arrive avec une **marge positive avant conversion** (§5).

Variante non générée : **événement d'administration** non annoncé (`Upgraded`, `RoleGranted`).
Aucun modèle de `shared/` ne le représente aujourd'hui ; il faudrait d'abord l'ajouter à
`docs/CONTRACTS.md` (zone partagée).

### Scénarios C et D (#25) — simulation hors chaîne

Générés par `data/scenarios_cd.py` sur un **registre de référence** du Ghost
(`data/ghost_ledger.py`) qui reprend les mécanismes actés : tranches d'échéance (§0bis-b), ratio
de contamination par adresse (§9), retard sans conversion (§3), seuils ratio ET montant absolu
(§9), réserve de restitution (§0bis-c). **Ce n'est pas le contrat (#7, #8)** : c'est un point de
comparaison pour ses tests, avec des simplifications listées en tête du fichier (soupçon en
`float`, pas de marge de conversion).

Trame : trafic légitime de fond → `t0` mint **non adossé** → alerte à `t0 + 3 min` (le
surveillant reconstitue hors chaîne la propagation du soupçon et la sème comme `Alert.seeds`) →
destruction multisig à `t0 + 20 min`.

| Fichier | Variante | Ce qu'on mesure (manifeste, `results`) |
|---------|----------|------------------------------------------|
| `scenario_d_otc` | l'attaquant revend son Ghost à des spéculateurs payés comptant, qui en revendent une partie à des légitimes | déficit du protocole, Ghost détruit par groupe, valeur nette des spéculateurs |
| `scenario_d_pool` | vente à notre pool en règlement différé (`swap-id`, §10) | créances payées / annulées, USDC payé par le pool |
| `scenario_d_no_ghost` | même attaque, fenêtre nulle | baseline « Resolv tel quel » (§5) |
| `scenario_c_with_beacon` / `_without_beacon` | l'attaquant fragmente son Ghost et l'apporte en garantie ; un coffre par prêt | mauvaises créances, prêts refusés (attaquant / légitimes) |

Résultats avec la graine 42 (simulation, paramètres à calibrer) :

- **D** : sans Ghost, le déficit du protocole vaut tout le mint frauduleux ; avec Ghost (OTC ou
  pool), il est nul. En OTC, la perte passe aux spéculateurs et aux légitimes qui leur ont racheté.
- **C** : mauvaises créances nulles avec la balise, 75 % du montant frauduleux sans balise.

Deux limites mises en évidence par la simulation (à discuter avec #8 et #43) :

1. **§10, swaps faits avant l'alerte** : la créance est annulée selon le ratio du vendeur **au
   moment du swap**. Avant l'alerte ce ratio vaut 0, donc ces créances sont payées à l'attaquant
   (`scenario_d_pool` : 3 ventes sur 8 avec la graine 42).
2. **Ratio par adresse × tranches** : avant l'alerte, une adresse qui détient du Ghost ancien et
   propre plus du Ghost frais contaminé peut convertir l'ancien ; le ratio étant uniforme sur le
   solde, une part du soupçon part avec (`suspect_leaked_before_alert`). Selon la graine, une
   fraction de la fraude survit ainsi à la destruction (0 avec la graine 42, ~0,1 % avec la
   graine 3).

## Paramètres — à calibrer, pas des mesures

Les valeurs par défaut de `GenerationParams` (200 utilisateurs, ~1 mint et ~12 transferts par
créneau de 5 min, 24 h simulées, attaque à 75 % de la période) sont des **paramètres de
génération**, pas des chiffres mesurés (`docs/CLAIMS.md`). Seule référence externe : Resolv
(~200 000 déposés, ratio ~400×, cf. §1).

## Reste ouvert

- Committer les JSONL ou seulement le générateur + la graine (`.gitignore`).
- Liste des adresses « point de sortie » (§2) : un seul point fictif pour l'instant.
- Variante B « événement admin » : nécessite un modèle partagé.
- Scénarios C/D : aligner le registre de référence sur le contrat Ghost (#8) quand il existe.
