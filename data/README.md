# data — données synthétiques

> **Toutes les données de ce dossier sont FICTIVES.** Aucune vraie donnée on-chain, aucune vraie
> adresse, aucune vraie clé. Faux secrets autorisés de type `FLAG{team20-canary}`.

Ce dossier ne contient pour l'instant que cette description. **Aucune donnée n'est générée** —
les scénarios ci-dessous seront produits plus tard par l'équipe (générateur à définir, voir
`docs/OPEN_QUESTIONS.md`).

## Scénarios à produire

### Scénario A — mint anormal de type Resolv (détecté au mint)

Trafic **normal** pendant une période, puis un **mint anormal** : émission d'un volume de tokens
disproportionné par rapport au collatéral déposé (reproduit le schéma Resolv : clé compromise →
mint massif non collatéralisé). L'anomalie doit être **détectable au moment du mint**.

### Scénario B — mint discret, détection sur les transferts

Variante où le **mint passe sous le radar** (volume suffisamment faible ou étalé pour ne pas
déclencher l'alerte de mint). Ce sont alors les **transferts anormaux** qui déclenchent l'alerte :
gros montants vers des **adresses neuves**, **découpage** (structuring) en plusieurs transferts,
**sorties rapides** vers des points de sortie (échanges).

## À définir plus tard (ne pas trancher ici)

- Format exact des fichiers (CSV / JSON / JSONL ?) et schéma des lignes.
- Paramètres de chaque scénario (volumes, nombre d'adresses, timings, seuils implicites).
- Outil de génération et sa commande de lancement.

Ces points sont listés dans `docs/OPEN_QUESTIONS.md`.
