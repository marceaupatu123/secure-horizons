# CONTRACTS.md — interfaces entre modules

> ⚠️ **Fichier partagé et sensible.** On ne modifie pas ce fichier sans accord explicite de
> l'équipe. Les champs sont **volontairement laissés vides** : ils seront définis ensemble.
>
> Chaque interface décrit : son **producteur** (qui l'émet), son **consommateur** (qui la lit),
> les **champs à définir**, et un **exemple JSON vide**. Les modèles concrets vivront dans
> `shared/` (Pydantic).
>
> **Note (proposé, à valider en équipe)** : avec l'orientation « sécurité dans le contrat »
> (montant dérivé on-chain, quarantaine, gel/libération), `ResponseAction` devra peut-être
> évoluer pour couvrir le **gel** et la **libération**. À décider ensemble.

---

## MintEvent

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — représente un événement de mint observé on-chain)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## TransferEvent

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — représente un transfert de tokens observé on-chain)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## Alert

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — anomalie détectée, mint ou transfert)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## ResponseAction

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — action de la réponse graduée : alerte, pause, validation…)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## AuditLogEntry

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — entrée du journal d'audit pour la conformité DORA)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## MintRequest

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — une demande de mint et le dépôt associé enregistré on-chain)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## QuarantineRecord

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — un mint placé en quarantaine pendant la fenêtre de veto)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## FreezeRequest

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — un surveillant demande un gel ; tout surveillant peut ralentir)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## ReleaseDecision

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — un humain (multisig) lève ou confirme un gel ; nul ne peut accélérer)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```

---

## RiskBeaconUpdate

- **Producteur** : _(à définir)_
- **Consommateur** : _(à définir)_
- **Description** : _(à définir — publication d'un état de risque lu par les protocoles en aval)_

### Champs à définir

| Champ | Type | Description |
|-------|------|-------------|
| _(à définir)_ | _(à définir)_ | _(à définir)_ |

### Exemple JSON

```json
{}
```
