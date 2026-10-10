# detection

- **Rôle** : un ou plusieurs **surveillants** indépendants (règles, ML, signaux de transferts anormaux) qui détectent une anomalie sur les **mints**/**transferts**, produisent des `Alert` et peuvent **demander un gel**. L'IA n'est qu'un surveillant parmi d'autres, jamais le décideur _(proposé, à valider)_.
- **Propriétaire** : @Yannis1307 (voir `docs/TEAM.md`).
- **Lancer** : `python -m detection` ; tests : `python -m pytest detection/`.

## Surveillant de mint à règles (#11)

`RuleBasedMonitor.check_mint(event, context)` suit `docs/OPEN_ANSWERS.md` §1 : **aucun seuil sur
la taille d'un mint**. Il vérifie I1 (`minted = dépôt × taux` à ε près), I5
(`Δ totalSupply = Σ Mint − Σ Burn`), I6 (`totalSupply ≤ collatéral × facteur`), les événements
d'administration non annoncés et l'écart du taux au-delà de δ vs une référence. Une `Alert`
signifie seulement **retarder** le périmètre (§3) ; détruire / pause globale = multisig.

- **Paramètres** : un seul fichier, `detection/params.py` (ε, δ, facteur I6, gravités), tous
  **PROVISOIRES / À MESURER**, aucune valeur mesurée.
- **Entrées hors `MintEvent`** : `detection/inputs.py` (`MintContext`, `AdminEvent`,
  `AdminAnnouncement`). Une vérification dont les entrées manquent est sautée.
- **GAP pour `shared/` (@marceaupatu123)** : `MintEvent` ne porte ni dépôt ni taux ; aucun modèle
  partagé pour l'offre totale, le collatéral, les événements d'administration ni leur annonce.
- **Pas de corrélation par `request_id`** : le monitor (#9) renseigne la sentinelle provisoire
  `UNKNOWN_REQUEST_ID = 0`, qui entre en collision avec une vraie demande n°0. Le dépôt est fourni
  explicitement par l'appelant.
