# monitor

- **Rôle** : écoute on-chain des événements de **mint** ET de **transfert** sur Avalanche Fuji.
- **Propriétaire** : @Yannis1307 (voir `docs/TEAM.md`).
- **Lancer** : `python -m monitor` ; tests : `python -m pytest monitor/`.

## Écoute des mints (#9)

Écouteur ERC-20 **générique** (aucun contrat déployé à ce jour, voir `contracts/DEPLOYMENTS.md`) :
un mint = `Transfer(from = 0x0, to, value)` émis par le contrat token configuré, lu par polling
`eth_getLogs` sur des plages de blocs, converti en `shared.models.MintEvent`.

- **Config** : un seul endroit, `monitor/config.py`. Variables : `FUJI_RPC_URL`,
  `MONITOR_TOKEN_ADDRESS` (voir `.env.example`), et en option `MONITOR_POLL_INTERVAL_SECONDS`,
  `MONITOR_BLOCK_BATCH_SIZE`, `MONITOR_CONFIRMATIONS`, `MONITOR_START_BLOCK`. Leurs défauts sont
  **provisoires** (à valider par l'équipe / à mesurer).
- **Sans token ni RPC**, `python -m monitor` affiche un message et s'arrête.
- **Gap résolu (#79)** : un `Transfer` ERC-20 ne porte pas l'id de demande. `MintEvent.request_id`
  vaut `None` (inconnu) en mode générique. Le mode « contrat protégé » ci-dessous (#104) renseigne
  le vrai id.
- Événements d'administration : voir le mode « contrat protégé » (#104).

## Mode « contrat protégé » (#104)

Activé quand `MONITOR_MINTER_ADDRESS` (adresse du `ProtectedMinter` de #5) est renseignée, en plus
de `MONITOR_TOKEN_ADDRESS` (le `StableToken`, `ProtectedMinter.stable()`). Code :
`monitor/protected.py`, branché dans `ChainListener.fetch_events` / `stream_event_batches`.

Par plage de blocs, **deux** appels `eth_getLogs` : les `Transfer` du token, et les événements du
minter (`SwapRequested`, `SwapCompleted`, `RoleGranted`, `RoleRevoked`, `RateChanged`, topic0 en OU).

**Décisions d'architecture prises ici (assistant, 2026-10-11 — à relire par l'équipe)** :

1. **La vérité du mint reste le `Transfer(0x0 → X)` du token**, pas `SwapCompleted`. Ce dernier est
   écrit par le contrat qu'on surveille : s'il est bogué ou remplacé, il peut mentir. Le monitor
   émet un `MintEvent` par `Transfer(0x0)` (montant et destinataire **réellement** crédités) et lui
   rattache le `SwapCompleted` de la **même transaction** (vrai `request_id`).
2. **Le dépôt, le déposant et le taux viennent de `SwapRequested`** (transaction du déposant,
   antérieure au traitement). `detection` recalcule donc lui-même I1 (minté = dépôt × taux) et I3
   (destinataire = déposant) à partir de faits indépendants de la clé `SERVICE_ROLE`. Si la demande
   précède le début de l'écoute (cache vide), repli sur les champs de `SwapCompleted`, marqués
   `source="completion"` (moins fiables, journalisé en WARNING).
3. **Un `Transfer(0x0)` sans `SwapCompleted` dans sa transaction** = chemin de mint non prévu (I4) :
   `detection` lève une alerte **critique** avec tout le mint comme graine.
4. **Un `SwapCompleted` sans mint** est journalisé en ERROR (le contrat annonce un mint fantôme).
5. **Les événements d'administration** sortent dans le flux (`AdminObservation`) et `detection`
   les évalue **dès leur lecture** (avant #104 : seulement au mint suivant, une prise de contrôle
   restait muette jusque-là). Liste retenue = ce que #5 émet réellement : `RoleGranted`,
   `RoleRevoked`, `RateChanged`. `Upgraded` n'existe pas (#5 n'est pas upgradable).
6. **Le monitor ne dépend pas de `detection`** : il produit des faits bruts (`MintProvenance`,
   `AdminObservation`), traduits par `detection/provenance.py`.
7. **Champs partagés (#104, révision groupée de `shared/` #135)** : chaque `MintEvent` émis en
   mode contrat protégé porte sa demande (`via_protected_path`, `depositor`, `deposit_amount`,
   `rate_wad`, `provenance_source`, `claimed_minted`) via `with_provenance`. Un mint sans
   `SwapCompleted` sort avec `via_protected_path=False` ; hors mode protégé, tout reste `None`.
   `amount` / `recipient` restent la vérité du log du token. `admin_event_from_observation`
   convertit une `AdminObservation` en `shared.models.AdminEvent` (rôle bytes32 brut, `actor`,
   ancien / nouveau taux).

Limites assumées : le cache des demandes en attente vit en mémoire (borné à 100 000, PROVISOIRE) :
après un redémarrage, les demandes antérieures retombent sur `source="completion"`.

### Sous-mode « Ghost » (#8, suite #104)

Activé quand `MONITOR_GHOST_ADDRESS` (le M-Ghost, `ProtectedMinter.ghost()`) est renseignée en plus de
`MONITOR_MINTER_ADDRESS` (refusé sans elle). `MONITOR_TOKEN_ADDRESS` reste le vrai token M
(`ProtectedMinter.stable()`). Un troisième appel `eth_getLogs` par plage lit `GhostIssued` et
`GhostConverted` sur le Ghost. Interface lue dans `contracts/src/GhostToken.sol` de la PR #123 (pas encore
mergée) : à revérifier si ces signatures changent avant le merge.

**Décisions d'architecture prises ici (assistant, 2026-10-11 — à relire par l'équipe)** :

1. **Avec le Ghost, le mint est `GhostIssued(kind=MINT)`**, et non plus un `Transfer(0x0)` sur M : c'est le seul
   chemin de création de valeur (`completeSwap` → `issueFromMinter`, I4 révisé dans #8). Il est rattaché au
   `SwapCompleted` de sa transaction comme avant, donc I1/I3 sont recalculés depuis `SwapRequested`. Ici, la
   « vérité » du montant est l'événement du Ghost, un contrat distinct du minter, et plus le solde de M.
2. **Un `Transfer(0x0 → X, v)` sur M accompagné d'un `GhostConverted(X, _, v, …)` dans la même transaction est
   une conversion**, pas un mint : sa valeur a déjà été comptée à l'émission du Ghost. Il est retiré du flux de
   mints. Sans ce tri, chaque conversion légitime levait une alerte I4 **critique** (faux positif).
3. **Un `Transfer(0x0)` sur M sans `GhostConverted` correspondant** (même destinataire, même montant) contourne
   le Ghost : il reste un mint **sans provenance**, donc I4 critique. Un `SwapCompleted` présent dans la même
   transaction ne lui sert **jamais** de provenance, car il ne peut justifier que du Ghost.
4. `GhostIssued` de type `TRANSFER_M` (Ghost émis en échange d'un M brûlé) ou `RESTITUTION` ne crée pas de valeur
   nouvelle : ces événements ne sont pas des mints.
5. **Les transferts de Ghost** : tout `Transfer` ERC-20 ordinaire lu sur le Ghost (ni émission ni burn), dans le
   même appel `eth_getLogs`, devient un `TransferEvent(is_ghost=True)`, quelle que soit la valeur de
   `MONITOR_TOKEN_IS_GHOST`. C'est l'entrée du lignage (`detection/lineage.py`, #106). Avec le Ghost, M ne produit
   plus de transfert ordinaire, puisqu'un transfert de M = un burn de M + du Ghost émis.

Limites : comme avant, les émissions et les burns de Ghost ne sont pas émis comme `TransferEvent` (#10). Pour le
lignage, une conversion (burn de Ghost) n'apparaît donc pas comme un envoi vers `0x0` : question ouverte,
`docs/OPEN_QUESTIONS.md` §14. Les événements `PerimeterDelayed` et `GhostDestroyed` ne sont pas encore lus.

## Écoute des transferts (#10)

`ChainListener.stream_transfer_events()` (et `fetch_transfer_events(from, to)`) : même événement
`Transfer` ERC-20 du même contrat, même boucle de polling que les mints, converti en
`shared.models.TransferEvent`.

- **Exclus** : les mints (`from = 0x0`, déjà émis par `stream_mint_events`) et les burns
  (`to = 0x0`) — exclusion des burns **provisoire, à valider par l'équipe**.
- **Gap connu** : un `Transfer` ERC-20 ne dit pas si le token est un Ghost. `TransferEvent.is_ghost`
  vient de `MONITOR_TOKEN_IS_GHOST` (`MonitorConfig.token_is_ghost`, défaut **provisoire**
  `false` = vrai token) tant que le design du contrat Ghost n'est pas fixé.
- `python -m monitor` n'affiche encore que les mints ; les transferts s'utilisent depuis le code
  (`detection`).

## Branchement vers detection (#86)

- `ChainListener.stream_event_batches()` (et `fetch_events(from, to)`) : mints ET transferts
  dans l'ordre de la chaîne, un lot par plage lue et un lot **vide** quand un poll n'apporte rien,
  pour que `detection` clôture ses tranches à l'heure. Consommé par `python -m detection`.
- `ChainListener.read_total_supply()` : `totalSupply()` ERC-20 du token (`eth_call`), utilisé
  comme offre pour normaliser le volume (choix PROVISOIRE, voir `detection/README.md`).

## Reprise sur erreur RPC et checkpoint (#74)

- **Reprise** : tout échec d'un appel RPC (tête de chaîne, `eth_getLogs`) est **retenté sans
  limite**, attente exponentielle `MONITOR_RPC_RETRY_BASE_SECONDS` × 2ⁿ plafonnée à
  `MONITOR_RPC_RETRY_MAX_SECONDS`. Chaque échec est logué en WARNING ; à partir de
  `MONITOR_RPC_FAILURE_ALERT_AFTER` échecs consécutifs, en **ERROR « SURVEILLANCE AVEUGLE »**.
  Le curseur n'avance qu'après une plage lue et rendue : reprise **sans trou ni doublon**.
- **Log mal formé** (validation `MintEvent`/`TransferEvent`) : logué en ERROR et ignoré, sans
  couper le flux (erreur déterministe, un retry ne changerait rien).
- **Réglage manquant** (`FUJI_RPC_URL`, `MONITOR_TOKEN_ADDRESS`) : `MonitorConfigurationError`,
  **non** retentée.
- **Checkpoint** : `MONITOR_CHECKPOINT_PATH` (fichier JSON `{"last_block": N}`, écriture
  atomique). Au démarrage il **prime** sur `MONITOR_START_BLOCK`. Écrit après que le consommateur
  a repris la main sur le lot : au redémarrage, un lot peut être relu (au moins une fois), jamais
  sauté. Désactivé par défaut (warning au démarrage) : **un fichier par process**, ne pas le
  partager entre `python -m monitor` et `python -m detection`.
- Tous ces défauts sont **provisoires** (voir `docs/OPEN_QUESTIONS.md` §12).
