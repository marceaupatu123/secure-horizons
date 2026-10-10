# CONTRACTS.md — interfaces entre modules

> ⚠️ **Fichier partagé et sensible.** On ne modifie pas ce fichier sans accord explicite de
> l'équipe. Les champs sont **volontairement laissés vides** : ils seront définis ensemble.
>
> Chaque interface décrit : son **producteur** (qui l'émet), son **consommateur** (qui la lit),
> les **champs à définir**, et un **exemple JSON vide**. Les modèles concrets vivront dans
> `shared/` (Pydantic).

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
