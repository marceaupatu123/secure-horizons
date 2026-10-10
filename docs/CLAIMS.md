# CLAIMS.md — ce qu'on affirme au jury

> **Règle : aucun chiffre n'est affiché au jury sans avoir été mesuré.**
>
> Tableau _proposé, à valider en équipe_. On ne promet que ce qu'on mesure ; on ne dit jamais
> « prouvé » (au mieux « vérifié par tests d'invariants »). Les colonnes « comment on le vérifie »
> et « limites et hypothèses » doivent être remplies avant toute démo. Les cases chiffrées restent
> **vides** tant que la mesure n'a pas été faite.

| Ce qu'on affirme au jury | Comment on le vérifie | Limites et hypothèses |
|--------------------------|-----------------------|-----------------------|
| La clé d'émission volée **ne peut pas choisir le montant** (le contrat le dérive du dépôt on-chain). | _(à définir — rejeu de l'attaque sur contrat vulnérable vs protégé)_ | _(à définir — hypothèse : clés d'administration non compromises)_ |
| La **perte maximale est bornée**. | _(à définir — tests d'invariants / fuzzing Foundry cherchant à dépasser la borne ; « vérifié par tests d'invariants », **pas** de preuve formelle)_ | _(à définir — hypothèses : plafonds appliqués on-chain, clés d'administration non compromises)_ |
| Un **gel protège les protocoles en aval**. | _(à définir — comparaison des mauvaises créances d'un faux marché de prêt avec et sans balise de risque)_ | _(à définir — marché simulé/fictif ; dépend de l'adoption de la balise par l'aval)_ |
| Le **taux de faux positifs est mesuré** sur du trafic normal rejoué. | _(à définir — mesure sur un jeu de trafic normal synthétique)_ | _(à définir — la garantie suppose que le trafic de test ressemble au trafic de calibration)_ |
| **Solvabilité (affirmation principale du Ghost).** Même si l'attaquant contourne la dérivation du montant (volet 1), un mint frauduleux **détecté avant la fin de la fenêtre Ghost** ne produit aucun vrai token non adossé : l'invariant `supply <= collateral` est maintenu. | _(à définir — tests d'invariants Foundry ; « vérifié par tests d'invariants », pas de preuve. Rejeu des scénarios A/D. **Mesure du délai de détection comparé à la fenêtre Ghost**)_ | _(à définir — ne tient que si délai de détection < fenêtre (cf. `OPEN_QUESTIONS.md` §2, priorité haute) ; la perte financière n'est pas effacée : elle est absorbée par les acheteurs de Ghost ; clés d'administration non compromises)_ |
| **Récupération (affirmation secondaire, objectif de la décision §0bis).** Un transfert suspect est **annulable tant que son Ghost n'est pas converti**, y compris après fragmentation chez N adresses. | _(à définir — rejeu d'une chaîne de N transferts/splits puis annulation ; **mesure de la part récupérée** rapportée au montant suspect)_ | _(à définir — le Ghost déjà converti échappe ; le sort du collatéral libéré dépend de #36 (non tranché) ; l'annulation demande une validation humaine (`OPEN_ANSWERS.md` §3) ; friction permanente sur les usages légitimes, à mesurer)_ |
| La **friction est bornée** : notre propre surveillance ne peut pas mettre plus de **X %** de l'offre en fenêtre allongée (volet 2). | _(à définir — tests d'invariants Foundry sur le budget de quarantaine ; « vérifié par tests d'invariants », pas de preuve)_ | _(à définir — X à mesurer ; hypothèse : garde-fou on-chain non contourné, clés d'administration non compromises)_ |
| Le **soupçon est conservé** : fractionner/disperser un lot suspect ne réduit pas le soupçon total (anti-blanchiment par construction, volet 2). | _(à définir — tests d'invariants sur le modèle de contamination par ratio : somme des soupçons conservée après N transferts/splits)_ | _(à définir — porte sur le Ghost non converti ; le Ghost déjà converti avant marquage échappe au clawback)_ |
| La **friction reste locale** : un allongement de fenêtre ne touche que le périmètre suspect, pas tout le token. | _(à définir — mesure de la part du token restée en fenêtre normale pendant un incident simulé)_ | _(à définir — conditionné au **lignage** du Ghost ; sans lignage, le ciblage est impossible)_ |

## Pistes futures (mentionnées, non implémentées — trop lourdes pour 48 h)

- Signature dans une **enclave sécurisée**.
- **Signatures à seuil (MPC)**.
- **Preuves à connaissance nulle** de solvabilité.

Elles répondent au problème de la clé volée mais ne sont pas dans le périmètre de l'événement.
