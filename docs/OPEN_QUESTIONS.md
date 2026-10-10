# OPEN_QUESTIONS.md — décisions à prendre en équipe

Ce fichier liste les décisions de conception **non tranchées**. Aucune n'est décidée par un
assistant IA : on les discute et on les acte ici (ajouter la décision + la date sous chaque point).

## 0. Décision structurante — _proposé, à valider en équipe_

**La sécurité vit-elle dans le contrat (montant dérivé on-chain, plafonds, quarantaine, multisig)
ou seulement autour (surveillance + pause) ?**

Sous-questions liées (à ne pas trancher ici) :

- Le **montant dérivé on-chain** est-il compatible avec notre faux protocole, et que devient la
  **signature** (autorise « traiter la demande n°X » plutôt qu'un montant) ?
- Quels **plafonds** (par opération, par heure, éventuellement adaptatifs) et quelle **fenêtre de
  quarantaine**, et quel impact sur les utilisateurs légitimes ?
- Comment **calculer et présenter la perte maximale bornée**, et sous quelles **hypothèses**
  (plafonds appliqués on-chain, clés d'administration non compromises) ?
- **Qui peut geler, qui peut lever un gel**, et comment (multisig, rôles, veto asymétrique) ?
- Faut-il construire la **balise de risque** et le **faux marché de prêt** (volet 3), ou rester
  sur le **contrat seul** si le temps manque ?
- **Combien de surveillants** et de quels types (règles, ML, signaux de transferts) ?
- Faut-il tenter la **prédiction conforme** pour borner les faux positifs, ou rester sur des
  **seuils simples** ?
- **Ordre de priorité si le temps manque** (proposition : volet 1, puis volet 2, puis volet 3).

## 1. Détection du mint anormal

- Quels **invariants** doit respecter le système de mint (ex : tokens émis ≤ f(collatéral)) ?
- Quels **seuils** déclenchent une anomalie de mint (absolus, relatifs, fenêtre temporelle) ?
- Comment distinguer un mint légitime important d'un mint malveillant ?

## 2. Signaux de transferts anormaux

- Quels **signaux** retenir : gros montant vers adresse neuve, découpage (structuring), vitesse de
  sortie, concentration vers des points de sortie (échanges) ?
- Comment pondérer/combiner ces signaux (règles, score, modèle `scikit-learn`) ?
- Qu'est-ce qu'une « adresse neuve » et un « point de sortie » dans notre modèle ?

## 3. Réponse graduée — automatique vs validation humaine

- Quels cas déclenchent un **blocage automatique** (pause réversible) ?
- Quels cas exigent une **validation humaine** avant action ?
- Comment garantir la **réversibilité** de la pause ? Qui a le droit de valider/relâcher ?

## 4. Angle différenciant (à choisir)

- Lien **incident / prestataire tiers critique** au sens **DORA** ?
- **Protection des protocoles en aval** (effet de contagion) ?
- **Supervision de l'agent de réponse** (garde-fou sur l'IA qui décide) ?
- Autre angle proposé par l'équipe ?

## 5. Mesure de performance

- Comment mesurer le **délai de détection** (de l'événement on-chain à l'alerte) ?
- Comment mesurer le **taux de faux positifs** (et sur quel jeu de données) ?
- Quelle **baseline** et quels critères de succès pour la démo ?

## 6. Données synthétiques (voir `data/README.md`)

- Format des fichiers (CSV / JSON / JSONL ?) et schéma des lignes.
- Paramètres précis des scénarios **A** (mint détecté) et **B** (transferts détectés).
- Outil de génération et commande de lancement.

## 7. Interfaces entre modules (voir `docs/CONTRACTS.md`)

- Champs de `MintEvent`, `TransferEvent`, `Alert`, `ResponseAction`, `AuditLogEntry`.
- Où vivent les modèles (`shared/`), format d'échange (JSON ?), versionnage éventuel.
