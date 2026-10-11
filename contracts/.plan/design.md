# Design — Token Ghost (#8), RiskBeacon + MockLendingMarket (#7), pool M-Ghost/USDC (#65)

Itération 3 : révision après `contracts/.plan/design-review.md` (itération 2, CHANGES_REQUESTED,
1 HIGH / 4 MEDIUM / 12 NIT). Chaque constat est traité ; la table de réponses est en §14
(itération 2) et §14bis (itération 1, conservée). Données **fictives** uniquement.

## 0. Vue d'ensemble

Ce document projette les décisions déjà actées (`docs/OPEN_ANSWERS.md` §0, §0bis, §0bis-a/b/c,
§3, §4, §9, §10) sur des contrats Foundry concrets. Il ne re-décide rien : quand une décision
laisse un détail ouvert, l'option la plus simple compatible est retenue et listée en §9
« Choix d'implémentation à valider ».

Architecture retenue : le vrai token **M** (`GhostedStable`) ne se mint que par conversion
depuis **M-Ghost** (`GhostToken`). Tout transfert de M brûle le M de l'expéditeur et émet du
M-Ghost frais chez le destinataire (§0bis). `ProtectedMinter` (volet 1) émet désormais du
M-Ghost frais au déposant au lieu de M. `GhostToken` porte tout l'état de sécurité : tranches
d'échéance (§0bis-b), soupçon par adresse (§9), incidents auto-expirants posés par les
surveillants (§3), multisig 2/3 (destruction, restitution) et pause 3/3 (`GuardianPausable`),
réserve de restitution (§0bis-c). `RiskBeacon` est une façade de lecture sans état propre ;
`MockLendingMarket` et `GhostUsdcPool` sont des consommateurs aval fictifs.

Pile technique (figée) : Solidity `^0.8.24` compilé en 0.8.33 / EVM cancun (`foundry.toml`
inchangé), OpenZeppelin v5.4.0 (`ERC20`, `AccessControl`, `Pausable`, `Math`, `SafeERC20`),
forge-std v1.17.0. Aucune nouvelle dépendance. Pas d'upgradabilité (H4).

Sources lues : `docs/OPEN_ANSWERS.md` (intégral), `docs/CONTRACTS.md` (Ghost*, AlertSeed,
RiskBeaconUpdate, enums), `docs/CLAIMS.md`, `docs/ROADMAP.md`, `contracts/README.md`,
`src/*.sol`, `test/**` (y compris `ProtectedMinterHandler.sol`), et en itération 2 le corps et
les commentaires des issues **#8, #7, #65, #33** (lus via `gh issue view`). Apports des issues
pris en compte :

- #8 (commentaire de spécification consolidée) : confirme §0bis, §0bis-b, §9, §3, §0bis-c, §0 ;
  les tests de #33 sont réalisés ici. Commentaire du propriétaire : la démo (#47, branchement
  #70) a besoin de **montants et d'états relisibles après rejeu** → événements complets (§3.12)
  et vues sans état caché (§3.11).
- #7 : « chiffre de démo : mauvaises créances avec vs sans balise (à mesurer) » → scénario C.
- #65 : `swap-id` = montant, ratio du vendeur au swap, échéance du Ghost vendu ; tests Foundry
  obligatoires ; mesures du scénario D avec `data/` (#25) plus tard → scénario D (§8.3).
- #33 et `OPEN_ANSWERS.md` §9 : « **Réversible** : audit blanchissant → ratios concernés remis
  à 0 ». L'itération 1 l'avait omis ; ajouté comme action humaine 2/3 `Clear` (§3.6bis).

En itération 3, lus aussi sur `origin/main` (`git show`, sans modifier ces dossiers) :
`data/ghost_ledger.py` et `data/scenarios_cd.py` (#25, PR #82, registre hors chaîne de
référence, propriétaire `data/`) → écarts listés en §10bis ; `monitor/listener.py` (#9 / #10)
→ correspondance des logs en §3.12. `OPEN_ANSWERS.md` §3 relu : « Aucun acteur seul ne peut
accélérer, libérer ou raccourcir » et « Silence = retour automatique » (fonde l'absence de
levée de retard, §10bis).

### Fichiers

| Fichier | Statut | Rôle |
|---|---|---|
| `src/GhostedStable.sol` | nouveau | M : ERC20 18 déc., `mint` réservé au Ghost (immuable), hook de transfert → Ghost |
| `src/GhostToken.sol` | nouveau | M-Ghost : tranches, soupçon, incidents, conversion, destruction, réserve |
| `src/lib/MaturityBuckets.sol` | nouveau | librairie : anneau de N+1 tranches par adresse (interne ; externe en repli, §1) |
| `src/GuardianActions.sol` | nouveau | abstrait, étend `GuardianPausable` : propositions 2/3 (rounds séparés de la pause) |
| `src/interfaces/IGhostRisk.sol` | nouveau | vues de risque lues par balise / pool (`effectiveSuspectOf`, `suspectComponentsOf`, `ratioOf`, `extendedUntil`, `destroyedAt`, `clearedAt`, `incidents`, seuils, `paused`) |
| `src/interfaces/IGhostToken.sol` | nouveau | points d'entrée appelés par M et le minter : `onUnderlyingTransfer`, `issueFromMinter`, `underlying()` |
| `src/GhostLens.sol` | conditionnel | uniquement si le repli de taille n°2 (§1) est nécessaire : vues de confort sans état |
| `src/RiskBeacon.sol` | nouveau | façade de lecture + `publish` permissionless (événements monitor) |
| `src/MockLendingMarket.sol` | nouveau | prêt fictif en MockUSDC contre M / M-Ghost, décote = f(risque) |
| `src/GhostUsdcPool.sol` | nouveau | pool simulé à prix fixe, règlement différé `swapId` |
| `src/ProtectedMinter.sol` | modifié | déploie le Ghost ; `completeSwap` émet du Ghost frais |
| `src/StableToken.sol`, `src/VulnerableMinter.sol` | inchangés | monde « sans protection » (baseline scénario A) |
| `src/GuardianPausable.sol` | inchangé | réutilisé tel quel (pause 3/3) |
| `test/**` | voir §8 | nouvelles suites + adaptation des suites volet 1 |
| `README.md` | modifié | sections Ghost / balise / marché / pool, invariants, gas mesuré |

## 1. Déploiement et chemins d'émission

**Ordre (aucune étape de confiance, tout est immuable)** : `ProtectedMinter` déploie
`GhostToken` dans son constructeur (même schéma que le `StableToken` actuel), et `GhostToken`
déploie `GhostedStable` dans le sien. Donc `M.minter == M.ghost == address(ghost)`,
`ghost.underlying == M`, `ghost.minter == address(protectedMinter)`, tous `immutable`.
`ProtectedMinter.stable` devient `GhostedStable` (= `ghost.underlying()`), plus `ghost` public.

Nouvelle signature : `ProtectedMinter(IERC20 collateral_, address admin, address service,
uint256 initialRate, address[3] guardians_, GhostConfig memory ghostConfig)`. Les mêmes 3
guardians servent au minter (pause 3/3 existante) et au Ghost (pause 3/3 + actions 2/3).

Contrôle de taille obligatoire à l'implémentation : `forge build --sizes`. Runtime de chaque
contrat ≤ 24 576 o (EIP-170) et initcode de `ProtectedMinter` ≤ 49 152 o (EIP-3860).
`foundry.toml` n'est **pas** modifié (pas de `via_ir`, `optimizer_runs` inchangé). Replis, dans
cet ordre, chacun appliqué seulement si le précédent ne suffit pas :

1. **Runtime de `GhostToken` > 24 576 o** : `MaturityBuckets` passe en librairie **externe**
   (fonctions `public` sur un `Account storage`, liée automatiquement par Foundry).
2. **Toujours trop gros** : les vues de confort `bucketsOf`, `nextOutgoingMaturity`,
   `suspectComponentsOf` sortent dans `GhostLens` (sans état, `GhostToken` immuable au
   constructeur), qui lit deux getters bruts gardés dans `GhostToken` :
   `bucketAt(address, uint8) → (uint64 maturity, uint192 amount)` et `maturedOf(address)`
   (+ `suspectRaw(address) → (Sc, Sp, pendingTag)`). `GhostLens` implémente **tout**
   `IGhostRisk` : les trois vues déplacées sont calculées sur les getters bruts, toutes les
   autres (`paused`, `destroyedAt`, `clearedAt`, `incidents`, `extendedUntil`,
   `maxExtensionEnd`, seuils…) sont relayées telles quelles au Ghost. `GhostUsdcPool` et
   `RiskBeacon` ne reçoivent donc toujours **qu'une** adresse `IGhostRisk` (immuable) : le Ghost
   sans repli, `GhostLens` avec. Un test `test_lens_matchesGhost` (si le repli est appliqué)
   compare chaque vue de `GhostLens` à son calcul direct sur un état non trivial.
3. **Initcode de `ProtectedMinter` > 49 152 o** : `GhostToken` est déployé à part avec
   l'adresse du minter prédite (`vm.computeCreateAddress` en test, nonce du déployeur en script)
   et `ProtectedMinter` vérifie au constructeur `ghost.minter() == address(this)` (revert
   `GhostMinterMismatch`).

Le choix effectif et les tailles mesurées sont recopiés dans le README.

**Chemins d'émission (remplace I4)** :

| Émission | Seul appelant | Effet sur `valeur(supply) = M.totalSupply + Ghost.totalSupply` |
|---|---|---|
| Ghost frais au déposant | `ProtectedMinter.completeSwap` → `ghost.issueFromMinter(…, requestId)` | `+minted`, et `totalIssued += minted` |
| Ghost frais au destinataire d'un transfert de M | `GhostedStable._update` → `ghost.onUnderlyingTransfer` | `−fee` (M brûlé `v`, Ghost émis `v − fee`) |
| M au convertisseur | `GhostToken.convert` → `M.mint` | `−fee` (Ghost brûlé `g`, M émis `g − fee`) |
| Ghost frais à une victime | exécution d'une restitution 2/3 | `+amount`, plafonné par `reserve()` |
| destruction | exécution d'une destruction 2/3 | `−burned` |

I1–I3 inchangés (montant et destinataire dérivés). I4 devient : « M n'est minté que par
`GhostToken.convert` ; le Ghost n'est émis que par les trois chemins ci-dessus ». I5 devient :
`valeur(supply) == totalIssued − Σburned − Σfees + Σrestituted ≤ totalIssued`.

## 2. `GhostedStable` (M)

- `ERC20("Protected USD (fictif)", "pUSD")`, 18 décimales, `address public immutable ghost`.
- `mint(to, amount)` : `msg.sender == ghost` sinon `NotMinter(caller)`.
- `_update(from, to, v)` surchargé : si `from != 0 && to != 0 && v > 0` →
  `super._update(from, address(0), v)` (brûle le M de l'expéditeur, émet
  `Transfer(from, 0, v)`) puis `IGhostToken(ghost).onUnderlyingTransfer(from, to, v)`. Sinon
  `super._update(from, to, v)`. `transfer` / `transferFrom` / allowances restent standard ;
  le destinataire ne reçoit **jamais** de M par transfert, toujours du Ghost (§0bis).
- Transfert de M vers soi-même (`from == to`) : traité comme les autres (devient du Ghost frais,
  le sens sûr ; aucun moyen de « rafraîchir » quoi que ce soit puisque M est déjà mûr).
- Erreurs : `NotMinter`, `ZeroAddress` (constructeur), erreurs ERC20 d'OpenZeppelin ; un hook qui
  revert (pause Ghost) fait échouer le transfert entier.

## 3. `GhostToken` (M-Ghost) — #8

`contract GhostToken is ERC20, AccessControl, GuardianActions` (`GuardianActions` étend
`GuardianPausable`). `ERC20("M-Ghost (fictif)", "gpUSD")`, 18 décimales. Un seul Ghost par
token ; le Ghost n'a pas de Ghost (§0bis-b) : un transfert de M-Ghost reste du M-Ghost.

### 3.1 Paramètres (immuables, fixés au constructeur)

```solidity
struct GhostConfig {
    uint64  window;              // W en secondes (> 0)
    uint64  slot;                // durée d'un créneau (> 0, window % slot == 0, window/slot <= 255)
    uint32  maxExtensionFactor;  // >= 1 : durée max d'un retard = factor × W
    uint16  quarantineBudgetBps; // <= 10_000 : part max de l'offre sous fenêtre allongée (incident courant)
    uint256 maxConvertRatio;     // <= 1e18 : ratio max autorisant la conversion (inclus)
    uint256 maxConvertSuspect;   // montant absolu suspect max autorisant la conversion (inclus)
    uint16  convertFeeBaseBps;   // marge Ghost -> M, partie fixe
    uint16  convertFeeSlopeBps;  // marge Ghost -> M, partie indexée : + slope × ratio / 1e18 ; base+slope <= 10_000
    uint16  entryFeeBps;         // marge M -> Ghost (transfert de M) ; <= 10_000
    uint64  restitutionClaimDelay; // délai avant bascule de la réserve au fonds d'assurance
}
```

Pas de setter : changer une valeur = redéployer (Fuji). Raison : aucun paramètre ne peut être
desserré par une clé admin (veto asymétrique §3, H1 limité au rôle surveillant). Toutes les
valeurs sont des **paramètres à mesurer** ; les valeurs de test (§8.0) sont des fixtures.
Validation constructeur → `InvalidConfig(uint8 field)` (revert, fatal au déploiement).
Les marges valent 0 par défaut dans les fixtures (§0 : barème à mesurer).

### 3.2 Tranches d'échéance (`MaturityBuckets`, §0bis-b)

Par adresse :

```solidity
struct Bucket { uint64 maturity; uint192 amount; }   // une slot de stockage
struct Account {
    uint256 matured;              // Ghost dont l'échéance est passée (agrégé, convertible)
    uint256 mask;                 // bit i = 1 ssi slots[i].amount > 0
    Bucket[256] slots;            // seuls les N+1 premiers indices sont utilisés
}
```

- N = `window / slot`. Anneau de **N + 1** entrées, index `(maturity / slot) % (N + 1)`.
- Échéance d'une valeur entrante à `t` : `m = ceilDiv(t + W, slot) * slot` (arrondi au créneau
  supérieur, le sens sûr ; `m ≥ t + W`).
- Pourquoi N + 1 suffit : à l'instant T, toute échéance non échue vérifie
  `T < m ≤ ceilDiv(T + W, slot) * slot` (une valeur transférée garde une échéance calculée à
  `t ≤ T`). Il y a au plus N + 1 multiples de `slot` dans cet intervalle, donc deux tranches non
  échues ne partagent jamais un index.
- `_settle(a)` : pour chaque bit de `mask`, si `maturity ≤ block.timestamp` → `matured += amount`,
  tranche vidée, bit effacé. Coût O(N + 1), lecture du masque en une SLOAD.
- `maturedEffectiveOf(a)` (vue) = `matured + Σ{amount | maturity ≤ now}` : la part **temporelle**
  seulement. La vue `convertibleOf(a)` y ajoute les verrous de risque (§3.5).
- Invariant de stockage : `balanceOf(a) == matured + Σ amount` (testé).
- Toute écriture de `Bucket.amount` passe par `SafeCast.toUint192` (OZ) : un dépassement revert
  (`SafeCastOverflowedUintDowncast`) au lieu de tronquer. Inatteignable en pratique (offre
  fictive), mais jamais silencieux.

**Envoi de `v` de `from` vers `to`** (`_moveBuckets`) : `_settle(from)`, `_settle(to)`, puis on
prélève d'abord `matured[from]` (le plus ancien) → `matured[to]`, puis les tranches non échues
de `from` par **échéance croissante** (parcours `k = 1..N+1`, `m = (floor(now/slot) + k) * slot`,
index de `m`, vérifier `slots[idx].maturity == m`), chacune ajoutée chez `to` au **même** index
avec la **même** échéance. Le Ghost frais reste chez l'expéditeur. Coût borné par N, indépendant
de l'historique. Variantes écartées (ne pas implémenter) : échéance moyenne pondérée, échéance
max, FIFO par lots.

**Émission fraîche** (`_issue(to, v)`) : `_settle(to)` puis ajout à la tranche d'échéance
`ceilDiv(now + W, slot) * slot`, puis `_mint(to, v)`.

### 3.3 Soupçon par adresse (§9)

Stockage par adresse : `suspectConfirmed[a]` (Sc), `suspectPending[a]` (Sp), `pendingTag[a]`
(id d'incident de Sp). Le **montant absolu suspect** est `S = Sc + Sp_valide` ; le **ratio**
est `S × 1e18 / balanceOf(a)` (virgule fixe 1e18, 0 si solde nul). Stocker S plutôt que le
ratio donne exactement la moyenne pondérée par les montants de §9, avec une seule
multiplication par transfert.

- `Sp` est **valide** ssi `incidents[pendingTag].confirmed` ou
  `block.timestamp < incidents[pendingTag].expiresAt`. Invalide ⇒ compte pour 0 (invalidation
  paresseuse, aucun nettoyage O(n)).
- `_normalize(a)` (écrit) : si Sp > 0 et incident confirmé → `Sc += Sp`, Sp = 0 ; si expiré non
  confirmé → `totalSuspectExpired += Sp`, Sp = 0 ; tag remis à 0 dans les deux cas.
- **Transfert de `v`** (après `_normalize(from)`, `_normalize(to)`, avec `B = balanceOf(from)`
  avant transfert) :
  `moved = ceilDiv(v × (Sc+Sp), B)` ; `movedC = min(Sc, ceilDiv(v × Sc, B))` ;
  `movedP = moved − movedC`. Expéditeur : `Sc −= movedC`, `Sp −= movedP`. Destinataire :
  `Sc += movedC`, `Sp += movedP` et `pendingTag = pendingTag[from]` si `movedP > 0`.
- Propriétés (prouvables à la main, **testées**) : la somme des soupçons est conservée
  **exactement** par un transfert (l'arrondi vers le haut ne fait que répartir, au plus 1 wei
  de plus chez le destinataire par transfert) ; `Sc + Sp ≤ balanceOf` reste vrai des deux côtés ;
  fractionner / disperser ne nettoie pas.
- Pourquoi deux composantes : une adresse peut détenir à la fois du soupçon confirmé (permanent
  jusqu'à destruction) et du soupçon en attente (auto-expirant). Une seule valeur étiquetée ne
  peut pas porter les deux sans soit perdre du confirmé, soit confirmer de l'attente.
- Après `_normalize`, tout Sp > 0 d'un destinataire porte le tag de l'unique incident non
  confirmé vivant (§3.4), qui est aussi celui de l'expéditeur : la fusion est toujours sûre.
  (Un Sp ne survit à `_normalize` que si son incident est non confirmé et vivant ; il n'y en a
  qu'un à la fois.)

- **Le soupçon ne sort jamais par conversion** (§3.5, verrou partiel) : la part suspecte valide
  `S` reste toujours sur le solde Ghost. C'est la projection de §9 « un lignage marqué suspect
  avant conversion reste en fenêtre allongée » : le verrou suit la **valeur** (comme l'échéance,
  §0bis-b), pas l'adresse marquée. Disperser ne nettoie donc ni la comptabilité ni le verrou.
- Arrondi : `ceilDiv` donne au moins 1 wei de soupçon à tout envoi depuis un compte marqué.
  Avec `maxConvertSuspect == 0`, un attaquant marqué peut bloquer **toute** conversion d'un tiers
  en lui envoyant 1 wei (durablement si l'incident est confirmé). Limite écrite au README :
  `maxConvertSuspect` doit être > 0 hors tests ; un test la mesure (§8.1).

Compteurs globaux pour les invariants : `totalSeeded`, `totalSuspectBurned`,
`totalSuspectExpired`, `totalSuspectCleared`. Conservation stockée :
`Σ_a (Sc + Sp) == totalSeeded − totalSuspectBurned − totalSuspectExpired − totalSuspectCleared`
(il n'y a plus de compteur « converti » : la conversion ne déplace pas de soupçon).

### 3.4 Incidents et rôle surveillant (§3, §9)

```solidity
struct Incident { uint64 openedAt; uint64 expiresAt; bool confirmed; uint256 extendedBalance; }
mapping(uint256 => Incident) public incidents;        // ids à partir de 1
uint256 public openIncidentId;                        // dernier incident ouvert (surveillant ou 2/3)
mapping(address => uint64)  internal _extendedUntil;  // fin de fenêtre allongée de a ; ne baisse JAMAIS
mapping(address => uint64)  public extensionRunStart; // début de la série d'extensions contiguës de a
mapping(address => uint256) public extensionTag;      // dernier incident ayant compté a dans son budget
```

`WATCHER_ROLE` (OZ `AccessControl`, géré par `DEFAULT_ADMIN_ROLE` = admin, hypothèse H1).
Une seule fonction surveillant, qui appelle la logique interne
`_delay(address[] memory accounts, uint256[] memory suspectAmounts, uint64 duration,
bool checkBudget, address actor)` :

`delay(address[] calldata accounts, uint256[] calldata suspectAmounts, uint64 duration)`
→ `_delay(accounts, suspectAmounts, duration, true, msg.sender)`. La voie humaine 2/3 hors
budget (§3.6bis, `Extend`) appelle `_delay(…, false, address(this))`. `actor` est le seul champ
d'acteur des événements `IncidentOpened` / `PerimeterDelayed` émis par `_delay` (jamais
`msg.sender`, qui vaudrait le 2e guardian à l'exécution 2/3).

1. Validation : longueurs égales (`LengthMismatch`), `1 ≤ length ≤ MAX_BATCH` (constante 64,
   `BatchTooLarge`), `whenNotPaused`, chaque compte ≠ 0 (`ZeroAddress`).
2. Incident cible : si `openIncidentId` est non confirmé et vivant (`now < expiresAt`) → on le
   **rejoint** ; `duration` est alors ignorée (l'échéance d'un incident ne change jamais).
   Sinon on **ouvre** `id + 1` avec `expiresAt = now + duration` ; `duration == 0` →
   `InvalidDuration()`, `duration > maxExtensionFactor × W` →
   `ExtensionTooLong(address(0), uint64(now + duration))` (même erreur `ExtensionTooLong(address
   account, uint64 end)` qu'à l'étape 3 ; `account == 0` = borne de l'incident).
   Émet `IncidentOpened(id, actor, expiresAt)`.
3. Pour chaque compte `a`, avec `end = incidents[id].expiresAt` :
   - `_normalize(a)` ;
   - **borne cumulée par compte** (garde-fou §9 « facteur max par périmètre ») :
     ```solidity
     if (_extendedUntil[a] == 0                                     // jamais allongé (évite runStart = 0
         || block.timestamp >= uint256(_extendedUntil[a]) + window) //  quand block.timestamp < W en test)
         extensionRunStart[a] = uint64(block.timestamp);            // au moins W sans extension : nouvelle série
     uint64 newEnd = end > _extendedUntil[a] ? end : _extendedUntil[a];
     if (newEnd > uint256(extensionRunStart[a]) + uint256(maxExtensionFactor) * window)
         revert ExtensionTooLong(a, newEnd);                       // tout le lot est annulé
     ```
     Ainsi, quelle que soit la suite d'incidents enchaînés (surveillant ou 2/3), une série
     contiguë d'extensions d'un compte dure au plus `maxExtensionFactor × W`, et deux séries sont
     séparées d'au moins W sans extension. Le cooldown vaut `window` (aucun nouveau paramètre ;
     valeur à mesurer, §9).
     **Énoncé honnête de la borne** (NIT 7) : elle porte sur la durée d'une série, pas sur la
     durée totale. Un surveillant compromis peut retarder un même compte `factor × W` sur chaque
     période de `(factor + 1) × W`, indéfiniment, soit une fraction du temps
     `factor / (factor + 1)` (6/7 avec les fixtures). C'est la formulation à reprendre au README
     et dans `docs/CLAIMS.md` (proposition de PR) : « friction bornée en taux », jamais « durée
     bornée ». Le remède à un surveillant compromis reste H1 (révocation de `WATCHER_ROLE` par
     l'admin).
     Vue de lecture pour le surveillant (NIT 6), même calcul que ci-dessus, sans écriture :
     ```solidity
     function maxExtensionEnd(address a) external view returns (uint64) {
         uint256 start = (_extendedUntil[a] == 0
                          || block.timestamp >= uint256(_extendedUntil[a]) + window)
             ? block.timestamp : extensionRunStart[a];
         return uint64(start + uint256(maxExtensionFactor) * window);
     }
     ```
     Un `delay` dont l'incident cible a `expiresAt ≤ maxExtensionEnd(a)` pour chaque compte ne
     revert pas pour `ExtensionTooLong` (testé : `test_maxExtensionEnd_predictsRevert`).
   - `_extendedUntil[a] = newEnd` (**ne fait que monter** : un second incident plus court ne
     raccourcit jamais une extension en cours) ;
   - semis : `Sp' = max(Sp, min(amount, balanceOf − Sc))` (ne fait qu'augmenter ;
     `totalSeeded += Sp' − Sp`) ; `pendingTag = id` si `Sp' > 0` (un Sp déjà présent après
     `_normalize` porte forcément `id`, l'unique incident non confirmé vivant) ;
   - budget : si `extensionTag[a] != id` → `extensionTag[a] = id`,
     `incidents[id].extendedBalance += balanceOf(a)` ;
   - émet `PerimeterDelayed(id, a, actor, Sp', newEnd)` (= `AlertSeed` + `ResponseAction`).
4. Budget, seulement si `checkBudget` : après la boucle, exiger
   `incidents[id].extendedBalance × 10_000 ≤ quarantineBudgetBps × supplyValue()` sinon revert
   `QuarantineBudgetExceeded(extendedBalance, supplyValue)` (tout le lot est annulé ; au-delà,
   extension = humain requis → `Extend` 2/3, §3.6bis).

**Définition unique de `extendedBalance(id)`** : `Σ balanceOf(a)` pour les `a` tels que
`extensionTag[a] == id`. Maintenu dans **toutes** les branches de `_update` (mint, burn,
transfert) : pour `from` (resp. `to`) non nul avec `extensionTag == openIncidentId`, on retire
(resp. ajoute) `v` à `incidents[openIncidentId].extendedBalance`. Seul l'incident courant est
maintenu (les plus anciens ne servent plus au budget) ; le coût reste O(1). Le budget n'est
**vérifié** qu'à la fin d'un `delay` (seule l'action du surveillant est bornée, §9 choix 7).

`isExtended(a) = block.timestamp < _extendedUntil[a]` ; vue `extendedUntil(a)` = `_extendedUntil[a]`
si `> now`, sinon 0. La confirmation d'un incident ne raccourcit ni ne prolonge une extension.

Ce que le surveillant **ne peut pas** faire, par construction : détruire, pauser, dépauser,
confirmer, blanchir, raccourcir une extension (`_extendedUntil` monotone), baisser un Sp, lever
une extension, prolonger un incident vivant, dépasser `maxExtensionFactor × W` par série et par
compte, dépasser le budget. Silence ⇒ à `expiresAt`, les Sp de l'incident deviennent sans effet
et, à `_extendedUntil`, la conversion redevient possible (retour automatique à NORMAL).

**Compte détecté tard** (constat 8 de la revue) : un compte qui **rejoint** l'incident vivant
n'est retenu que jusqu'à `expiresAt` (marge = `max(échéance propre, expiresAt − now)`), et au
bloc `timestamp == expiresAt` son Sp expire. Choix retenu : **documenter et mesurer** (README +
test `test_lateJoin_marginIsRemainingLifetime`), sans bascule d'incident (deux incidents non
confirmés vivants casseraient la fusion O(1) des `pendingTag`). Parade humaine écrite au README :
une confirmation 2/3 (liste vide, §3.6) avant `expiresAt` transforme Sp en Sc, qui reste
verrouillé (§3.5) jusqu'à destruction ou blanchiment. ★ §9.

### 3.5 Conversion Ghost → M (§0bis-b, §0, §9)

`convert(uint256 amount) returns (uint256 tokenOut)`, `whenNotPaused`, pour `msg.sender` :

1. `amount > 0` (`ZeroAmount`) ; `_settle`, `_normalize`. On note `S = Sc + Sp` (après
   `_normalize`, Sp restant = Sp valide), `ratioUp = Math.mulDiv(S, 1e18, balanceOf,
   Math.Rounding.Ceil)` (comparaison au seuil, sens sûr) et `ratio = S × 1e18 / balanceOf`
   (arrondi bas, pour la marge et les événements). Si `balanceOf == 0`, revert
   `NotMatured(amount, 0)` **avant** tout calcul de ratio (pas de division par zéro).
2. `amount ≤ matured[a]` sinon `NotMatured(amount, matured)` — seules les tranches échues.
3. `!isExtended(a)` sinon `WindowExtended(_extendedUntil[a])` — l'adresse marquée (le périmètre)
   ne convertit rien pendant le retard (§3 point 2).
4. `ratioUp ≤ maxConvertRatio` et `S ≤ maxConvertSuspect` sinon
   `SuspicionAboveThreshold(ratioUp, S)` — le seuil de §9 (ratio **et** montant absolu). Test
   `test_threshold_ratioRoundedUp` : un ratio exact juste au-dessus du seuil (reste non nul)
   revert.
5. **Verrou partiel du lignage** (constat 1 de la revue, option B) : `amount ≤ balanceOf − S`
   sinon `SuspectPartLocked(amount, balanceOf − S)`. La part suspecte valide ne se convertit
   **jamais** : soupçon en attente jusqu'à l'expiration de son incident (silence) ou sa
   confirmation ; soupçon confirmé jusqu'à destruction ou blanchiment 2/3. Pourquoi l'option B
   plutôt que A (blocage total dès que `Sp ≠ 0`) : A laisse 1 wei marqué geler la conversion
   entière d'un gros porteur (contraire à « pas de tache d'huile », §9, et à l'invariant (b)
   « la poussière ne retarde que la poussière ») ; B ne retient que la part suspecte, ce qui suffit
   à empêcher l'évasion par dispersion : un fan-out de Ghost entièrement suspect donne des
   adresses où `balanceOf − S ≈ 0`, rien ne sort, quels que soient les seuils.
6. `fee = amount × (convertFeeBaseBps + convertFeeSlopeBps × ratio / 1e18) / 10_000` (arrondi
   bas) ; `tokenOut = amount − fee`.
7. Le soupçon ne bouge pas (Sc, Sp inchangés ; le ratio du reste monte mécaniquement).
8. `matured −= amount`, `_burn(a, amount)`, `M.mint(a, tokenOut)` ; `totalFees += fee`,
   `lastReserveInflowAt = now` si `fee > 0`. Émet `GhostConverted`.

`convertibleOf(a)` (vue) = 0 si `isExtended(a)` ou seuils dépassés, sinon
`min(maturedEffectiveOf(a), balanceOf − S_valide)`. Le M obtenu n'est jamais repris (aucune fonction
ne brûle du M hors transfert par son détenteur). « Ghost converti avant le gel : irréversible,
voulu » (§9) reste vrai : seul le Ghost **sans** soupçon valide au moment de la conversion sort.

### 3.6 Destruction (multisig 2/3, §3, §9)

`proposeDestroy(uint256 incidentId, address[] calldata targets) returns (uint256 proposalId)`
(guardian ; compte comme 1re approbation ; `targets.length ≤ MAX_BATCH`, liste vide autorisée =
**confirmation seule**). Exécution à la 2e approbation (`approveAction(proposalId)`) :

1. Incident `1 ≤ incidentId ≤ openIncidentId` ; s'il n'est pas confirmé, il doit être vivant
   (`IncidentExpired` sinon : ressusciter des marques expirées serait incohérent). Marqué
   `confirmed = true`, émet `IncidentConfirmed`.
2. Pour chaque cible (doublons tolérés, la 2e occurrence brûle 0) : `_normalize` (le Sp de
   `incidentId`, désormais confirmé, bascule en Sc), `_settle`, puis
   `burned = suspectConfirmed[a]` **seulement** (= ratio confirmé × solde Ghost non converti,
   exact puisque `Sc/B × B = Sc`). Un Sp restant après `_normalize` appartient forcément à un
   autre incident vivant non confirmé : il **n'est pas** brûlé (pas de destruction sans quorum
   sur cet incident). Brûlé en vidant d'abord les tranches **les plus récentes** puis `matured` ;
   `Sc = 0` ; `_burn(a, burned)` ; `totalBurned += burned`, `totalSuspectBurned += burned` ;
   `destroyedAt[a] = now`, `destroyedIncident[a] = incidentId` (enregistrés même si
   `burned == 0` : le pool s'en sert, §6). Émet `GhostDestroyed`.
3. `lastReserveInflowAt = now` si quelque chose a été brûlé.

Utilisable pendant la pause globale (action humaine de récupération). Les rounds 2/3 sont
indépendants de `pauseRound` (3/3). Le budget n'est pas affecté (le solde brûlé sort de
`extendedBalance` par la branche burn de `_update`, §3.4).

### 3.6bis Extension hors budget et blanchiment (multisig 2/3, §9)

- **`proposeExtend(address[] accounts, uint256[] suspectAmounts, uint64 duration)`** → à la 2e
  approbation : `_delay(accounts, suspectAmounts, duration, false)` — même logique que le
  surveillant (§3.4), **sans** vérification de budget (§9 : « au-delà, extension = humain
  requis »), toujours bornée par `maxExtensionFactor × W` par incident **et** par la borne
  cumulée par compte, toujours auto-expirante, `whenNotPaused`. Émet les mêmes
  `IncidentOpened` / `PerimeterDelayed` (champ `actor` = `address(this)` pour distinguer la voie
  2/3 du surveillant, passé explicitement à `_delay`, §3.4).
  **Interaction avec l'incident courant** (NIT 8) : s'il existe un incident vivant non
  confirmé, `Extend` le **rejoint** comme le surveillant : `duration` est ignorée (les humains
  n'allongent pas au-delà de `expiresAt` ; pour aller plus loin, il faut confirmer puis ouvrir
  un nouvel incident, toujours sous la borne cumulée), et les soldes ajoutés entrent dans
  `extendedBalance`. Conséquence voulue (§9 « au-delà, extension = humain requis ») : après un
  `Extend` hors budget, chaque `delay` du surveillant revert `QuarantineBudgetExceeded`
  jusqu'à `expiresAt` (ou jusqu'à confirmation, qui permet d'ouvrir un incident neuf au budget
  vierge). Écrit au README ; test `test_extendOverBudget_blocksWatcherUntilExpiry`.
- **`proposeClear(address[] accounts)`** (≤ `MAX_BATCH`) → à la 2e approbation, pour chaque
  compte : `_normalize`, `cleared = Sc + Sp`, `Sc = Sp = 0`, `totalSuspectCleared += cleared`,
  `clearedAt[a] = now`. Émet `SuspicionCleared(a, proposalId, cleared)`. C'est « audit blanchissant
  → ratios remis à 0 » (§9, #33). `_extendedUntil` n'est **pas** touché : l'extension d'adresse
  expire seule (choix le plus simple, garde la monotonie ; ★ §9). Utilisable pendant la pause.
  Le blanchiment ne déplace aucune valeur : la solvabilité n'est pas affectée.

### 3.7 Réserve de restitution et fonds d'assurance (§0bis-c)

- `totalIssued` (Ghost) == `ProtectedMinter.totalMinted` (valeur du collatéral adossant
  l'offre émise, au taux figé des demandes ; H1 : taux honnête, pas d'oracle).
- `supplyValue() = M.totalSupply() + totalSupply()`.
- `reserve() = totalIssued − supplyValue − insuranceFund`, **saturé à 0** (ne devient négatif
  que si l'invariant de solvabilité est cassé, ce que les tests vérifient).
- `proposeRestitution(address to, uint256 amount)` → à la 2e approbation : `whenNotPaused`,
  `amount > 0`, `to ≠ 0`, `amount ≤ reserve()` sinon `ExceedsReserve(amount, reserve)` (la
  proposition reste ouvrable plus tard ; aucune exécution partielle). Émet du Ghost **frais** à
  `to` (`_issue`), `totalRestituted += amount`, émet `Restituted`.
- `sweepToInsurance()` permissionless : exige `now ≥ lastReserveInflowAt + restitutionClaimDelay`
  et `reserve() > 0` ; `insuranceFund += reserve()`. Le fonds est un compteur comptable (aucun
  token minté) ; son emploi est hors périmètre. Émet `ReserveSweptToInsurance`.
- Conséquence assumée (★ §9-9) : avec des marges > 0, chaque `convert` ou transfert de M repousse
  `lastReserveInflowAt` ; sous trafic continu la bascule n'arrive donc jamais et toute la réserve
  reste disponible pour la restitution. Avec les marges à 0 (fixtures), seules les destructions
  repoussent la minuterie.

### 3.8 Pause globale 3/3

`GuardianPausable` réutilisé tel quel (`approvePause` / `approveUnpause`, même multisig). En
pause : transferts de Ghost, `convert`, `onUnderlyingTransfer` (donc tout transfert de M),
`issueFromMinter` (donc `completeSwap`), `delay`, restitution → revert `EnforcedPause`.
Restent possibles : approbations de pause/dépause, propositions et destructions 2/3,
`sweepToInsurance`, `Clear` 2/3, vues. Bloqués aussi : `Extend` 2/3. La pause propre de
`ProtectedMinter` (3/3) reste distincte et inchangée.

Horloges pendant la pause (écrit au README) : les incidents et les extensions continuent
d'expirer sur `block.timestamp`, alors que `delay` est bloqué. À la dépause, des Sp peuvent avoir
expiré. Parade : confirmer (liste vide) ou détruire pendant la pause, ce qui reste permis.

### 3.9 Intégration ERC20 et points d'entrée externes

- `_update(from, to, v)` surchargé : si `from != 0 && to != 0` → `whenNotPaused` ; si `v == 0`
  ou `from == to` → `super._update` seul (aucun effet sur tranches/soupçon) ; sinon, dans cet
  ordre : `B = balanceOf(from)` mis en cache, `if (B < v) revert
  ERC20InsufficientBalance(from, B, v)` (NIT 11 : l'erreur OZ standard, avant toute écriture,
  jamais une panique de la librairie), `_normalize` ×2, déplacement du soupçon (§3.3, avec ce
  `B`), `_moveBuckets` (§3.2), mise à jour `extendedBalance`, `super._update`, émet
  `GhostTransferred`. Si `from == 0` ou `to == 0` :
  tranches et soupçon gérés en amont par `_issue` / `convert` / destruction, mais
  `extendedBalance` est **quand même** mis à jour (côté non nul) avant `super._update` : c'est
  la seule branche commune à toutes les émissions et tous les brûlages (constat 5).
- `issueFromMinter(address to, uint256 amount, uint256 requestId)` : `msg.sender == minter`
  (`NotMinter`), `whenNotPaused`, `_issue`, `totalIssued += amount`,
  `GhostIssued(recipient = to, source = minter, requestId, …, kind = MINT)`. `requestId` est
  l'id de la demande traitée par `completeSwap` (constat 3ter) ; le Ghost ne le valide pas (seul
  le minter peut appeler, et il passe l'id qu'il vient de traiter).
- `onUnderlyingTransfer(address from, address to, uint256 v)` : `msg.sender == underlying`
  (`NotUnderlying`), `whenNotPaused` ; `fee = v × entryFeeBps / 10_000` ; si `v − fee > 0` :
  `_issue(to, v − fee)` ; `totalFees += fee` ; `if (fee > 0) lastReserveInflowAt =
  uint64(block.timestamp)` (NIT 4, cohérent avec §3.7) ;
  `GhostIssued(recipient = to, source = from, requestId = 0, …, kind = TRANSFER_M)`.
  Le M entrant est propre : ratio entrant 0.
- Restitution (§3.7) : `GhostIssued(recipient = to, source = address(this), requestId = 0, …,
  kind = RESTITUTION)`. `requestId` n'a de sens que si `kind == MINT`.
- Pas de réentrance possible : M et Ghost s'appellent mutuellement sans rappel externe arbitraire
  (`M.mint` n'a pas de hook, le hook de M ne fait que minter du Ghost). Pas de `ReentrancyGuard`.

### 3.10 `GuardianActions` (2/3)

```solidity
enum ActionKind { Destroy, Restitution, Extend, Clear }
struct Proposal { ActionKind kind; bool executed; uint8 approvals; bytes params; }
mapping(uint256 => Proposal) public proposals;  // ids à partir de 1
mapping(uint256 => mapping(address => bool)) public hasApprovedAction;
uint256 public constant ACTION_QUORUM = 2;
error ActionAlreadyApproved(address guardian, uint256 proposalId); // AlreadyApproved existe déjà dans GuardianPausable
```

`approveAction(id)` (nom distinct de `ERC20.approve(address,uint256)` pour éviter une surcharge
qui piège ethers et le monitor) : guardian (`NotGuardian`), proposition existante
(`UnknownProposal`), non exécutée (`AlreadyExecuted`), pas déjà approuvée par ce guardian
(`ActionAlreadyApproved`). Chaque `propose*` compte comme 1re approbation du proposeur. À 2
approbations : `executed = true` **avant** d'appeler `_execute(kind, params)` (virtuel,
implémenté par `GhostToken`). Si `_execute` revert (ex. `ExceedsReserve`), toute la transaction
revert : la proposition reste ouverte à 1 approbation. Pas d'expiration ni de révocation de
proposition (même simplification assumée que `GuardianPausable`). Événements
`ActionProposed(id, kind, proposer)`, `ActionApproved(id, guardian, approvals)`,
`ActionExecuted(id, kind)`.

### 3.11 Vues (`IGhostRisk`)

`effectiveSuspectOf(a)`, `suspectComponentsOf(a) → (Sc, SpValide, pendingTag)`, `ratioOf(a)`
(1e18), `extendedUntil(a)` (0 si non allongé), `convertibleOf(a)`, `maturedEffectiveOf(a)`,
`maturedOf(a)` (agrégé brut),
`bucketsOf(a) → (uint64[] maturities, uint256[] amounts)` (tests), `nextOutgoingMaturity(a, v)`
(échéance la plus tardive parmi les tranches qui partiraient pour un envoi de `v` ; 0 si tout
vient de la part échue). Comme `maturedEffectiveOf`, cette vue applique un **règlement
virtuel** (NIT 12) : les tranches `maturity ≤ block.timestamp` sont comptées dans la part
échue même si `_settle` n'a pas encore tourné ; sinon l'échéance de créance du pool serait
surestimée. Test `test_nextOutgoingMaturity_virtualSettle` (tranche échue non réglée, vente au
pool ⇒ `claim.maturity == now`). Aussi : `maxExtensionEnd(a)` (§3.4), `destroyedAt(a)`,
`destroyedIncident(a)`, `clearedAt(a)`, `pendingTag(a)`,
`extensionRunStart(a)`, `extensionTag(a)`, `incidents(id)` (dont `extendedBalance`),
`openIncidentId`, `reserve()`, `supplyValue()`, `totalIssued`, `window()`, `slot()`, seuils et
marges (getters de la config), `paused()`.

### 3.12 Événements (monitor, `docs/CONTRACTS.md`)

| Événement | Champs | Modèle `shared/` correspondant |
|---|---|---|
| `GhostIssued` | `recipient`↑, `source`↑ (minter / expéditeur M / Ghost), `requestId`↑ (id de demande si MINT, 0 sinon), `amount`, `incomingRatio` (0), `maturity`, `kind` (MINT / TRANSFER_M / RESTITUTION) | `GhostTokenMintEvent` (+ `MintEvent.request_id` si MINT) |
| `GhostTransferred` | `from`↑, `to`↑, `amount`, `incomingRatio` (1e18), `suspectMoved`, `latestMaturity` | `GhostTokenMintEvent` (+ `TransferEvent.is_ghost=true`) |
| `GhostConverted` | `holder`↑, `ghostAmount`, `tokenAmount`, `feeAmount`, `ratio` | `GhostTokenRedemptionEvent` |
| `IncidentOpened` | `incidentId`↑, `actor`↑ (surveillant, ou `address(this)` pour `Extend` 2/3), `expiresAt` | `ResponseAction(delay)` |
| `PerimeterDelayed` | `incidentId`↑, `account`↑, `actor`↑ (surveillant, ou `address(this)` pour `Extend` 2/3), `suspectAmount`, `extendedUntil` | `AlertSeed` / `QuarantineRecord(extended)` |
| `SuspicionCleared` | `account`↑, `proposalId`↑, `clearedAmount` | `ReleaseDecision(release)` |
| `IncidentConfirmed` | `incidentId`↑, `proposalId`↑ | `ReleaseDecision(confirm_destroy)` |
| `GhostDestroyed` | `account`↑, `incidentId`↑, `proposalId`↑, `burnedAmount`, `ratio`, `suspectAmount` | `GhostTokenBurnEvent` (`decision_id` = `proposalId`) |
| `Restituted` | `to`↑, `proposalId`↑, `amount` | `AuditLogEntry` |
| `ReserveSweptToInsurance` | `amount`, `insuranceFundTotal` | `AuditLogEntry` |
| `ActionProposed` / `ActionApproved` / `ActionExecuted` | voir §3.10 | `ReleaseDecision` |
| `GuardianApproval`, `Paused`, `Unpaused`, `RoleGranted`… | hérités | inchangé |

↑ = indexé. Ratios toujours en entier virgule fixe 1e18 (le monitor convertit en `float`).

**Lecture monitor par adresse** (constat 3ter ; `monitor/listener.py` sur `origin/main` filtre
par **une** adresse de token, classe tout `Transfer(0x0, to)` en mint avec
`request_id = UNKNOWN_REQUEST_ID` et exclut les `to == 0x0`). Avec ce design, trois adresses
émettent des logs utiles et `Transfer(0x0, …)` ne veut pas toujours dire « mint » :

| Adresse | Log(s) dans la même transaction | Sens |
|---|---|---|
| `ProtectedMinter` | `SwapCompleted(requestId, depositor, recipient, depositAmount, mintedAmount, rate)` | **mint** (« demande n°X → déposant → montant ») : événement de référence pour le décodeur de mint dédié (#9), inchangé |
| M-Ghost | `Transfer(0x0, to)` + `GhostIssued(kind = MINT, requestId)` | Ghost frais du mint ; `requestId` == celui de `SwapCompleted` |
| M-Ghost | `Transfer(0x0, to)` + `GhostIssued(kind = TRANSFER_M, source)` | Ghost frais d'un transfert de M de `source` vers `to` |
| M-Ghost | `Transfer(0x0, to)` + `GhostIssued(kind = RESTITUTION)` + `Restituted` | restitution 2/3 |
| M-Ghost | `Transfer(from, to)` + `GhostTransferred` | transfert de Ghost (`is_ghost = true`) |
| M-Ghost | `Transfer(a, 0x0)` + `GhostConverted` / `GhostDestroyed` | conversion / destruction |
| M | `Transfer(from, 0x0)` + `GhostIssued(TRANSFER_M)` côté Ghost | transfert de M (`is_ghost = false`), à reconstruire depuis `GhostIssued.source → recipient` |
| M | `Transfer(0x0, a)` + `GhostConverted` côté Ghost | conversion Ghost → M, **jamais** un mint |

Conséquences pour #9 / #10 (proposées en PR, §10, aucun fichier `monitor/` modifié) : le décodeur
ERC-20 générique ne doit **pas** être branché sur M comme détecteur de mint ; le mint se lit sur
`SwapCompleted` (ou `GhostIssued(kind = MINT)`) ; `token_is_ghost = true` pour l'adresse M-Ghost
seulement ; un transfert de M se reconstruit depuis `GhostIssued(TRANSFER_M)`.

**Id de demande 0** : `ProtectedMinter.nextRequestId` part de 0, donc la première demande
porte l'id 0, qui coïncide avec la sentinelle provisoire `UNKNOWN_REQUEST_ID = 0` du listener.
Choix retenu : **ne pas changer** la numérotation du volet 1 (mergé en PR #71, testé avec l'id 0
dans `ProtectedMinter.t.sol` l. 101 et 245). Sur la chaîne il n'y a pas d'ambiguïté : l'id
vient toujours d'un événement qui le porte (`SwapCompleted`, ou `GhostIssued` avec
`kind == MINT`). La sentinelle n'existe que pour le décodeur générique, que le listener prévoit
de **remplacer** (et non compléter) par un décodeur dédié ; la PR propose au propriétaire de
`monitor/` de retirer la sentinelle à ce moment. ★ §9-20.

Test `test_events_monitorMapping` (`test/ghost/GhostEvents.t.sol`) : `vm.expectEmit` sur la
suite exacte de logs (adresse émettrice comprise) pour un mint (dont `GhostIssued.requestId ==`
id de `SwapCompleted`, cas id 0 inclus), un transfert de M, un transfert de Ghost, une conversion,
une destruction et une restitution.

### 3.13 Erreurs et validation (Ghost)

Toutes les erreurs sont des `revert` à erreur personnalisée : l'état n'est jamais modifié
partiellement, l'appelant reçoit le sélecteur et ses arguments, le journal est l'absence
d'événement (aucun log on-chain d'un échec ; le monitor voit la transaction échouée). Aucune
n'est « avalée » : chacune est récupérable en corrigeant l'appel, sauf `InvalidConfig` (fatal,
redéployer).

| Opération | Erreur | Condition |
|---|---|---|
| constructeur | `InvalidConfig(field)`, `ZeroAddress`, `InvalidGuardian` | config §3.1, adresses nulles, guardians |
| transfert / transferFrom | `EnforcedPause`, erreurs ERC20 OZ | pause ; solde / allowance |
| `convert` | `ZeroAmount`, `NotMatured`, `WindowExtended`, `SuspicionAboveThreshold`, `SuspectPartLocked`, `EnforcedPause` | §3.5 |
| `delay` | `AccessControlUnauthorizedAccount`, `LengthMismatch`, `BatchTooLarge`, `ZeroAddress`, `InvalidDuration`, `ExtensionTooLong`, `QuarantineBudgetExceeded`, `EnforcedPause` | §3.4 |
| `proposeDestroy` / `proposeRestitution` / `proposeExtend` / `proposeClear` (**contrôles sans état seulement**) | `NotGuardian`, `BatchTooLarge`, `LengthMismatch`, `ZeroAddress`, `ZeroAmount`, `InvalidDuration` (`duration == 0`), `ExtensionTooLong(address(0), …)` (`duration > factor × W`), `UnknownIncident` (`incidentId == 0` ou `> openIncidentId`) | §3.6, §3.6bis, §3.7 |
| `approveAction` → `_execute` (**tout**, état compris) | `NotGuardian`, `UnknownProposal`, `AlreadyExecuted`, `ActionAlreadyApproved`, puis à l'exécution : tous les contrôles sans état ci-dessus **et** `IncidentExpired`, `ExceedsReserve`, `ExtensionTooLong(a, …)` (borne cumulée), `EnforcedPause` (Restitution, Extend) | §3.6, §3.6bis, §3.7, §3.10 |
| `sweepToInsurance` | `ClaimDelayNotElapsed`, `NothingToSweep` | §3.7 |
| `issueFromMinter` / `onUnderlyingTransfer` | `NotMinter` / `NotUnderlying`, `EnforcedPause` | §3.9 |

Découpage proposition / exécution (NIT 14) : une proposition ne vérifie que ce qui ne peut pas
changer avec le temps ; tout ce qui dépend de l'état (réserve, vie de l'incident, borne
cumulée, pause) n'est vérifié qu'à l'exécution. Ainsi une restitution peut être proposée avant
que la réserve soit alimentée, et s'exécute à la 2e approbation une fois la réserve suffisante
(test `test_restitution_proposedBeforeReserve_executesLater`).

Entrées externes : montants `uint256` (0 refusé là où cela n'a pas de sens), listes bornées à
`MAX_BATCH = 64` (borne de gas, constante), adresses non nulles, `duration` bornée par
`maxExtensionFactor × W`. Les invariants « solvabilité », « rien de convertible avant W » et
« le surveillant ne va que dans le sens sûr » sont appliqués **dans `GhostToken`** (seule couche
qui voit tous les mouvements ; aucun consommateur aval ne peut les contourner).

## 4. `RiskBeacon` — #7

Façade **sans état d'écriture propre** : toutes les écritures de risque vivent dans
`GhostToken` avec les permissions de §3 (surveillant = `delay` auto-expirant ; guardians = 2/3
confirmation/destruction, 3/3 pause). Raison : une seule source de vérité, aucun second système
de permissions à synchroniser ; la balise ne peut donc ni inventer ni effacer un risque.

```solidity
enum PerimeterState { NORMAL, RETARDE, DETRUIT, PAUSE_GLOBALE }
struct Risk { uint256 ratio; uint256 suspectAmount; uint64 windowExpiresAt; PerimeterState state; uint256 incidentId; }
constructor(IGhostRisk ghost)                       // immuable, != 0
function riskOf(address account) external view returns (Risk memory);
function publish(address[] calldata accounts) external; // permissionless, <= MAX_BATCH, émet RiskPublished
event RiskPublished(address indexed account, PerimeterState state, uint256 ratio, uint256 suspectAmount, uint64 windowExpiresAt, uint256 incidentId);
```

État (priorité décroissante) : `PAUSE_GLOBALE` si `ghost.paused()` ; `DETRUIT` si
`destroyedIncident(a) != 0` et `now < max(incidents[destroyedIncident].expiresAt,
destroyedAt(a) + W)` (une re-destruction sous un incident confirmé déjà expiré reste donc
visible au moins W) ; `RETARDE` si
`ghost.extendedUntil(a) > 0` ; sinon `NORMAL` (même avec un ratio > 0 : le ratio est le prix du risque,
l'état est la machine à états §3).

Source de chaque champ de `Risk` (NIT 9) : `ratio = ghost.ratioOf(a)` ;
`suspectAmount = ghost.effectiveSuspectOf(a)` ; `windowExpiresAt = ghost.extendedUntil(a)`
(0 si non allongé ; = `RiskBeaconUpdate.window_expires_at`, « fin de fenêtre allongée en
cours ») ; `incidentId` : `DETRUIT` → `destroyedIncident(a)` ; `RETARDE` → `extensionTag(a)` ;
`NORMAL` et `PAUSE_GLOBALE` → `pendingTag(a)` si son Sp est valide (incident confirmé ou
vivant), sinon 0. Après expiration, un compte détruit repasse NORMAL (silence =
retour, son soupçon a été brûlé). `publish` relit le Ghost : n'importe qui peut le déclencher
sans pouvoir fausser les valeurs. Erreurs : `BatchTooLarge`, `ZeroAddress` (constructeur).

## 5. `MockLendingMarket` (fictif) — #7, cœur §0/§4

Prête du `MockUSDC` contre du M ou du M-Ghost déposé. Prix fixe fictif : 1 M = 1 M-Ghost (face)
= 1 USDC, soit `1e18` unités → `1e6` unités. Pas d'intérêts, pas de liquidation : le marché
sert à **mesurer** des mauvaises créances (scénario C), pas à les gérer. Liquidité USDC apportée
par simple transfert (faucet `MockUSDC`) ; pas de comptabilité LP.

```solidity
struct MarketConfig {
    bool    useBeacon;          // false = configuration de comparaison qui ignore la balise
    uint16  ltvBps;             // <= 10_000
    uint16  baseHaircutBps;     // décote de base (Ghost et M)
    uint16  slopeHaircutBps;    // + slope × ratio / 1e18 (Ghost seulement) ; base+slope <= 10_000
    uint256 maxBorrowRatio;     // refus de nouvel emprunt au-delà (1e18)
    uint256 maxBorrowSuspect;   // refus au-delà (montant absolu)
}
struct Position { uint256 ghost; uint256 m; uint256 suspect; uint256 debt; uint64 unlockAt; }
constructor(IERC20 ghost, IERC20 m, IERC20 usdc, RiskBeacon beacon, uint64 window, uint64 slot, MarketConfig memory cfg)
// beacon == address(0) autorisé seulement si !cfg.useBeacon (sinon ZeroAddress) ;
// window/slot copiés du Ghost au déploiement (le marché ne lit pas IGhostRisk).
```

- `deposit(ghostAmt, mAmt)` (au moins un > 0, sinon `ZeroAmount`) :
  - Chaque jambe est comptée au **delta mesuré** de `ghost.balanceOf(market)` autour du
    `safeTransferFrom` (constat 18) : un dépôt de M arrive chez le marché en Ghost frais (§0bis),
    diminué de la marge d'entrée ; `position.m` reçoit ce delta, pas `mAmt`.
  - Soupçon importé, **uniquement si `cfg.useBeacon`** (constat 9 : la décote lit la balise) :
    ```solidity
    uint256 before = beacon.riskOf(address(this)).suspectAmount;
    // ... transferts ...
    p.suspect += beacon.riskOf(address(this)).suspectAmount - before;
    ```
    Si `useBeacon == false` : aucun appel à la balise ni au Ghost en lecture de risque,
    `p.suspect` reste 0 (testé par `vm.expectCall(beacon, …, 0)`).
  - Verrou unique de position (constat 4) : `p.unlockAt = max(p.unlockAt, now + window + slot)`
    dès que `ghostAmt + mAmt > 0`. Sans ce verrou, déposer du M puis retirer aussitôt sortirait
    les tranches **les plus anciennes** du marché (souvent échues) et contournerait la fenêtre de
    §0bis.
- Décote d'une position : `ratioPos = p.ghost == 0 ? 0 : p.suspect × 1e18 / p.ghost`
  (constat 3 : une position M seule ne divise jamais par zéro) ;
  `haircutBps = useBeacon ? min(10_000, base + slope × ratioPos / 1e18) : base`.
  `collateralValue = (m × (10_000 − base) + ghost × (10_000 − haircutBps)) / 10_000` converti en
  USDC (`/1e12`, arrondi bas).
- `borrow(usdcAmt)` : `usdcAmt > 0` ; si `useBeacon` : `beacon.riskOf(msg.sender)` doit avoir
  `state == NORMAL`, `ratio ≤ maxBorrowRatio`, `suspectAmount ≤ maxBorrowSuspect`, et
  `ratioPos ≤ maxBorrowRatio`, `suspect ≤ maxBorrowSuspect` sinon `RiskTooHigh(ratio, suspect,
  state)` ; puis `debt + usdcAmt ≤ collateralValue × ltv / 10_000` sinon `Undercollateralized` ;
  liquidité disponible sinon `InsufficientLiquidity`. Transfert USDC.
- `repay(usdcAmt)` : ≤ dette (`RepayExceedsDebt`), `transferFrom` USDC.
- `withdraw(ghostAmt, mAmt)` : dès que `ghostAmt + mAmt > 0`, exige `now ≥ p.unlockAt`
  (`CollateralLocked(unlockAt)`), pour **toutes** les jambes ; la position reste saine après
  retrait (`Undercollateralized`) ; `ghostAmt ≤ p.ghost` et `mAmt ≤ p.m`
  (`ExceedsPosition`) ; seulement si `ghostAmt > 0` :
  `p.suspect -= Math.min(p.suspect, Math.ceilDiv(ghostAmt × p.suspect, p.ghost))` (jamais de
  `ceilDiv(0, 0)` : `ghostAmt > 0 ⇒ p.ghost > 0`) ; envoi en Ghost (le marché n'a que du Ghost). Le Ghost retiré garde ses échéances et apporte le
  ratio du marché (§9 : un pool se redistribue au retrait).
- Vues : `positionOf(b)`, `collateralValue(b)`, `haircutBps(b)`, `totalDebt`.

Limite assumée (documentée README) : le marché est **une** adresse pour le Ghost, donc un seul
ratio mélangé (§9 : un pool se redistribue au retrait, soupçon conservé). `position.suspect` est
le livre de risque du marché ; il ne décroît pas quand un soupçon en attente expire (biais
prudent pour le marché). Le marché paie l'USDC **tout de suite** contre du Ghost non mûr : c'est
précisément le vecteur de contagion que la balise doit endiguer (scénario C).

Seconde limite assumée (NIT 15, README) : une destruction qui vise le marché baisse son solde
Ghost, mais `p.ghost` / `p.m` ne sont **pas** dépréciés (pas de liquidation, pas de
socialisation des pertes). Après destruction, `Σ positions` peut dépasser
`ghost.balanceOf(market)` et le dernier retrait revert (`ERC20InsufficientBalance`). C'est
pourquoi la mauvaise créance du scénario C se mesure sur le **solde réel** du marché (§8.3),
jamais sur le livre de positions.

## 6. `GhostUsdcPool` (simulé) — #65, §10

**Prix fixe** retenu (plus simple que le produit constant) : `usdcPerGhost` immuable (unités
USDC pour `1e18` Ghost). Raison : une destruction change le solde Ghost du pool ; à prix fixe il
n'y a aucune réserve de pricing à resynchroniser (pas de `sync`, pas de `k` à défendre), et le
scénario D mesure qui perd quoi, ce qui ne dépend pas de la courbe. Limite : pas de découverte de
prix (la décote « spéculative » n'est pas modélisée par le pool ; le prix du risque est porté par
la balise et le marché de prêt). Liquidité apportée par transferts directs ; pas de jetons LP.

```solidity
enum ClaimStatus { None, Open, Settled }
struct SwapClaim {
    address seller; uint256 ghostAmount; uint256 usdcAmount;
    uint256 ratioConfirmed; uint256 ratioPending; uint256 pendingTag;  // ratio vendeur au swap (1e18)
    uint64 maturity; uint64 createdAt; ClaimStatus status;
}
mapping(uint256 => SwapClaim) public claims;  // swapId à partir de 1
uint256 public totalOwed;                     // USDC promis non payés
```

Constructeur : `GhostUsdcPool(IERC20 ghostToken, IGhostRisk ghostRisk, IERC20 usdc,
uint256 usdcPerGhost)` (`ghostRisk` = le Ghost, ou `GhostLens` si le repli n°2 de §1 est appliqué,
qui implémente alors tout `IGhostRisk` ; adresses non nulles, prix > 0, sinon `ZeroAddress` /
`InvalidPrice`).

Ratios figés au swap (NIT 10, arrondi vers le haut = sens sûr pour l'annulation), avec
`(Sc, SpValide, tag) = ghostRisk.suspectComponentsOf(seller)` et `B = balanceOf(seller)` lus
avant le transfert (`B ≥ ghostAmount > 0`) :
`ratioConfirmed = Math.mulDiv(Sc, 1e18, B, Ceil)`, `ratioPending = Math.mulDiv(SpValide, 1e18,
B, Ceil)`, `pendingTag = SpValide > 0 ? tag : 0`. Au `claim`, `pendingTag == 0` compte comme
« ni confirmé ni vivant » (la part `ratioPending` vaut alors 0 dans `rConfirmed` comme dans
`rValid`).

- `sellGhost(uint256 ghostAmount) returns (uint256 swapId)` : `ghostAmount > 0` ; lit **avant**
  le transfert `ghost.suspectComponentsOf(seller)`, `balanceOf(seller)`,
  `nextOutgoingMaturity(seller, ghostAmount)`, `extendedUntil(seller)` ;
  `nextOutgoingMaturity` applique le règlement virtuel (§3.11) ;
  `usdcAmount = ghostAmount × usdcPerGhost / 1e18` (> 0 sinon `ZeroAmount`) ; exige
  `usdc.balanceOf(pool) − totalOwed ≥ usdcAmount` (`InsufficientLiquidity`) ;
  `maturity = max(nextOutgoingMaturity, extendedUntil, now)` ; `transferFrom` du Ghost (le
  Ghost garde son échéance et apporte le ratio du vendeur, §0bis-b/§9) ; `totalOwed +=
  usdcAmount`. Émet `SwapClaimCreated(swapId, seller, ghostAmount, usdcAmount, ratio, maturity)`.
  **Aucun USDC payé.**
- `buyGhost(uint256 usdcIn) returns (uint256 ghostOut)` : `ghostOut = usdcIn × 1e18 /
  usdcPerGhost` (> 0) ; solde Ghost du pool suffisant (`InsufficientLiquidity`) ;
  `transferFrom` USDC puis transfert Ghost **immédiat** (tranches les plus anciennes du pool,
  ratio du pool). Émet `GhostBought`.
- `claim(uint256 swapId)` (vendeur seulement, `NotSeller`) : `Open` (`ClaimNotOpen`),
  `now ≥ maturity` (`ClaimNotMature`), `!ghost.paused()` (`EnforcedPause`). Si
  `ghost.clearedAt(seller) ≥ createdAt` (blanchiment 2/3 du vendeur après le swap) : `r = 0`.
  Sinon deux ratios dérivés des composantes figées au swap :
  `rConfirmed = ratioConfirmed + (incident pendingTag **confirmé** ? ratioPending : 0)` et
  `rValid = rConfirmed + (incident pendingTag **vivant non confirmé** ? ratioPending : 0)`.
  - Si `ghost.destroyedAt(seller) ≥ createdAt` (destruction confirmée visant le vendeur après
    le swap) : `cancelled = min(usdcAmount, ceilDiv(usdcAmount × rConfirmed, 1e18))` — seule la
    part **confirmée** est annulée (constat 6 : comme la destruction, §3.6, ne brûle pas le Sp
    d'un autre incident vivant) ; payé `usdcAmount − cancelled`.
  - Sinon : payé intégralement seulement si `rValid == 0` ; sinon revert `ClaimSuspect(rValid)`
    — on attend l'expiration (silence), la destruction ou le blanchiment. Miroir du verrou
    partiel (§3.5) : la part suspecte vendue ne sort pas en USDC avant décision ; pour rester en
    O(1) et sans paiement partiel, c'est toute la créance qui attend (★ §9-16). Un soupçon
    confirmé jamais suivi de destruction bloque la créance comme il bloquerait la conversion.
  - `status = Settled` **avant** le transfert USDC ; `totalOwed −= usdcAmount` ; l'USDC annulé
    reste dans le pool et compense le Ghost détruit chez lui. Émet `SwapClaimSettled(swapId,
    paid, cancelled)`.
- Le `swapId` n'est qu'un lien de revert : aucun soupçon ne passe par lui ; la propagation se
  fait par le ratio côté M-Ghost. Annulation **paresseuse** au `claim` (O(1), aucune boucle sur
  les créances d'un vendeur). DEX tiers : hors périmètre, couverts seulement par leur ratio et la
  balise ; un USDC déjà payé par un tiers n'est pas récupérable (README, limites).

## 7. `ProtectedMinter` (modifié, volet 1 préservé)

- Constructeur : signature §1 ; `ghost = new GhostToken(address(this), admin, guardians_,
  ghostConfig)` ; `stable = GhostedStable(ghost.underlying())`.
- `completeSwap(requestId)` : inchangé sauf `stable.mint(depositor, minted)` →
  `ghost.issueFromMinter(depositor, minted, requestId)`. `SwapCompleted` inchangé (destinataire =
  déposant) et reste l'**événement de référence** « demande n°X → déposant → montant » pour le
  décodeur de mint dédié du monitor (§3.12). Ordre des logs dans la transaction : `Transfer`
  (Ghost, `0x0 → déposant`), `GhostIssued(MINT, requestId)`, puis `SwapCompleted`.
- `nextRequestId` part toujours de 0 (numérotation du volet 1 inchangée, §3.12, ★ §9-20).
- `requestSwap`, `setRate`, `quoteMint`, `getRequest`, rôles, pause 3/3 : inchangés.
- `VulnerableMinter` + `StableToken` : inchangés (monde sans Ghost, baseline du scénario A).

## 8. Stratégie de test

### 8.0 Base commune

`test/utils/BaseTest.sol` : ajoute `watcher = makeAddr("watcher")`, `_ghostConfig()` (fixtures,
**pas des mesures** : `window = 600`, `slot = 60` (N = 10), `maxExtensionFactor = 6`,
`quarantineBudgetBps = 2_000`, `maxConvertRatio = 0`, `maxConvertSuspect = 0`, marges 0,
`restitutionClaimDelay = 1 days`), `_deployProtected()` retourne aussi le Ghost et accorde
`WATCHER_ROLE` à `watcher` (prank admin), helpers `_mintGhost(who, usdcAmount)`,
`_warpPastWindow()`, `_destroy(incidentId, targets)` (guardian1 propose, guardian2 approuve),
`_restitute(to, amount)`, `_confirm(incidentId)`, `_clear(accounts)`, `_extend2of3(…)`. Les
tests à base de marges non nulles redéploient avec une config dédiée. Une seconde fixture
**`_ghostConfigThresholds()`** (seuils > 0 : `maxConvertRatio = 0.01e18`,
`maxConvertSuspect = 100e18`, alignés sur les défauts de `data/ghost_ledger.py` en 18 décimales
(§10bis) ; valeurs de test, pas des mesures) sert à tous les tests de
dispersion (constat 1) : avec des seuils à 0, l'évasion par fan-out serait masquée.

### 8.1 Tests unitaires (une règle → au moins un test)

| Fichier | Règles couvertes |
|---|---|
| `test/GhostedStable.t.sol` | mint réservé au Ghost ; transfert/transferFrom de M → M brûlé, Ghost frais chez le destinataire (`maturity = ceil(now+W)`) ; allowance consommée ; pause Ghost ⇒ transfert de M revert ; marge d'entrée |
| `test/ghost/GhostBuckets.t.sol` | arrondi au créneau supérieur ; rien de convertible avant W ; transfert de Ghost garde l'échéance d'origine ; plus anciennes tranches d'abord ; la poussière reçue ne retarde pas le solde existant ; anneau N+1 (bouclage sur plusieurs W) ; `balanceOf == matured + Σ tranches` ; auto-transfert et transfert nul neutres ; envoi > solde ⇒ `ERC20InsufficientBalance` (pas de panique) ; `test_nextOutgoingMaturity_virtualSettle` |
| `test/ghost/GhostSuspicion.t.sol` | ratio porté par l'expéditeur, moyenne pondérée chez le destinataire ; arrondi vers le haut ; conservation exacte ; Sc/Sp séparés ; expiration paresseuse ; confirmation bascule Sp en Sc ; dilution ne baisse pas le montant absolu |
| `test/ghost/GhostConvert.t.sol` | chacune des 5 conditions de §3.5 isolément ; verrou partiel : `amount ≤ balanceOf − S`, la part suspecte ne sort jamais, le soupçon ne bouge pas à la conversion ; gros porteur avec 1 wei suspect convertit tout sauf 1 wei (seuils > 0) ; `test_threshold_ratioRoundedUp` ; solde nul ⇒ `NotMatured(amount, 0)` ; `test_dustGriefing_thresholdsZero` mesure le blocage par 1 wei avec seuils à 0 (limite README) ; marge base + pente ; M minté = g − fee ; `reserve()` augmente de la marge ; M jamais repris après destruction |
| `test/ghost/GhostWatcher.t.sol` | seul `WATCHER_ROLE` ; ouverture / ajout à l'incident ; `duration == 0` → `InvalidDuration` ; `duration` > factor×W → `ExtensionTooLong` ; budget dépassé revert (lot entier) ; Sp ne fait que monter ; rejoindre n'allonge pas l'incident ; incident confirmé ⇒ nouvel incident ; **`test_shorterSecondIncident_doesNotShorten`** (incident 1 `expiresAt = 3600` confirmé à t=100, incident 2 de 60 s à t=200 re-marque le compte ⇒ toujours allongé jusqu'à 3600) ; **`test_chainedIncidents_cumulativeCap`** (incidents enchaînés au bloc d'expiration ⇒ `ExtensionTooLong` dès que la série dépasse factor×W ; nouvelle série acceptée après W sans extension) ; **`test_fanOut16_noSuspectConversionBeforeExpiry`** (seuils > 0, compte marqué disperse vers 16 adresses, aucune ne convertit sa part suspecte avant `expiresAt`, Σ converti ≤ Σ propre) ; `test_lateJoin_marginIsRemainingLifetime` (mesure affichée) ; `test_maxExtensionEnd_predictsRevert` (vue = borne exacte, avant et après cooldown) ; `test_frictionDutyCycle` (surveillant qui ré-allonge au plus tôt pendant 10 périodes : fraction du temps retardé affichée, ≤ factor/(factor+1)) ; champ `actor == watcher` dans `IncidentOpened` / `PerimeterDelayed` ; `extendedBalance` == somme recalculée après mint / burn / transfert / destruction ; silence ⇒ retour NORMAL ; circulation permise pendant le retard, conversion suspendue |
| `test/ghost/GhostGuardian.t.sol` | 2/3 destruction (1 approbation ne suffit pas) ; `approveAction` ≠ `approve` ERC20 ; `ActionAlreadyApproved` ; rounds indépendants de la pause 3/3 ; liste vide = confirmation ; `IncidentExpired` ; destruction = Sc exact, tranches récentes d'abord ; **`test_redestroy_keepsOtherLiveIncidentPending`** (re-destruction sous incident 1 confirmé pendant que l'incident 2 est vivant ⇒ Sp de 2 intact) ; `Extend` 2/3 : lot hors budget refusé au surveillant, accepté en 2/3, toujours borné par factor×W et la borne cumulée, expire seul, `actor == address(ghost)` dans les événements ; **`test_extendOverBudget_blocksWatcherUntilExpiry`** (incident vivant rejoint par `Extend`, `duration` ignorée, tout `delay` suivant revert `QuarantineBudgetExceeded` jusqu'à `expiresAt`, accepté après) ; `test_restitution_proposedBeforeReserve_executesLater` (§3.13) ; `Clear` 2/3 : soupçon remis à 0, `totalSuspectCleared`, extension inchangée ; restitution plafonnée (`ExceedsReserve`, proposition toujours ouverte) ; `sweepToInsurance` après délai ; pause 3/3 bloque transferts/convert/M/minter/delay/Extend/restitution, pas la destruction ni `Clear` |
| `test/ProtectedMinter.t.sol` (adapté) | I1–I3 inchangés mais vérifiés sur `ghost.balanceOf` ; I4 révisé (§1) ; Ghost frais au déposant |
| `test/RiskBeacon.t.sol` | 4 états et leur priorité ; `publish` émet les valeurs du Ghost ; aucune écriture possible |
| `test/MockLendingMarket.t.sol` | décote = f(risque lu par la balise) ; refus au-delà des seuils et hors NORMAL ; config `useBeacon=false` : aucun appel à la balise (`vm.expectCall(address(beacon), …, 0)`), `beacon == 0` accepté seulement dans ce cas ; LTV ; **`test_depositM_thenWithdraw_locked`** (dépôt de M puis retrait immédiat ⇒ `CollateralLocked` ; après `window + slot`, le Ghost retiré est convertible sans gain de temps par rapport à un transfert de M direct) ; `position.m` = delta mesuré (marge d'entrée > 0) ; soupçon importé mesuré via la balise ; **`test_mOnlyPosition_noDivisionByZero`** (dépôt de M seul ⇒ `haircutBps == base`, `borrow` dans la LTV réussit, retrait de la seule jambe M après `unlockAt` réussit, pour `useBeacon` vrai et faux) ; `ExceedsPosition` |
| `test/GhostUsdcPool.t.sol` | vente ⇒ créance sans paiement ; `ClaimNotMature` ; paiement à échéance ; annulation `rConfirmed × montant` après destruction visant le vendeur, sans la part d'un autre incident vivant ; `ClaimSuspect` pendant incident vivant puis paiement après expiration ; blanchiment 2/3 ⇒ paiement intégral ; achat immédiat ; `totalOwed` ; ratios figés arrondis vers le haut ; `pendingTag == 0` ⇒ part en attente ignorée ; tranche échue non réglée vendue ⇒ `claim.maturity == now` |
| `test/ghost/GhostEvents.t.sol` | `test_events_monitorMapping` (§3.12) : suite exacte de logs et adresse émettrice pour mint (`GhostIssued.requestId ==` id de `SwapCompleted`, id 0 compris), transfert de M, transfert de Ghost, conversion, destruction, restitution |
| `test/ghost/LedgerParity.t.sol` | `test_ledgerParity_simpleChain` (§10bis) : séquence courte sans marquage ni marge (mint 100 à t0, A→B 40 à t0 + 3 min, B→C 10 à t0 + 5 min, conversions après W) ; soldes, tranches `(échéance, montant)` et montants convertis comparés aux valeurs attendues du registre `data/ghost_ledger.py`, **recopiées en dur** dans le test avec en commentaire la suite d'appels Python qui les reproduit (aucune dépendance Python dans la CI Foundry) |
| `test/RiskBeacon.t.sol` (complément) | source de chaque champ de `Risk` (§4) : `incidentId` = `destroyedIncident` / `extensionTag` / `pendingTag` valide / 0 selon l'état |

**Suites existantes à modifier explicitement** (constat 14 ; aucune autre ne change) :

| Fichier | Modification |
|---|---|
| `test/utils/BaseTest.sol` | `_deployProtected()` → `returns (ProtectedMinter pm, GhostedStable token, GhostToken ghost)` (constructeur à 6 arguments, `_ghostConfig()`), `WATCHER_ROLE` accordé à `watcher` ; `_deployVulnerable()` inchangé |
| `test/GuardianPausable.t.sol` | l. 122 et 125 : `new ProtectedMinter(…, guardians, _ghostConfig())` ; type `StableToken` → `GhostedStable` ; déstructuration du nouveau `_deployProtected` |
| `test/ProtectedMinter.t.sol` | l. 149 : sélecteur `StableToken.NotMinter` → `GhostedStable.NotMinter` ; l. 211–222 : constructeur à 6 arguments ; type `StableToken` → `GhostedStable` ; assertions de solde du déposant sur `ghost.balanceOf` |
| `test/StolenServiceKey.fuzz.t.sol` | l. 76 : `GhostedStable.NotMinter` ; ajout d'un fuzz `ghost.issueFromMinter` par l'attaquant → `NotMinter` ; type `StableToken` → `GhostedStable` |
| `test/ScenarioA.t.sol` | `pStable` typé `GhostedStable` ; mesures côté protégé lues en `supplyValue()` / `ghost.balanceOf` ; côté vulnérable inchangé |
| `test/invariant/ProtectedMinter.invariant.t.sol` | type `GhostedStable` ; `stable.totalSupply` → `ghost.supplyValue()` ; soldes → `ghost.balanceOf` |
| `test/invariant/ProtectedMinterHandler.sol` | `stolenKeyMintDirect` tente **aussi** `ghost.issueFromMinter` et `M.mint` (I4 révisé) ; ces tentatives sont classées « doit échouer » |

`Tokens.t.sol` et `VulnerableMinter.t.sol` ne bougent pas (`StableToken` reste le token du monde
sans protection).

### 8.2 Invariants (`test/invariant/`)

`GhostHandler.sol` + `Ghost.invariant.t.sol` : 5 acteurs, 1 surveillant, 3 guardians honnêtes
(H2), clé de service volée (volet 1). Actions : `requestAndComplete`, `transferGhost`,
`transferM`, `convert`, `convertSuspectPart` (tente de convertir au-delà de `balanceOf − S` :
doit échouer), `warp(dt ∈ [0, 2W])`, `watcherDelay`, `watcherChainIncident` (ouvre un incident
au bloc d'expiration du précédent et re-marque les mêmes comptes), `watcherForbidden` (tente
destroy/pause/approveAction/confirm/clear/delay trop long/hors budget/au-delà de la borne
cumulée), `guardianDestroy`, `guardianExtend`, `guardianClear`, `guardianRestitute`, `sweep`,
`guardianPause`. Le handler tourne deux fois : avec `_ghostConfig()` et avec
`_ghostConfigThresholds()` (deux contrats d'invariants). Les valeurs attendues sont **recalculées par le handler** (modèle
d'ombre des tranches et du soupçon), jamais lues du contrat testé.

**Règle de vivacité** : chaque action est classée. *Doit réussir* (préconditions calculées par
le handler) → `try/catch` ; un revert positionne `ghost_unexpectedRevert = true`. *Doit
échouer* → un succès positionne `ghost_unexpectedSuccess = true`. *Peut échouer* (uniquement les
approbations de pause, comme aujourd'hui) → compteur ok/ko. `invariant_liveness` exige les deux
drapeaux à `false`, et `invariant_callSummary` affiche les compteurs ok pour prouver que les
chemins utiles sont réellement explorés. `fail_on_revert = false` reste tel quel.

| Suite | Invariant |
|---|---|
| (a) | `Σ_{entrées à t ≤ now − W} montant ≥ totalConverti + Σ_a convertibleOf(a)` (entrées = mint, transfert de M, restitution, suivies avec leur horodatage par le handler) |
| (b) | par acteur, tranches du contrat == modèle d'ombre (échéances arrondies, plus anciennes d'abord) ; à chaque transfert, sur la part **temporelle** (`maturedEffectiveOf`, indépendante du soupçon) : celle de `to` ne baisse pas, celle de `from` baisse d'au plus `v` ; et `balanceOf(to) − S(to)` ne baisse pas (la poussière suspecte ne verrouille que la poussière) |
| (c) | `Σ_a (Sc + Sp) == totalSeeded − totalSuspectBurned − totalSuspectExpired − totalSuspectCleared` ; `Sc + Sp ≤ balanceOf` pour tout acteur ; **aucune conversion réussie n'a laissé `balanceOf < S_valide`** (verrou partiel) ; plus `testFuzz_suspicionConserved_chainAndFanOut(depth ≤ 32, fanOut ≤ 16, splits)` : sans destruction, blanchiment ni expiration, `Σ effectiveSuspectOf == montant semé` exactement, conversions comprises |
| (d) | pour chaque destruction exécutée : `burned == Sc après normalisation` (ratio confirmé × non converti), Sp d'un autre incident vivant inchangé, solde baissé d'exactement `burned`, soupçon confirmé après = 0, soldes M inchangés |
| (e) | `supplyValue ≤ totalIssued == minter.totalMinted() ≤ Σ dépôts × taux` ; `reserve() == totalIssued − supplyValue − insuranceFund ≥ 0` (sans saturation) ; `Σ restitué ≤ Σ brûlé + Σ marges` ; toute restitution > réserve a échoué |
| (f) | aucune action interdite du surveillant n'a réussi (drapeau `ghost_unexpectedSuccess`) ; `_extendedUntil[a]` **ne baisse jamais**, quel que soit l'incident ; pour tout compte, toute série d'extensions contiguës vérifie `fin − début ≤ maxExtensionFactor × W` et deux séries sont séparées d'au moins W (le handler garde début/fin par compte) ; Sp ne baisse jamais du fait du surveillant ; après `expiresAt` sans confirmation, Sp valide = 0 et, après `_extendedUntil`, `extendedUntil(a) == 0` ; `incidents[open].extendedBalance == Σ balanceOf(a)` des comptes d'`extensionTag == open`, **recalculée par le handler** (modèle d'ombre, pas le compteur) ; juste après chaque `delay` réussi, cette somme recalculée × 1e4 ≤ budget × supplyValue |
| (g) | `ProtectedMinter.invariant.t.sol` adapté : mêmes 7 invariants, `stable.totalSupply` → `supplyValue` et soldes → `ghost.balanceOf` (le handler volet 1 ne transfère pas) |

### 8.3 Scénarios mesurés (chiffres affichés, jamais assertés en dur)

- **`test/ScenarioC.t.sol`** — deux marchés identiques sauf `useBeacon` (`true` / `false`),
  mêmes fixtures (`ltvBps`, décotes), même liquidité USDC. **La mesure vient de la vérité côté
  Ghost, jamais du livre `Position.suspect`** (constat 1 : ce livre vaut 0 par construction dans
  le marché sans balise, ce qui rendait la comparaison vide). Dans `setUp`, l'attaquant est le
  **seul déposant** de chaque marché (assert explicite : `ghost.balanceOf(market)` avant dépôt
  == 0) ; le prix fixe du marché est 1 Ghost = 1 USDC (`1e18 → 1e6`).
  Mesure, identique pour les deux marchés et indépendante de `cfg` :
  ```solidity
  uint256 sBefore = ghost.effectiveSuspectOf(address(market));
  _depositAsAttacker(market, ghostAmt);                  // Ghost volé, partiellement suspect
  uint256 suspectIn = ghost.effectiveSuspectOf(address(market)) - sBefore; // mesuré par le test
  uint256 debt = _borrowMaxAsAttacker(market);           // 0 si refusé (try/catch : RiskTooHigh attendu avec balise)
  // ... destruction 2/3 visant [attaquant, marketWith, marketWithout] ...
  uint256 beforeBal = ghost.balanceOf(address(market));  // lu juste avant _destroy
  _destroy(incidentId, targets);
  uint256 burnedAtMarket = beforeBal - ghost.balanceOf(address(market));
  uint256 recoverableUsdc = ghost.balanceOf(address(market)) / 1e12; // plancher 0, prix fixe
  uint256 badDebt = debt > recoverableUsdc ? debt - recoverableUsdc : 0;
  console.log("bad debt (USDC units)", badDebt);
  ```
  La valeur récupérable ne dépend **pas** de la décote : la décote sert à prêter moins, pas à
  mesurer la perte. Assertions : `badDebtWith ≤ badDebtWithout` (qualitatif) ;
  `burnedAtMarket == suspectIn` à 1 wei par transfert près, **pour les deux marchés** ;
  `p.suspect == suspectIn` seulement pour `useBeacon = true` (et `p.suspect == 0` sinon) ; le
  refus d'emprunt avec balise est vérifié (`RiskTooHigh`) et non avalé. Aucun chiffre cible.
  Variante 1 : surveillant marque l'attaquant (`delay` avec montant suspect) **avant** dépôt et
  emprunt ; le soupçon entre chez le marché avec le dépôt (ratio de l'expéditeur, §9).
  Variante 2 : emprunt **avant** détection → les deux marchés prêtent pareil ; le surveillant
  marque ensuite `[attaquant, marketWith, marketWithout]` en semant chez chaque marché le
  montant suspect déposé (le soupçon est déjà parti avec le Ghost : marquer l'attaquant seul ne
  semerait rien, son solde est vide) ; mesures affichées telles quelles (limite honnête : la
  balise n'aide qu'avant l'emprunt). Le registre hors chaîne (`data/scenarios_cd.py`) mesure
  avec « un coffre par prêt » : écart listé en §10bis. Les montants sont dimensionnés pour que
  chaque `delay` respecte le budget de quarantaine des fixtures (offre légitime de fond mintée
  dans `setUp`), sinon le test passerait par `Extend` 2/3.
- **`test/ScenarioRecovery.t.sol`** — mesure de l'affirmation n°2 de la décision #37
  (« annulable tant que non converti, y compris après fragmentation » ; méthode : rejeu d'une
  chaîne et mesure de la part récupérée, constat 2). Config `_ghostConfigThresholds()`.
  ```solidity
  /// Chaîne de profondeur `depth` puis fan-out `fanOut` depuis un compte marqué (Ghost
  /// partiellement volé), dilution par du Ghost propre chez certains détenteurs, conversions
  /// "propres" tentées après W (avant expiresAt), confirmation 2/3, puis destructions par lots
  /// de MAX_BATCH sur tous les détenteurs.
  function testFuzz_recovery_chainAndFanOut(uint8 depth, uint8 fanOut, uint256 seed) public {
      depth = uint8(bound(depth, 1, 32)); fanOut = uint8(bound(fanOut, 1, 16));
      // ... semis S via delay, transferts (montants dérivés de seed), conversions tentées ...
      // ... _confirm(id) avant expiresAt, puis _destroy(id, lot) pour chaque lot de 64 ...
      assertEq(ghost.totalSuspectBurned(), S);  // conservation exacte + verrou partiel : rien de suspect converti
      console.log("recovered / seeded (1e18)", ghost.totalSuspectBurned() * 1e18 / S);
      console.log("clean Ghost converted by holders", cleanConverted);
  }
  ```
  `test_recovery_partialDetection` : même chaîne, un tiers des détenteurs n'est **pas** ciblé ;
  part récupérée affichée, jamais assertée en dur (règle `docs/CLAIMS.md`) ; le soupçon confirmé
  restant chez les non-ciblés est affiché (il reste verrouillé, §3.5).
  `test_recovery_confirmationTooLate` : la confirmation arrive après `expiresAt` ⇒
  `IncidentExpired`, part récupérée 0 (limite affichée : silence = retour à la normale, §3).
- **`test/ScenarioD.t.sol`** — fixture de prix `usdcPerGhost = 900_000` (0,9 USDC par Ghost),
  alignée sur `ContagionParams.ghost_price = 0.9` de `data/scenarios_cd.py` pour faciliter la
  comparaison (fixture, pas une mesure). L'attaquant détient du Ghost volé à une victime, est marqué,
  vend au pool (créance), des spéculateurs achètent du Ghost au pool, destruction 2/3 visant
  [attaquant, pool, spéculateurs], réclamation de la créance, restitution 2/3 à la victime.
  Mesures `console.log` : perte protocole (`max(0, supplyValue − totalIssued)`, attendue 0),
  Δ valeur pool (`usdc − owed + ghost × prix`), Δ spéculateurs, USDC effectivement reçu par
  l'attaquant, réserve avant/après restitution. Assertions : solvabilité, `cancelled == ceil(rConfirmed ×
  usdc)`, l'attaquant ne convertit jamais sa part suspecte (verrou partiel), cohérence des
  sommes ; aucun chiffre cible inventé. Variante D2 avec `_ghostConfigThresholds()` : l'attaquant
  disperse avant de vendre ; mêmes mesures.

### 8.4 Gas (mesure exigée, pas d'estimation)

`test/gas/GhostGas.t.sol` : pire cas d'un transfert de Ghost (expéditeur et destinataire avec
N + 1 tranches non vides toutes différentes, premier remplissage de slots), cas courant
(1 tranche), transfert de M (hook), `convert`, `delay` à 1 et 64 comptes, destruction à 64
cibles. Mesure par `gasleft()` + `forge snapshot` ; résultats recopiés dans le README avec la
config (N = 10). Le transfert mesuré inclut la mise à jour de `extendedBalance` (expéditeur et
destinataire comptés dans l'incident courant) et la propagation de soupçon ; `forge build
--sizes` est recopié à côté (§1). Si le pire cas est jugé trop cher, seul N change (§0bis-b), pas l'algorithme.

## 9. Choix d'implémentation à valider

Options les plus simples compatibles avec les décisions ; aucune n'est une décision d'équipe.
Celles marquées ★ méritent une entrée dans `docs/OPEN_QUESTIONS.md` (proposée en PR, §10).

1. ★ **Incidents à invalidation paresseuse** (§3.4) : un seul incident **non confirmé** vivant
   à la fois ; les surveillants le rejoignent ; son échéance est fixée à l'ouverture. Soupçon en
   deux composantes (Sc confirmé, Sp en attente étiqueté). Suggéré par la consigne ; à valider.
   Conséquence : un compte détecté tard n'est retenu que jusqu'à `expiresAt` (documenté et
   mesuré, pas de bascule d'incident ; parade = confirmation 2/3 avant expiration).
2. ★ **Confirmation = destruction 2/3** (liste vide = confirmation seule), possible seulement
   tant que l'incident est vivant. Un soupçon confirmé n'est retiré que par destruction ou par
   **blanchiment 2/3** (`Clear`, §3.6bis : « audit blanchissant → ratios remis à 0 », §9). Le
   blanchiment ne lève pas l'extension d'adresse (elle expire seule).
3. ★ **Seuils de conversion inclusifs** (`≤`) ; fixtures à 0 pour la plupart des tests et une
   fixture à seuils > 0 pour les tests de dispersion. Valeurs à mesurer ; README : seuils > 0
   obligatoires hors tests (sinon 1 wei suspect bloque un tiers).
3bis. ★ **Verrou partiel du lignage** (§3.5, option B de la revue) : la part suspecte valide ne
   se convertit jamais et la conversion ne déplace aucun soupçon ; l'adresse **marquée** est en
   plus entièrement bloquée pendant son extension. Écarté : blocage total de tout porteur de
   Sp (option A, tache d'huile) et propagation de l'extension d'adresse le long du lignage
   (même effet, et hors budget).
3ter. ★ **Borne cumulée par compte** (§3.4) : une série d'extensions contiguës d'un compte ≤
   `maxExtensionFactor × W`, cooldown = W sans extension entre deux séries. Valeur du cooldown à
   mesurer ; s'applique aussi à `Extend` 2/3. Énoncé honnête : la borne est un **taux**, pas une
   durée totale — un surveillant compromis peut retarder un compte `factor / (factor + 1)` du
   temps (6/7 avec les fixtures), indéfiniment, jusqu'à révocation de son rôle (H1). Mesuré par
   `test_frictionDutyCycle`. Vue `maxExtensionEnd(a)` pour que le surveillant évite les reverts.
4. **Paramètres immuables** (redéploiement pour changer une valeur), aucun setter admin.
5. **Marges** : formule `base + pente × ratio` en bps, marge d'entrée M → Ghost forfaitaire
   (le M est propre), montant prélevé = valeur non émise, versée à la réserve puis au fonds
   d'assurance ; marge nulle sur l'émission par le minter (I1, ε = 0).
6. **Semis** : `Sp = max(Sp, montant)` plafonné au solde (idempotent, ne fait que monter) plutôt
   qu'additif.
7. ★ **Budget de quarantaine** compté sur l'incident **courant** seulement (`extendedBalance`
   maintenu dans toutes les branches de `_update`) ; les comptes encore allongés par un incident
   antérieur **confirmé** ne comptent plus (déjà validés par des humains) ; des entrées
   ultérieures vers un compte allongé peuvent dépasser le budget sans action du surveillant
   (seule l'action du surveillant est bornée, vérifiée à la fin de `delay`). Au-delà du budget :
   revert pour le surveillant ; **extension = humain requis** via `Extend` 2/3 (§3.6bis), sans
   budget mais avec les mêmes bornes de durée.
8. **Ordre de destruction dans les tranches** : les plus récentes d'abord (préserve la part
   convertible du porteur de bonne foi).
9. **Restitution en Ghost frais** (fenêtre W appliquée à la victime aussi), bloquée pendant la
   pause ; **bascule au fonds d'assurance** de toute la réserve après `restitutionClaimDelay`
   sans nouvelle entrée, permissionless ; fonds = compteur comptable.
10. **`totalIssued` = collatéral de référence** (au taux figé, H1) ; les demandes en attente ne
    comptent pas dans la réserve.
11. **Pause** : pause Ghost (3/3) = pause globale du token ; pause du minter distincte et
    inchangée ; destruction autorisée en pause.
12. **Déploiement en cascade** (`ProtectedMinter` → `GhostToken` → `GhostedStable`), repli par
    adresse prédite si l'initcode dépasse EIP-3860.
13. **Transfert de M = burn M + mint Ghost** : `Transfer(from, 0, v)` côté M, jamais
    `Transfer(from, to)` ; les outils qui attendent un solde M chez le destinataire verront du
    Ghost.
14. **Balise sans état** : écritures uniquement dans le Ghost ; état DETRUIT tant que
    `now < max(expiresAt de l'incident détruit, destroyedAt + W)`, puis NORMAL.
15. ★ **Marché de prêt** : accepte le Ghost non mûr à la face (décote = f(risque lu par la
    balise) seulement, pas de décote d'échéance) ; livre de risque `position.suspect` mesuré par
    delta de la balise, qui ne décroît pas à l'expiration ; verrou unique de position
    `window + slot` posé par tout dépôt et exigé par tout retrait ; M déposé détenu en Ghost,
    compté au delta mesuré ; config `useBeacon = false` sans aucune lecture de risque.
16. **Pool à prix fixe** ; échéance de la créance = `max(échéance du Ghost vendu, fin de
    retard du vendeur, now)` ; ★ créance payable seulement si le ratio valide figé au swap est
    nul (sinon attente de l'expiration, de la destruction ou du blanchiment ; pas de paiement
    partiel) ; annulation paresseuse de la seule part **confirmée** si
    `destroyedAt(vendeur) ≥ createdAt`.
17. `MAX_BATCH = 64` pour `delay`, `proposeDestroy`, `proposeExtend`, `proposeClear`, `publish`
    (borne de gas, à ajuster selon §8.4).
18. **Replis de taille** dans l'ordre fixé en §1 (librairie externe, puis `GhostLens`, puis
    déploiement séparé du Ghost), sans toucher `foundry.toml`.
19. **Pause et horloges** : incidents et extensions expirent pendant la pause (temps réel,
    §3) ; parade = confirmation ou destruction pendant la pause.
20. ★ **Id de demande 0 conservé** (§3.12, §7) : `nextRequestId` part toujours de 0 (volet 1
    inchangé) ; `GhostIssued` porte `requestId` (significatif si `kind == MINT`) et
    `SwapCompleted` reste l'événement de référence. La collision avec la sentinelle provisoire
    `UNKNOWN_REQUEST_ID = 0` du listener est traitée côté `monitor/` (retrait de la sentinelle au
    passage au décodeur dédié), proposée en PR. Alternative écartée : décaler les ids à 1
    (modifie le volet 1 mergé et ses tests pour un besoin propre au monitor).
21. **Pas de levée de retard** : aucune fonction ne lève ni ne raccourcit une extension, même en
    2/3 et même après destruction (`OPEN_ANSWERS.md` §3 : « aucun acteur seul ne peut accélérer,
    libérer ou raccourcir », « silence = retour automatique »). Conséquence : un compte détruit
    garde son extension jusqu'à `_extendedUntil` avant de convertir son reste propre. Diverge du
    `lift_delay` de `data/ghost_ledger.py` (§10bis).
22. **Validation en deux temps** des actions 2/3 (§3.13) : contrôles sans état à la
    proposition, tout (état compris) à l'exécution.
23. **Fixtures de scénarios** alignées sur `data/scenarios_cd.py` quand c'est gratuit (prix du
    pool 0,9 USDC) ; ce sont des fixtures, pas des mesures.

## 10. Propositions hors `contracts/` (description de PR uniquement, aucun fichier modifié)

- **`docs/CONTRACTS.md` / `shared/`** (propriétaire `shared/`) : `GhostTokenMintEvent` —
  `window_expires_at` = `maturity` arrondie au créneau, ajouter `kind`
  (`mint`/`transfer_m`/`restitution`/`ghost_transfer`) ; ratios on-chain en entier 1e18 →
  `float` ; `GhostTokenBurnEvent.decision_id` = `proposalId` en chaîne ; `TransferEvent.is_ghost`
  : reformuler « Ghost d'un Ghost » (n'existe pas, §0bis-b) en « transfert de M-Ghost » ;
  `RiskBeaconUpdate.risk_level` : correspondance NORMAL→`normal` (ou `elevated` si ratio > 0),
  RETARDE→`elevated`, DETRUIT / PAUSE_GLOBALE→`frozen` ; nouveau modèle `SwapClaim` (pool).
- **Monitor / detection** (#9, #10, #11 ; propriétaire `monitor/`) : I5 change de sens — un
  transfert de M est un burn de M + un mint de Ghost ; `valeur(supply)` = M + Ghost ; lire
  `GhostIssued` / `GhostDestroyed` / `GhostConverted` / `PerimeterDelayed`. Recopier dans la PR
  la table « Lecture monitor par adresse » de §3.12 : ne pas brancher le décodeur ERC-20
  générique sur M comme détecteur de mint (chaque `Transfer(0x0, a)` sur M est une
  conversion) ; mint lu sur `SwapCompleted` (adresse du minter) ou `GhostIssued(kind = MINT)` ;
  `token_is_ghost = true` pour M-Ghost seulement ; transferts de M reconstruits depuis
  `GhostIssued(TRANSFER_M).source → recipient` ; retirer la sentinelle `UNKNOWN_REQUEST_ID = 0`
  au passage au décodeur dédié (l'id de demande 0 existe, ★ §9-20).
- **`data/`** (#25, propriétaire `data/`) : recopier la table de §10bis dans la PR et notifier le
  propriétaire ; aucun fichier `data/` modifié.
- **`docs/CLAIMS.md`** : colonnes « limites » — Ghost converti hors d'atteinte ; marché de prêt
  qui paie contre du Ghost non mûr ; DEX tiers ; budget de quarantaine borné par action du
  surveillant seulement ; gas mesuré par transfert.
- **`docs/OPEN_QUESTIONS.md`** : les points ★ de §9. Règle d'équipe : les décisions ambiguës
  vont dans `OPEN_QUESTIONS.md`, mais `docs/` n'est pas dans le périmètre de cette tâche. Qui les
  reporte : l'auteur de la PR les liste dans la description sous « Questions à reporter dans
  `docs/OPEN_QUESTIONS.md` » et **demande au propriétaire de `docs/`** (à nommer dans la PR ; par
  défaut l'auteur de la décision concernée dans `OPEN_ANSWERS.md` : Marceau pour §0bis / §9,
  denybs pour §0bis-b/c / §10, Équipe 20 pour §3) de les y inscrire. Rien n'est copié dans
  `OPEN_ANSWERS.md` tant que l'équipe n'a pas tranché.
- **`docs/CLAIMS.md`** (ajouts) : verrou partiel (la part suspecte ne se convertit jamais),
  marge d'un compte détecté tard = reste de vie de l'incident, griefing 1 wei avec seuils à 0,
  borne cumulée par compte énoncée en **taux** (un surveillant compromis peut retarder un compte
  `factor / (factor + 1)` du temps, 6/7 avec les fixtures : « friction bornée en taux », pas
  « durée bornée ») ; mesure de l'affirmation n°2 (#37) = part récupérée affichée par
  `ScenarioRecovery.t.sol` ; scénario C mesuré sur le solde réel du marché.
- **`docs/ROADMAP.md`** : cocher #8, #7, #65 après merge (seul fichier `docs/` touché, par la
  règle de suivi).

## 10bis. Écarts avec `data/ghost_ledger.py` (registre hors chaîne, #25)

`data/ghost_ledger.py` et `data/scenarios_cd.py` (sur `origin/main`, PR #82, propriétaire
`data/`) se présentent comme « point de comparaison aux tests du contrat (#8) », la vérité
restant on-chain. Le contrat ne se cale pas sur le registre : chaque écart est listé ici, recopié
dans la description de PR, et le propriétaire de `data/` est notifié. **Aucun fichier `data/`
n'est modifié.** Colonne « qui aligne » : `data/` sauf mention contraire.

Points communs vérifiés (aucun écart) : échéance `ceil((t + W) / slot) × slot` sur l'époque
Unix ; tranches les plus anciennes envoyées d'abord en gardant leur échéance ; seules les
tranches échues se convertissent ; transfert de M = Ghost frais chez le destinataire, ratio 0 ;
soupçon stocké en montant absolu, ratio dérivé ; semis `min(solde, max(soupçon, montant))` ;
retard jamais raccourci par un nouveau `delay` ; fenêtre 10 min / créneau 1 min (= fixtures
`600` / `60`).

| Point | `data/ghost_ledger.py` / `scenarios_cd.py` | Design (contrat) | Effet si non aligné | Qui aligne |
|---|---|---|---|---|
| Conversion | `convert(address)` : **toutes** les tranches échues ; si seuils respectés, le soupçon sort avec (`converted_suspect += ratio × matured`) | `convert(amount)`, verrou partiel `amount ≤ min(matured, balanceOf − S)` ; le soupçon ne sort **jamais** | C/D hors chaîne surestiment ce que l'attaquant convertit ; l'invariant (c) du contrat contredit le registre | `data/`, sauf si l'équipe rejette ★ 3bis |
| Modèle de soupçon | un `float` permanent par adresse | `Sc` (confirmé) + `Sp` (en attente, expire avec l'incident) ; `Clear` 2/3 | « silence = retour à 0 » absent du registre | `data/` |
| Retard | `delay(address, until)` libre ; `lift_delay` (levée multisig ou après destruction) | incident unique à `expiresAt` figé, borne `factor × W`, borne cumulée, budget ; **aucune levée** (★ §9-21) | le registre modélise une action que le contrat interdit | `data/` (le design suit §3 : « aucun acteur seul ne peut accélérer, libérer ou raccourcir », « silence = retour automatique ») |
| Destruction | `burn_suspect` : `ceil(soupçon)` au prorata des tranches, reliquat d'arrondi sur les plus récentes | `Sc` seul (pas un `Sp` d'un autre incident vivant), tranches les plus récentes d'abord (§9-8) | même montant brûlé (à 1 wei près) mais tranches restantes différentes, donc échéances résiduelles différentes | `data/`, sauf si l'équipe préfère le prorata (§9-8 à valider) |
| Transfert du soupçon | `ratio × amount` en `float`, `max(0, …)` chez l'expéditeur | `ceilDiv` entier, conservation exacte | écarts d'arrondi : tolérance 1 wei par transfert dans toute comparaison | — (tolérance documentée) |
| Mint non adossé | `mint(…, backed=False)`, `deficit > 0` possible | impossible on-chain (volet 1, I1–I4) ; `reserve()` ≥ 0 vérifiée par (e) | le `deficit` du registre n'a pas d'équivalent on-chain hors hypothèse H1 tombée | — (le registre modélise le monde sans volet 1) |
| Soldes de genèse | `credit_real` (vrai token sans passer par le Ghost) | M n'existe que par conversion | en test, la genèse passe par mint → `warp(W)` → `convert` | — |
| Marges | aucune | `entryFeeBps`, `convertFeeBaseBps/SlopeBps` (0 dans les fixtures) | comparer avec les marges à 0 | — |
| Unités des seuils | `suspect_threshold = 100 × 10**6` (6 déc.), `ratio_threshold = 0.01` | 18 déc., ratio 1e18 ; `_ghostConfigThresholds()` = `0.01e18` / `100e18` (alignés, fixtures) | seuils incomparables sans conversion d'unités | `data/` (documenter l'unité) |
| Marché (C) | « un coffre par prêt » (ratio par position) | une seule adresse de marché, ratio mélangé, livre `Position.suspect` ; mesure sur le solde réel (§8.3) | contagion entre déposants absente du registre ; comparable seulement avec un déposant unique (ce que fait `ScenarioC.t.sol`) | — (limite écrite des deux côtés) |
| Pool (D) | `ghost_price = 0.9` | prix fixe `usdcPerGhost` ; fixture `900_000` (alignée) | — | — |
| Restitution, fonds d'assurance, pause 3/3, budget, `Clear` | absents | présents | non comparables | `data/` si les scénarios en ont besoin |
| Monde sans Ghost | `window = 0` désactive le Ghost | baseline = `VulnerableMinter` + `StableToken` (scénario A) | — | — |

Test de parité (facultatif dans la revue, retenu car peu coûteux) :
`test/ghost/LedgerParity.t.sol::test_ledgerParity_simpleChain` (§8.1), limité au sous-ensemble
commun ci-dessus (pas de marquage, marges à 0) ; les valeurs attendues sont recopiées en dur avec
la suite d'appels Python qui les produit, pour que le propriétaire de `data/` puisse les
régénérer.

## 11. Hypothèses et README

Hypothèses mises à jour : H1 (admin / `RATE_ADMIN_ROLE` / attribution de `WATCHER_ROLE` non
compromis), H2 (guardians : au plus 1 compromis pour le 2/3, 0 pour le 3/3), H3, H4 inchangées,
**H5 remplacée** : burns limités à conversion, transfert de M, destruction 2/3, marges. Le
README gagne : sections Ghost / balise / marché / pool, tableau des chemins d'émission (§1),
invariants (a)–(g), gas et tailles mesurés (§8.4, §1), et une section **Limites** :
`maxConvertSuspect` > 0 obligatoire hors tests (griefing 1 wei, §3.3) ; marge d'un compte
rejoint tard = reste de vie de l'incident (§3.4) ; horloges qui tournent pendant la pause
(§3.8) ; budget borné par l'action du surveillant seulement (§9-7) ; marché qui paie contre du
Ghost non mûr (§5) ; DEX tiers et USDC déjà payé par un tiers non récupérables (§6) ; bascule
au fonds d'assurance jamais atteinte sous trafic continu si marges > 0 (§3.7). Toujours
« vérifié par tests d'invariants », jamais « prouvé ».

## 12. Hors périmètre

DEX tiers ; liquidation et intérêts du marché ; jetons LP ; emploi du fonds d'assurance ;
oracle de prix ; rotation des guardians et révocation d'approbations ; upgradabilité ;
déploiement Fuji (adresses dans `DEPLOYMENTS.md` plus tard) ; modules Python.

## 13. Suivi GitHub

À faire à l'implémentation (pas dans cette étape de design) : s'assigner #8, #7, #65
(`gh issue edit <N> --add-assignee "@me"`) ; branche `feat/8-token-ghost` ; une PR dont la
description contient `Closes #8`, `Closes #7`, `Closes #65` et mentionne #33 (tests d'invariants
transférés à #8) ; cocher les lignes correspondantes de `docs/ROADMAP.md` au merge. Les points ★
et les propositions de §10 figurent dans la description de PR.

## 14. Réponses à la revue (itération 1)

| # | Sév. | Réponse | Où |
|---|---|---|---|
| 1 | HIGH | **Traité, option B** : verrou partiel `amount ≤ balanceOf − S_valide`, la conversion ne déplace aucun soupçon ; l'adresse marquée reste en plus bloquée entièrement. Option A écartée (tache d'huile, contraire à « la poussière ne retarde que la poussière »). Tests fan-out ×16 avec seuils > 0 + propriété dans (c). ★ 3bis | §3.3, §3.5, §8.1, §8.2 |
| 2 | HIGH | **Traité** : borne cumulée par compte (`extensionRunStart`, cooldown W), s'applique au surveillant et à `Extend` 2/3 ; propriété ajoutée à (f) + action `watcherChainIncident`. ★ 3ter | §3.4, §8.2 |
| 3 | HIGH | **Traité** : `_extendedUntil[a]` stocké et seulement relevé ; `extensionTag` ne sert plus qu'au budget ; test du scénario incident confirmé puis incident court ; monotonie dans (f) | §3.4, §8.1, §8.2 |
| 4 | HIGH | **Traité** : `unlockAt` unique posé par tout dépôt, exigé par tout retrait ; test dépôt M → retrait immédiat | §5, §8.1 |
| 5 | MEDIUM | **Traité** : définition unique, mise à jour dans toutes les branches de `_update` ; (f) compare au modèle d'ombre du handler | §3.4, §3.9, §8.2 |
| 6 | MEDIUM | **Traité** : la destruction ne brûle que Sc après normalisation ; le pool n'annule que `rConfirmed` ; test re-destruction avec second incident vivant | §3.6, §6, §8.1 |
| 7 | MEDIUM | **Traité** : `ActionKind.Extend` 2/3 sans budget, mêmes bornes de durée, auto-expirant | §3.6bis, §3.10 |
| 8 | MEDIUM | **Traité par documentation + mesure** (option 1) : pas de bascule d'incident (casserait la fusion O(1) des `pendingTag`) ; parade humaine = confirmation avant expiration ; test de mesure ; README. ★ 1 | §3.4, §9-1, §11 |
| 9 | MEDIUM | **Traité** : soupçon importé mesuré par delta de `beacon.riskOf(market)` seulement si `useBeacon` ; aucun appel sinon (`vm.expectCall` 0) ; `beacon == 0` permis seulement sans balise ; type `IERC20` suffisant | §5, §8.1 |
| 10 | MEDIUM | **Traité** : ordre de repli fixé (librairie externe → `GhostLens` → déploiement séparé), `foundry.toml` intact | §1, Fichiers |
| 11 | NIT | Traité : `approveAction(uint256)` | §3.10 |
| 12 | NIT | Traité : `ActionAlreadyApproved(address, uint256)` | §3.10, §3.13 |
| 13 | NIT | Traité : `IGhostToken.sol` ajouté ; consommateurs typés `IERC20` + `IGhostRisk` | Fichiers, §6 |
| 14 | NIT | Traité : table des suites existantes à modifier, lignes citées vérifiées par recherche | §8.1 |
| 15 | NIT | Traité : limite README + `test_dustGriefing_thresholdsZero` | §3.3, §8.1, §11 |
| 16 | NIT | Traité : `DETRUIT` tant que `now < max(expiresAt, destroyedAt + W)` | §4, §9-14 |
| 17 | NIT | Traité : `InvalidDuration()` pour 0 | §3.4 |
| 18 | NIT | Traité : `position.m` = delta mesuré | §5 |
| 19 | NIT | Traité : `SafeCast.toUint192` | §3.2 |
| 20 | NIT | Traité : conséquence écrite | §3.7, §9-9 |
| 21 | NIT | Traité : README + parade (confirmation/destruction en pause) | §3.8, §9-19 |
| 22 | NIT | Traité : issues #8, #7, #65, #33 lues (corps + commentaires) ; apport nouveau = blanchiment 2/3 (`Clear`, §9 « réversible ») ; qui reporte les ★ dans `OPEN_QUESTIONS.md` précisé | §0, §3.6bis, §10 |

Hors revue, ajouté après lecture des issues : action `Clear` 2/3 (§9 « audit blanchissant »,
#33), corrigeant l'itération 1 qui l'excluait (ancien ★ 2).

