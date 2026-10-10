# data — données synthétiques

- **Propriétaire** : @EnzoFB06 (voir `docs/TEAM.md`).

> **Toutes les données de ce dossier sont FICTIVES.** Aucune vraie donnée on-chain, aucune vraie
> adresse, aucune vraie clé. Faux secrets autorisés de type `FLAG{team20-canary}`.

Ce dossier ne contient pour l'instant que cette description. **Aucune donnée n'est générée** —
les scénarios ci-dessous seront produits plus tard par l'équipe (générateur à définir, voir
`docs/OPEN_QUESTIONS.md`).

## Scénarios à produire — _proposé, à valider en équipe_

### Scénario A — même attaque rejouée (vulnérable vs protégé)

Une **autorisation signée** demandant un **montant anormal**, rejouée **sur le contrat
vulnérable** (qui l'accepte) **puis sur le contrat protégé** (où le montant est dérivé on-chain du
dépôt). But : montrer la différence d'issue entre les deux contrats.

### Scénario B — attaquant sous les plafonds

L'attaquant **reste sous les plafonds** on-chain pour ne pas être arrêté par le contrat seul. Ce
sont alors les **surveillants** (règles, ML, signaux de transferts anormaux) qui doivent le
repérer et, le cas échéant, demander un gel.

### Scénario C — gel et pare-feu de contagion _(si volet 3 retenu)_

Un **gel est publié** sur la balise de risque, puis on **compare les mauvaises créances** d'un
**faux marché de prêt** (simulé, fictif) **avec et sans** lecture de la balise de risque. Les
chiffres sont à **mesurer**, pas à inventer.

### Scénario D — marché secondaire du Token Ghost _(si quarantaine liquide retenue)_

L'attaquant **génère des Tokens Ghost** et les **revend immédiatement** à des spéculateurs sur un
**pool de liquidité simulé** (fictif). L'alerte est **confirmée**, les Tokens Ghost du lot suspect
**disparaissent** (destruction par le contrat). On **mesure** les pertes **côté protocole**
(attendu : zéro, à vérifier) **vs** les pertes **côté spéculateurs**. Les chiffres sont à
**mesurer**, pas à inventer.

## À définir plus tard (ne pas trancher ici)

- Format exact des fichiers (CSV / JSON / JSONL ?) et schéma des lignes.
- Paramètres de chaque scénario (volumes, nombre d'adresses, timings, seuils implicites).
- Outil de génération et sa commande de lancement.

Ces points sont listés dans `docs/OPEN_QUESTIONS.md`.
