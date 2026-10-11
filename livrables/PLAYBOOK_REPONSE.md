# Playbook de réponse — Équipe 20, Secure Horizons

Procédure suivie quand un surveillant lève une alerte sur le token. Elle décrit ce que fait
`response/orchestrator.py`, tel qu'acté dans `docs/OPEN_ANSWERS.md` §3 et §9.

> Maquette sur données **fictives**. Le multisig est **simulé** ; durées et seuils sont des
> valeurs de départ, à mesurer, pas actées.

## Principe

- La sécurité vit d'abord **dans le contrat** ; la surveillance est un renfort.
- **Retarder n'est pas bloquer** : on suspend la conversion Ghost → vrai token d'un périmètre
  ciblé, on ne gèle pas la circulation.
- **Silence = retour à la normale.** Un retard que personne ne confirme expire seul : le biais
  par défaut favorise l'utilisateur légitime.
- **L'IA ne décide jamais seule** d'une destruction ni d'une pause globale.

## Qui fait quoi

| Action | Qui décide | Automatique ? | Réversible ? |
|--------|-----------|---------------|--------------|
| Lever une alerte | Surveillants à règles (mint, transferts) | Oui | — |
| **Retarder** un périmètre (fenêtre Ghost 10 min → 1 h) | Surveillant ou IA, seul | Oui | Oui, expire seul |
| Expliquer l'alerte, pré-remplir le rapport | IA (LLM), appelée **uniquement sur alerte** | Oui | — (brouillon à relire) |
| Proposer une destruction | IA | Oui, mais **sans effet** | — |
| **Détruire** le Ghost suspect | Humains, multisig **2 sur 3** | Non | **Non** |
| **Pause globale** du protocole | Humains, multisig **3 sur 3** | Non | Oui, par le même quorum |
| Lever un retard avant échéance | Humains, multisig 2 sur 3 | Non | — |

Aucun acteur seul ne peut accélérer, libérer ou raccourcir (veto asymétrique).

## Déroulé d'un incident

1. **Détection.** Un surveillant constate un mint hors invariant, ou un volume élevé ET une
   dispersion effondrée sur les transferts. Il émet une alerte avec les adresses concernées.
2. **Confinement automatique.** L'orchestrateur retarde le sujet et chaque adresse liée : la
   conversion de leur Ghost est suspendue, la circulation reste permise. Le soupçon suit la
   valeur (contamination par ratio) : disperser ne nettoie pas.
3. **Signal vers l'aval.** La balise de risque expose le niveau de soupçon ; un protocole de
   prêt qui la lit refuse le Ghost suspect en garantie.
4. **Qualification.** L'IA rédige une explication de l'alerte et un brouillon de rapport
   d'incident. Elle peut proposer une destruction : la proposition est tracée, sans effet.
5. **Décision humaine**, pendant la fenêtre allongée. Trois issues :
   - **rien** → le retard expire, retour automatique à la normale (cas du faux positif) ;
   - **destruction** (2/3) → la fraction suspecte du Ghost non converti est détruite ;
   - **pause globale** (3/3) → dernier recours, levée par le même quorum.
6. **Restitution.** Le collatéral libéré par une destruction va dans une réserve de
   restitution ; le protocole ne garde rien.
7. **Clôture.** Le rapport d'incident est relu et complété par un humain.

## Comment c'est documenté

- **Journal d'audit** append-only : chaque alerte, retard, proposition, décision multisig,
  rejet (quorum non atteint, signataire inconnu) et expiration y est horodaté avec son auteur.
  Export JSONL : `python -m response --audit-jsonl <chemin>`.
- **Rapport d'incident** pré-rempli d'après les rubriques de notification d'incident majeur
  DORA (classification, périmètre, chronologie, qui a décidé quoi). C'est un **brouillon** :
  il ne constitue pas une déclaration conforme sans relecture humaine.

Un auditeur peut ainsi vérifier, pour chaque décision : qui l'a prise, sur quelle alerte, avec
quel quorum, et à quelle heure.

## « Et si le modèle se trompe, qui est responsable ? »

Le pire qu'un surveillant ou l'IA puisse faire seul est de **retarder** une conversion sur un
périmètre ciblé, pour une durée bornée. Mesuré sur un faux positif simulé (scénario N3) :
8,1 % à 8,5 % de l'offre retardée inutilement, puis retour seul à la normale, aucune
destruction. Toute action irréversible porte la signature d'au moins deux humains, tracée au
journal : la responsabilité d'une destruction est la leur, pas celle du modèle.

## Limites

- Le canal de notification des signataires (qui est prévenu, comment) n'est pas défini.
- Le retard doit durer plus longtemps que le temps de réaction réel du multisig, qui n'est
  pas mesuré.
- Un surveillant compromis peut retarder à répétition ; remède : révocation de son rôle par
  l'administrateur. Le budget de quarantaine borne la part de l'offre touchée.
- Le Ghost déjà converti avant l'alerte échappe à la destruction.
