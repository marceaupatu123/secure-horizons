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

## Surveillant de transferts (#12)

`RuleBasedMonitor.check_transfer(event)` suit `docs/OPEN_ANSWERS.md` §9 (acté) : volume normalisé
par l'offre en circulation, baseline **médiane + MAD** glissante, alerte seulement si **volume
élevé ET dispersion effondrée**, jamais sur le volume seul. Les choix suivants viennent des
propositions **non actées** de `docs/OPEN_QUESTIONS.md` §2 et sont **PROVISOIRES** :

- **Tranches de 5 min** comparées à la baseline du **même créneau** (même heure les jours
  précédents). L'alerte part à la **clôture** de la tranche : au premier transfert de la tranche
  suivante, ou via `close_slot_if_due(now)` sur un minuteur (à appeler pour rester plus rapide que
  la fenêtre Ghost de 10 min).
- **Dispersion = indice de Herfindahl** (somme des parts au carré des destinataires). Dans
  l'`Alert`, `dispersion_score` = 1/HHI (« nombre effectif de destinataires », bas = concentré) ;
  le HHI brut est dans `reason` et `last_slot_stats`.
- **Destinataires distincts** : exposés (`last_slot_stats.distinct_recipients`, `reason`) mais
  **jamais** utilisés seuls : 50M vers 3 adresses neuves puis 4 bridges le font passer de 150 à
  157 seulement (testé), alors que le HHI explose.
- **Adresse neuve** = aucune transaction avant le début de la tranche dans nos données
  (`known_addresses` + tranches déjà vues). Variante future : moins de K transactions.
- **Points de sortie** = liste fixe `TransferRuleParams.exit_points` (vide par défaut), à fournir
  par le générateur de `data/` (@EnzoFB06, #24).
- **Signaux par transfert** (gros montant vers adresse neuve, découpage, sortie rapide, fan-out) :
  déjà captés par le HHI ; seulement exposés en descriptif, ils ne déclenchent rien seuls.
- **Graines** : où se trouvent, à la clôture, les fonds envoyés par des adresses neuves (les
  relais neufs tombent à 0, le soupçon arrive sur les bridges ; somme conservée). Un attaquant aux
  adresses « chauffées » à l'avance ne produit aucune graine (alerte quand même, sans graine).
- **Historique insuffisant** (< `min_history_slots` tranches du même créneau) : la tranche nourrit
  la baseline mais **n'alerte jamais**. Une tranche qui alerte n'entre pas dans la baseline.
- **Paramètres** : `TransferRuleParams` dans `detection/params.py` (longueur de tranche, période,
  fenêtre, historique minimal, seuils de z, MAD, points de sortie), tous **PROVISOIRES / À
  MESURER**.
- **GAP pour `shared/` (@marceaupatu123)** : aucun modèle partagé ne porte l'offre en circulation
  (passée via `circulating_supply` / `update_circulating_supply`) ; `Alert` n'a pas de champ pour
  le HHI brut ni pour le nombre de destinataires distincts (d'où 1/HHI dans `dispersion_score` et
  le détail dans `reason`).
