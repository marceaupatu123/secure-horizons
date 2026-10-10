# CONTRACTS.md — interfaces entre modules

> ⚠️ **Fichier partagé et sensible.** On ne modifie pas ce fichier sans accord explicite de
> l'équipe (review de 2 propriétaires, cf. `docs/TEAM.md`). Il **spécifie** les 13 modèles
> partagés de `shared/models.py` : c'est le contrat que l'implémentation suivra. Toute
> évolution de schéma passe d'abord par ce fichier, puis par le propriétaire de `shared/`.
>
> Chaque interface décrit : son **producteur** (qui l'émet), son **consommateur** (qui la lit),
> une **description**, le **tableau des champs** (nom, type, borne/validation, description), et un
> **exemple JSON non vide et valide**. Les modèles concrets vivent dans `shared/` (Pydantic).

---

## Conventions transverses (s'appliquent à TOUS les modèles)

Ces règles sont **actées** et dérivent des décisions d'équipe (`docs/OPEN_ANSWERS.md` §0, §0bis,
§9) et des contraintes EVM / Fuji. Elles ne sont pas re-débattues ici.

### Pydantic strict

- Chaque modèle : `model_config = ConfigDict(extra="forbid")`. Aucun champ hors schéma n'est
  toléré. La base permissive `_OpenModel` (`extra="allow"`) est **supprimée** à l'implémentation.
- Tous les champs sont **explicitement typés**, avec `Field(..., description=...)`. Chaque classe
  porte une docstring.
- Les bornes sont validées : `ge`/`le` pour les ratios, `gt`/`ge` pour les montants, `pattern`
  pour adresses et hash.
- Les ensembles fermés sont des `Enum` (str Enum), jamais des chaînes libres.

### Représentation du temps — DÉCISION

**Tous les champs temporels sont des `datetime` en UTC** (jamais d'int epoch). En JSON, ils sont
sérialisés en **ISO 8601 avec offset** (`"2026-10-10T14:30:00Z"` / `"...+00:00"`). Choix retenu :
Pydantic valide et sérialise nativement `datetime`, et un journal DORA lisible vaut mieux qu'un
entier opaque. Les champs temporels sont nommés avec le suffixe `_at` (`observed_at`,
`created_at`, `expires_at`, …).

### Identités et montants EVM — DÉCISION

Deux alias de types réutilisables, validés par `pattern` Pydantic :

| Alias | Type sous-jacent | Validation (regex) | Sens |
|-------|------------------|--------------------|------|
| `Address` | `str` | `^0x[a-fA-F0-9]{40}$` | adresse EVM (20 octets hex) |
| `TxHash` | `str` | `^0x[a-fA-F0-9]{64}$` | hash de transaction / de log (32 octets hex) |

- **Montants** : toujours des **entiers en base units** (`int`), **jamais de `float`** pour de la
  monnaie. Positivité imposée : `gt=0` quand un montant nul n'a pas de sens (ex. montant d'un
  mint), `ge=0` quand zéro est licite (ex. solde, montant suspect résiduel).
- `block_number: int` avec `ge=0`.
- `chain_id: int` : identifiant de chaîne EVM (Fuji = `43113`), `ge=1`.

### Soupçon : ratio ET montant absolu — DÉCISION

Partout où circule le soupçon (au minimum `Alert`, `RiskBeaconUpdate`, `GhostTokenBurnEvent`, et
tout modèle de contamination), **deux** champs coexistent (cf. `OPEN_ANSWERS.md` §9) :

- `contamination_ratio: float`, borné `ge=0.0, le=1.0` : fraction suspecte normalisée.
- `suspect_amount: int` (base units), `ge=0` : montant absolu suspect. **Parade à
  l'auto-contamination défensive** : insensible à la dilution, il reste explicite et n'est jamais
  dérivé silencieusement du ratio.

### Enums fermés — DÉCISION

| Enum | Valeurs | Utilisé par |
|------|---------|-------------|
| `AlertKind` | `mint`, `transfer`, `baseline_anomaly`, `beacon` | `Alert` |
| `AlertSeverity` | `info`, `warning`, `critical` | `Alert` |
| `ResponseActionType` | `delay`, `destroy`, `global_pause` | `ResponseAction` |
| `ResponseActionStatus` | `proposed`, `applied`, `expired`, `rejected` | `ResponseAction` |
| `FreezeDirection` | `extend` (allonger la fenêtre), `confirm` (geler/détruire) | `FreezeRequest` |
| `ReleaseVerdict` | `release` (lever), `confirm_freeze`, `confirm_destroy`, `global_pause` | `ReleaseDecision` |
| `QuarantineStatus` | `active`, `extended`, `released`, `burned` | `QuarantineRecord` |
| `BeaconRiskLevel` | `normal`, `elevated`, `frozen` | `RiskBeaconUpdate` |

Les trois verbes de réponse (`delay` / `destroy` / `global_pause`) reprennent exactement les trois
verbes de `OPEN_ANSWERS.md` §9 (retarder / détruire / pause globale). `delay` est auto-expirant et
décidable par un surveillant/IA seul ; `destroy` et `global_pause` exigent le multisig humain
(porté par `ReleaseDecision`).

---

## MintEvent

- **Producteur** : module `monitor` (`ChainListener.stream_mint_events`).
- **Consommateur** : module `detection` (`Monitor.check_mint`).
- **Description** : événement de mint observé on-chain sur Fuji. Le montant est celui **dérivé
  on-chain par le contrat** (volet 1), pas un montant signé par le demandeur.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `tx_hash` | `TxHash` | `^0x[a-fA-F0-9]{64}$` | hash de la transaction de mint |
| `log_index` | `int` | `ge=0` | index du log dans la transaction (unicité event) |
| `block_number` | `int` | `ge=0` | numéro de bloc |
| `chain_id` | `int` | `ge=1` | identifiant de chaîne EVM (43113 = Fuji) |
| `observed_at` | `datetime` | UTC, ISO 8601 | horodatage d'observation par le monitor |
| `recipient` | `Address` | regex adresse | adresse créditée par le mint |
| `amount` | `int` | `gt=0` | montant minté en base units (dérivé on-chain) |
| `request_id` | `int` | `ge=0` | identifiant de la `MintRequest` traitée (« demande n°X ») |

### Exemple JSON

```json
{
  "tx_hash": "0x3f2a1b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f701",
  "log_index": 0,
  "block_number": 12345678,
  "chain_id": 43113,
  "observed_at": "2026-10-10T14:30:00Z",
  "recipient": "0x1111111111111111111111111111111111111111",
  "amount": 1000000000000000000,
  "request_id": 42
}
```

---

## TransferEvent

- **Producteur** : module `monitor` (`ChainListener.stream_transfer_events`).
- **Consommateur** : module `detection` (`Monitor.check_transfer`).
- **Description** : transfert de tokens observé on-chain. Tout transfert déclenche une émission de
  Ghost chez le destinataire (cf. `OPEN_ANSWERS.md` §0bis) ; cet événement est l'observation brute
  du transfert, pas le Ghost lui-même.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `tx_hash` | `TxHash` | `^0x[a-fA-F0-9]{64}$` | hash de la transaction de transfert |
| `log_index` | `int` | `ge=0` | index du log dans la transaction |
| `block_number` | `int` | `ge=0` | numéro de bloc |
| `chain_id` | `int` | `ge=1` | identifiant de chaîne EVM |
| `observed_at` | `datetime` | UTC, ISO 8601 | horodatage d'observation |
| `sender` | `Address` | regex adresse | adresse émettrice |
| `recipient` | `Address` | regex adresse | adresse réceptrice |
| `amount` | `int` | `gt=0` | montant transféré en base units |
| `is_ghost` | `bool` | — | `true` si le token transféré est déjà un Ghost (Ghost d'un Ghost) |

### Exemple JSON

```json
{
  "tx_hash": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
  "log_index": 3,
  "block_number": 12345690,
  "chain_id": 43113,
  "observed_at": "2026-10-10T14:31:12Z",
  "sender": "0x1111111111111111111111111111111111111111",
  "recipient": "0x2222222222222222222222222222222222222222",
  "amount": 250000000000000000,
  "is_ghost": true
}
```

---

## Alert

- **Producteur** : module `detection` (`Monitor.check_mint` / `check_transfer`).
- **Consommateur** : module `response` (`ResponseOrchestrator.handle_alert`), module `llm` (sur
  alerte uniquement), module `dashboard`.
- **Description** : anomalie détectée sur un mint, un transfert ou la baseline adaptative. Porte le
  soupçon (ratio + montant absolu). Le discriminant acté est « volume élevé ET dispersion
  effondrée » (`OPEN_ANSWERS.md` §9) ; les scores de dispersion sont transportés ici.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `alert_id` | `str` | non vide | identifiant unique de l'alerte (UUID synthétique) |
| `kind` | `AlertKind` | enum | nature de l'anomalie (`mint`/`transfer`/`baseline_anomaly`/`beacon`) |
| `severity` | `AlertSeverity` | enum | gravité (`info`/`warning`/`critical`) |
| `created_at` | `datetime` | UTC, ISO 8601 | horodatage de création de l'alerte |
| `monitor_name` | `str` | non vide | surveillant émetteur (ex. `rule_mint`, `rule_transfer`, `ml`) |
| `subject_address` | `Address` | regex adresse | adresse concernée par le soupçon |
| `source_tx_hash` | `TxHash \| None` | regex hash si présent | transaction déclenchante (si applicable) |
| `contamination_ratio` | `float` | `ge=0.0, le=1.0` | fraction suspecte normalisée |
| `suspect_amount` | `int` | `ge=0` | montant absolu suspect, base units |
| `dispersion_score` | `float \| None` | `ge=0.0` | mesure de dispersion (effondrée = concentration) |
| `volume_zscore` | `float \| None` | — | écart du volume courant vs baseline médiane+MAD |
| `reason` | `str` | non vide | explication lisible (règle déclenchée) |

### Exemple JSON

```json
{
  "alert_id": "a1f0c2e4-0001-4a2b-8c3d-5e6f70819203",
  "kind": "transfer",
  "severity": "critical",
  "created_at": "2026-10-10T14:31:20Z",
  "monitor_name": "rule_transfer",
  "subject_address": "0x2222222222222222222222222222222222222222",
  "source_tx_hash": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
  "contamination_ratio": 0.87,
  "suspect_amount": 870000000000000000,
  "dispersion_score": 0.04,
  "volume_zscore": 6.2,
  "reason": "Volume eleve ET dispersion effondree : 2 destinations, adresses neuves"
}
```

---

## ResponseAction

- **Producteur** : module `response` (`ResponseOrchestrator.handle_alert` / `request_freeze` /
  `apply_release`).
- **Consommateur** : module `response` (journalisation), module `dashboard`, module `audit`
  (`AuditLogEntry`).
- **Description** : action de la réponse graduée. Un des trois verbes actés (`delay` /
  `destroy` / `global_pause`). `delay` est auto-expirant (`expires_at` renseigné) ; `destroy` et
  `global_pause` référencent la décision multisig (`decision_id`).

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `action_id` | `str` | non vide | identifiant unique de l'action |
| `action_type` | `ResponseActionType` | enum | `delay` / `destroy` / `global_pause` |
| `status` | `ResponseActionStatus` | enum | `proposed`/`applied`/`expired`/`rejected` |
| `created_at` | `datetime` | UTC, ISO 8601 | horodatage de création |
| `expires_at` | `datetime \| None` | UTC si présent | expiration (obligatoire si `action_type=delay`) |
| `perimeter_address` | `Address \| None` | regex adresse si présent | périmètre ciblé (`None` si `global_pause`) |
| `triggering_alert_id` | `str \| None` | — | alerte à l'origine de l'action |
| `decision_id` | `str \| None` | — | `ReleaseDecision` multisig (requis pour `destroy`/`global_pause`) |
| `contamination_ratio` | `float \| None` | `ge=0.0, le=1.0` | ratio au moment de l'action |
| `suspect_amount` | `int \| None` | `ge=0` | montant suspect visé (base units) |

### Exemple JSON

```json
{
  "action_id": "act-0001",
  "action_type": "delay",
  "status": "applied",
  "created_at": "2026-10-10T14:31:25Z",
  "expires_at": "2026-10-10T15:01:25Z",
  "perimeter_address": "0x2222222222222222222222222222222222222222",
  "triggering_alert_id": "a1f0c2e4-0001-4a2b-8c3d-5e6f70819203",
  "decision_id": null,
  "contamination_ratio": 0.87,
  "suspect_amount": 870000000000000000
}
```

---

## AuditLogEntry

- **Producteur** : module `response` (`ResponseOrchestrator.record_audit`).
- **Consommateur** : module `dashboard`, archivage de conformité (DORA).
- **Description** : entrée immuable du journal d'audit. Trace qui a fait quoi, quand, sur quoi, et
  pourquoi — pour la conformité DORA. Append-only ; jamais modifiée après écriture.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `entry_id` | `str` | non vide | identifiant unique de l'entrée |
| `recorded_at` | `datetime` | UTC, ISO 8601 | horodatage d'écriture |
| `actor` | `str` | non vide | auteur (`monitor:rule_transfer`, `multisig`, `contract`, `llm`) |
| `event_type` | `str` | non vide | type d'évènement journalisé (ex. `response_action`, `freeze`) |
| `subject_address` | `Address \| None` | regex adresse si présent | adresse concernée |
| `related_action_id` | `str \| None` | — | `ResponseAction` liée, le cas échéant |
| `related_tx_hash` | `TxHash \| None` | regex hash si présent | transaction on-chain liée |
| `payload` | `dict[str, str]` | — | détails structurés clé→valeur (données fictives uniquement) |
| `message` | `str` | non vide | résumé lisible pour un auditeur humain |

### Exemple JSON

```json
{
  "entry_id": "audit-0001",
  "recorded_at": "2026-10-10T14:31:25Z",
  "actor": "monitor:rule_transfer",
  "event_type": "response_action",
  "subject_address": "0x2222222222222222222222222222222222222222",
  "related_action_id": "act-0001",
  "related_tx_hash": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
  "payload": {"action_type": "delay", "window_minutes": "30"},
  "message": "Fenetre Ghost allongee a 30 min sur le perimetre suspect (auto-expirant)"
}
```

---

## MintRequest

- **Producteur** : faux protocole / demandeur, enregistré on-chain ; lu par le **contrat protégé**.
- **Consommateur** : le contrat protégé (volet 1) ; module `monitor` pour corrélation
  (`MintEvent.request_id`).
- **Description** : demande de mint et dépôt associé enregistré on-chain. **La signature autorise
  « traiter la demande n°X », PAS un montant** : le contrat dérive lui-même le montant du dépôt
  on-chain (`OPEN_ANSWERS.md` §0). `requested_amount` n'est donc **pas** un champ : le montant
  n'est jamais fourni par le demandeur.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `request_id` | `int` | `ge=0` | identifiant de la demande (« demande n°X » autorisée par la signature) |
| `requester` | `Address` | regex adresse | adresse du demandeur |
| `deposit_token` | `Address` | regex adresse | token du dépôt enregistré on-chain |
| `deposit_amount` | `int` | `gt=0` | montant du dépôt en base units (le contrat dérive le mint de là) |
| `created_at` | `datetime` | UTC, ISO 8601 | horodatage d'enregistrement de la demande |
| `chain_id` | `int` | `ge=1` | identifiant de chaîne EVM |
| `signature` | `str` | `^0x[a-fA-F0-9]+$` | signature autorisant « traiter la demande n°X » (hex) |

### Exemple JSON

```json
{
  "request_id": 42,
  "requester": "0x3333333333333333333333333333333333333333",
  "deposit_token": "0x4444444444444444444444444444444444444444",
  "deposit_amount": 1000000000000000000,
  "created_at": "2026-10-10T14:29:50Z",
  "chain_id": 43113,
  "signature": "0xdeadbeefcafe0011223344556677889900aabbccddeeff"
}
```

---

## QuarantineRecord

- **Producteur** : le contrat (quarantaine liquide) ; miroir côté `response`/`monitor`.
- **Consommateur** : module `response`, module `dashboard`, module `detection` (budget de
  quarantaine).
- **Description** : état de quarantaine d'un périmètre (adresse) : solde Ghost non converti,
  fenêtre courante, ratio de contamination. La fenêtre normale est courte (ex. 10 min) ; elle peut
  être allongée (`status=extended`, auto-expirante). `active`→`released` (conversion 1:1) ou
  `active`→`burned` (gel confirmé).

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `record_id` | `str` | non vide | identifiant unique de l'enregistrement |
| `address` | `Address` | regex adresse | adresse (périmètre) sous quarantaine |
| `status` | `QuarantineStatus` | enum | `active`/`extended`/`released`/`burned` |
| `ghost_balance` | `int` | `ge=0` | solde Ghost non converti, base units |
| `contamination_ratio` | `float` | `ge=0.0, le=1.0` | ratio de contamination de l'adresse |
| `suspect_amount` | `int` | `ge=0` | montant absolu suspect (= `ratio × ghost_balance`), base units |
| `window_opened_at` | `datetime` | UTC, ISO 8601 | ouverture de la fenêtre courante |
| `window_expires_at` | `datetime` | UTC, ISO 8601 | fin de la fenêtre courante (après quoi conversion possible) |
| `chain_id` | `int` | `ge=1` | identifiant de chaîne EVM |

### Exemple JSON

```json
{
  "record_id": "q-0001",
  "address": "0x2222222222222222222222222222222222222222",
  "status": "extended",
  "ghost_balance": 1000000000000000000,
  "contamination_ratio": 0.87,
  "suspect_amount": 870000000000000000,
  "window_opened_at": "2026-10-10T14:31:12Z",
  "window_expires_at": "2026-10-10T15:01:12Z",
  "chain_id": 43113
}
```

---

## FreezeRequest

- **Producteur** : un surveillant / l'IA (`delay`, direction sûre, solitaire) ou un préalable à une
  décision multisig.
- **Consommateur** : module `response` (`ResponseOrchestrator.request_freeze`).
- **Description** : demande de gel émanant d'un surveillant. Veto asymétrique : tout surveillant
  peut **ralentir** (`direction=extend`, auto-expirant) ; une demande dans le sens risqué
  (`direction=confirm`) est seulement une **proposition** qui devra être tranchée par une
  `ReleaseDecision` multisig. Nul ne peut accélérer / raccourcir via ce modèle.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `request_id` | `str` | non vide | identifiant unique de la demande de gel |
| `direction` | `FreezeDirection` | enum | `extend` (allonger, sûr) / `confirm` (proposer gel/destruction) |
| `requested_by` | `str` | non vide | surveillant/IA à l'origine (ex. `monitor:rule_transfer`, `ai`) |
| `created_at` | `datetime` | UTC, ISO 8601 | horodatage de la demande |
| `perimeter_address` | `Address` | regex adresse | périmètre visé |
| `triggering_alert_id` | `str \| None` | — | alerte à l'origine |
| `contamination_ratio` | `float` | `ge=0.0, le=1.0` | ratio justifiant la demande |
| `suspect_amount` | `int` | `ge=0` | montant absolu suspect, base units |
| `extend_minutes` | `int \| None` | `gt=0` si présent | durée d'allongement demandée (si `direction=extend`) |

### Exemple JSON

```json
{
  "request_id": "fr-0001",
  "direction": "extend",
  "requested_by": "monitor:rule_transfer",
  "created_at": "2026-10-10T14:31:22Z",
  "perimeter_address": "0x2222222222222222222222222222222222222222",
  "triggering_alert_id": "a1f0c2e4-0001-4a2b-8c3d-5e6f70819203",
  "contamination_ratio": 0.87,
  "suspect_amount": 870000000000000000,
  "extend_minutes": 30
}
```

---

## ReleaseDecision

- **Producteur** : humains via **multisig** (M parmi N).
- **Consommateur** : module `response` (`ResponseOrchestrator.apply_release`).
- **Description** : décision humaine qui lève un gel ou confirme une action irréversible. Seule
  voie pour `destroy` et `global_pause` (`OPEN_ANSWERS.md` §9). Porte les signatures multisig :
  voler une clé ne suffit pas. Nul ne peut accélérer ; `release` revient à la normale.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `decision_id` | `str` | non vide | identifiant unique de la décision |
| `verdict` | `ReleaseVerdict` | enum | `release`/`confirm_freeze`/`confirm_destroy`/`global_pause` |
| `decided_at` | `datetime` | UTC, ISO 8601 | horodatage de la décision |
| `perimeter_address` | `Address \| None` | regex adresse si présent | périmètre (`None` si `global_pause`) |
| `related_freeze_id` | `str \| None` | — | `FreezeRequest` tranchée |
| `signers` | `list[Address]` | min 1 adresse, chacune regex | signataires multisig |
| `threshold` | `int` | `ge=1` | seuil M du multisig (M parmi N) requis |
| `burn_ratio` | `float \| None` | `ge=0.0, le=1.0` | fraction à détruire si `confirm_destroy` |
| `rationale` | `str` | non vide | justification humaine consignée (audit) |

### Exemple JSON

```json
{
  "decision_id": "rd-0001",
  "verdict": "confirm_destroy",
  "decided_at": "2026-10-10T14:45:00Z",
  "perimeter_address": "0x2222222222222222222222222222222222222222",
  "related_freeze_id": "fr-0001",
  "signers": [
    "0x5555555555555555555555555555555555555555",
    "0x6666666666666666666666666666666666666666"
  ],
  "threshold": 2,
  "burn_ratio": 0.87,
  "rationale": "Audit humain : lignage frauduleux confirme, destruction de la fraction suspecte"
}
```

---

## RiskBeaconUpdate

- **Producteur** : module `response` / détection (publication de la balise de risque).
- **Consommateur** : protocoles DeFi **en aval** (volet 3 : faux marché de prêt), module
  `dashboard`.
- **Description** : publication de l'état de risque d'une adresse/périmètre — le **prix du risque**
  continu, cœur du projet (`OPEN_ANSWERS.md` §0). L'aval lit le ratio pour accepter/refuser une
  garantie au-dessus d'un seuil. Un pool AMM est une adresse avec un ratio comme une autre.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `beacon_id` | `str` | non vide | identifiant unique de la publication |
| `address` | `Address` | regex adresse | adresse/périmètre couvert (y compris pool AMM) |
| `risk_level` | `BeaconRiskLevel` | enum | `normal`/`elevated`/`frozen` |
| `contamination_ratio` | `float` | `ge=0.0, le=1.0` | prix du risque : fraction suspecte publiée |
| `suspect_amount` | `int` | `ge=0` | montant absolu suspect publié, base units |
| `published_at` | `datetime` | UTC, ISO 8601 | horodatage de publication |
| `window_expires_at` | `datetime \| None` | UTC si présent | fin de fenêtre allongée en cours, le cas échéant |
| `chain_id` | `int` | `ge=1` | identifiant de chaîne EVM |

### Exemple JSON

```json
{
  "beacon_id": "beacon-0001",
  "address": "0x2222222222222222222222222222222222222222",
  "risk_level": "elevated",
  "contamination_ratio": 0.87,
  "suspect_amount": 870000000000000000,
  "published_at": "2026-10-10T14:31:30Z",
  "window_expires_at": "2026-10-10T15:01:12Z",
  "chain_id": 43113
}
```

---

## GhostTokenMintEvent

- **Producteur** : le **contrat** (émission de Ghost à chaque transfert / mint).
- **Consommateur** : module `monitor`, module `response` (quarantaine), module `dashboard`.
- **Description** : émission d'un Token Ghost chez le destinataire lors d'un transfert ou d'un mint
  (quarantaine liquide, `OPEN_ANSWERS.md` §0bis). Le Ghost porte son **ratio de contamination
  entrant** (lignage par ratio par adresse) : le montant envoyé porte le ratio courant de
  l'expéditeur.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `tx_hash` | `TxHash` | regex hash | transaction ayant émis le Ghost |
| `log_index` | `int` | `ge=0` | index du log |
| `block_number` | `int` | `ge=0` | numéro de bloc |
| `chain_id` | `int` | `ge=1` | identifiant de chaîne EVM |
| `minted_at` | `datetime` | UTC, ISO 8601 | horodatage d'émission du Ghost |
| `recipient` | `Address` | regex adresse | adresse recevant le Ghost |
| `amount` | `int` | `gt=0` | montant de Ghost émis, base units |
| `incoming_ratio` | `float` | `ge=0.0, le=1.0` | ratio porté par le montant entrant (ratio expéditeur) |
| `window_expires_at` | `datetime` | UTC, ISO 8601 | fin de fenêtre avant conversion 1:1 possible |
| `source_transfer_tx` | `TxHash \| None` | regex hash si présent | transfert sous-jacent (si issu d'un transfert) |

### Exemple JSON

```json
{
  "tx_hash": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778",
  "log_index": 4,
  "block_number": 12345690,
  "chain_id": 43113,
  "minted_at": "2026-10-10T14:31:12Z",
  "recipient": "0x2222222222222222222222222222222222222222",
  "amount": 250000000000000000,
  "incoming_ratio": 0.87,
  "window_expires_at": "2026-10-10T14:41:12Z",
  "source_transfer_tx": "0x9a8b7c6d5e4f30211223344556677889900aabbccddeeff00112233445566778"
}
```

---

## GhostTokenRedemptionEvent

- **Producteur** : le **contrat** (conversion Ghost → vrai token).
- **Consommateur** : module `monitor`, module `response`, module `dashboard`.
- **Description** : conversion 1:1 d'un Token Ghost en vrai token, après la fenêtre sans anomalie.
  Autorisée **uniquement** si le ratio **et** le montant absolu suspect sont sous seuil au moment
  de la conversion (`OPEN_ANSWERS.md` §9). Une marge peut être prélevée (barème à mesurer, exprimé
  en base units).

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `tx_hash` | `TxHash` | regex hash | transaction de conversion |
| `log_index` | `int` | `ge=0` | index du log |
| `block_number` | `int` | `ge=0` | numéro de bloc |
| `chain_id` | `int` | `ge=1` | identifiant de chaîne EVM |
| `redeemed_at` | `datetime` | UTC, ISO 8601 | horodatage de conversion |
| `holder` | `Address` | regex adresse | adresse convertissant son Ghost |
| `ghost_amount` | `int` | `gt=0` | montant de Ghost converti, base units |
| `token_amount` | `int` | `ge=0` | montant de vrai token reçu (après marge éventuelle), base units |
| `fee_amount` | `int` | `ge=0` | marge prélevée à la conversion, base units (0 si aucune) |
| `contamination_ratio` | `float` | `ge=0.0, le=1.0` | ratio au moment de la conversion (sous seuil) |

### Exemple JSON

```json
{
  "tx_hash": "0xaabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",
  "log_index": 1,
  "block_number": 12345750,
  "chain_id": 43113,
  "redeemed_at": "2026-10-10T14:42:00Z",
  "holder": "0x7777777777777777777777777777777777777777",
  "ghost_amount": 500000000000000000,
  "token_amount": 499000000000000000,
  "fee_amount": 1000000000000000,
  "contamination_ratio": 0.01
}
```

---

## GhostTokenBurnEvent

- **Producteur** : le **contrat**, sur gel confirmé par `ReleaseDecision` multisig
  (`verdict=confirm_destroy`).
- **Consommateur** : module `response`, module `audit` (`AuditLogEntry`), module `dashboard`.
- **Description** : destruction de la **fraction suspecte** du Ghost non converti d'une adresse
  (`burn_ratio × ghost_balance`), pas tout le solde (`OPEN_ANSWERS.md` §9). Porte le ratio ET le
  montant absolu suspect détruits : destruction proportionnelle à l'exposition réelle.

### Champs

| Champ | Type | Borne / validation | Description |
|-------|------|--------------------|-------------|
| `tx_hash` | `TxHash` | regex hash | transaction de destruction |
| `log_index` | `int` | `ge=0` | index du log |
| `block_number` | `int` | `ge=0` | numéro de bloc |
| `chain_id` | `int` | `ge=1` | identifiant de chaîne EVM |
| `burned_at` | `datetime` | UTC, ISO 8601 | horodatage de destruction |
| `address` | `Address` | regex adresse | adresse dont le Ghost suspect est détruit |
| `burned_amount` | `int` | `gt=0` | montant de Ghost détruit, base units (= fraction suspecte) |
| `contamination_ratio` | `float` | `ge=0.0, le=1.0` | ratio appliqué pour la destruction |
| `suspect_amount` | `int` | `ge=0` | montant absolu suspect détruit, base units |
| `decision_id` | `str` | non vide | `ReleaseDecision` multisig autorisant la destruction |

### Exemple JSON

```json
{
  "tx_hash": "0xffeeddccbbaa00998877665544332211ffeeddccbbaa00998877665544332211",
  "log_index": 2,
  "block_number": 12345800,
  "chain_id": 43113,
  "burned_at": "2026-10-10T14:46:00Z",
  "address": "0x2222222222222222222222222222222222222222",
  "burned_amount": 870000000000000000,
  "contamination_ratio": 0.87,
  "suspect_amount": 870000000000000000,
  "decision_id": "rd-0001"
}
```
