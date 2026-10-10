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
- **Pas encore fait** : événements d'administration (`Upgraded`, `RoleGranted`, OPEN_ANSWERS §1),
  écoute des transferts (#10).
