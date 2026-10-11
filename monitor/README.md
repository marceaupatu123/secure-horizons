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
- **Gap connu** : un `Transfer` ERC-20 ne porte pas l'id de demande. `MintEvent.request_id` vaut
  la sentinelle `UNKNOWN_REQUEST_ID` (0) tant que le contrat (#5) n'émet pas d'événement dédié ;
  il suffira alors de passer un autre `MintLogDecoder` à `ChainListener`.
- **Pas encore fait** : événements d'administration (`Upgraded`, `RoleGranted`, OPEN_ANSWERS §1).

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
