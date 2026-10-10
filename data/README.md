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

### Scénario B — une hypothèse du volet 1 tombe : les surveillants la voient-ils ?

Avec le volet 1 (montant dérivé on-chain) et sans plafond fixe (`docs/OPEN_ANSWERS.md` §0),
« rester sous les plafonds » ne rapporte rien : un mint cohérent avec son dépôt (1:1) n'est pas
une attaque, quelle que soit sa taille (§1). Le scénario B suppose donc qu'**une hypothèse du
volet 1 tombe**, le contrat seul ne suffit plus, et on **mesure** si les surveillants le voient
(détecté ou non, délai de détection) et si la réponse reste un **retard** (§3).

**B1 — hypothèse qui tombe** (piste à choisir en équipe, une seule suffit pour la démo) :

| Piste | Ce qui tombe | Ce que le surveillant de mint doit lever (§1) |
|-------|--------------|-----------------------------------------------|
| Clé admin volée | le contrat n'est plus celui qu'on croit (`Upgraded`, `RoleGranted`, nouveau rôle de mint) | événement d'administration non annoncé ; violation I5 si un chemin de mint parallèle apparaît |
| Taux / oracle manipulé | I1 est respecté, mais avec un faux taux | écart du taux au-delà de δ vs la source de référence ; violation I6 (solvabilité) |
| Destinataire détourné | I3 (« destinataire = déposant ») n'est pas appliqué | mint dont le destinataire ≠ déposant de la demande n°X |

**B2 — transferts anormaux** (inchangé) : après le mint, l'attaquant fait sortir les fonds vers
peu d'adresses neuves. Le surveillant de transferts doit lever une alerte sur **volume élevé ET
dispersion effondrée** (§9).

Les valeurs δ, ε et les seuils de dispersion sont **à mesurer** sur ce trafic, pas à inventer.

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
- Piste retenue pour le scénario B1 (clé admin, oracle ou destinataire détourné).
- Outil de génération et sa commande de lancement.

Ces points sont listés dans `docs/OPEN_QUESTIONS.md`.
