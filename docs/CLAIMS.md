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
| Le **protocole principal reste 100% solvable** même si l'attaquant contourne le Volet 1 (quarantaine liquide / Token Ghost). | _(à définir — vérifié par la destruction des Tokens Ghost avant conversion)_ | _(à définir — la perte financière n'est pas effacée : elle est absorbée par les acheteurs du marché secondaire)_ |
| La **friction est bornée** : notre propre surveillance ne peut pas mettre plus de **X %** de l'offre en fenêtre allongée (volet 2). | _(à définir — tests d'invariants Foundry sur le budget de quarantaine ; « vérifié par tests d'invariants », pas de preuve)_ | _(à définir — X à mesurer ; hypothèse : garde-fou on-chain non contourné, clés d'administration non compromises)_ |
| Le **soupçon est conservé** : fractionner/disperser un lot suspect ne réduit pas le soupçon total (anti-blanchiment par construction, volet 2). | _(à définir — tests d'invariants sur le modèle de contamination par ratio : somme des soupçons conservée après N transferts/splits)_ | _(à définir — porte sur le Ghost non converti ; le Ghost déjà converti avant marquage échappe au clawback)_ |
| La **friction reste locale** : un allongement de fenêtre ne touche que le périmètre suspect, pas tout le token. | _(à définir — mesure de la part du token restée en fenêtre normale pendant un incident simulé)_ | _(à définir — conditionné au **lignage** du Ghost ; sans lignage, le ciblage est impossible)_ |

## Pistes futures (mentionnées, non implémentées — trop lourdes pour 48 h)

- Signature dans une **enclave sécurisée**.
- **Signatures à seuil (MPC)**.
- **Preuves à connaissance nulle** de solvabilité.

Elles répondent au problème de la clé volée mais ne sont pas dans le périmètre de l'événement.
