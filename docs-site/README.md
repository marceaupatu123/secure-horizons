# docs-site — documentation novice illustrée (Mintlify)

Doc pédagogique **de A à Z** de Secure Horizons, pour des **novices en crypto et en dev** :
analogies, schémas Mermaid, exemples chiffrés fictifs (Alice, Bob, Mallory, Spéculos), extraits
de code commentés ligne à ligne et tutoriels pas à pas.

> À ne pas confondre avec `docs/` (racine), la doc **technique d'équipe** (décisions, interfaces,
> roadmap). En cas de divergence, **`docs/` fait foi** : cette doc la vulgarise, elle ne tranche
> rien.

## Lancer la doc en local

Mintlify utilise Node.js (pas Python). Depuis ce dossier :

```bash
npm i -g mintlify     # une seule fois
mintlify dev          # ouvre la doc sur http://localhost:3000
```

La navigation est dans `docs.json` ; chaque page est un fichier `.mdx` (slug = chemin sans
`.mdx`).

## Contenu (3 onglets)

### Comprendre le projet

| Page | Sujet |
|------|-------|
| `index.mdx` | Accueil : le projet en 30 s / 5 min, personnages, parcours selon ton profil. |
| `bases-blockchain.mdx` | La blockchain en 10 minutes (bloc, transaction, clé, gas, ERC20, Fuji…). |
| `le-probleme.mdx` | Clé de service volée, le hack Resolv pas à pas, la faille reproduite. |
| `lidee-cle.mdx` | « La sécurité vit dans le contrat » + décision §0 « pricer le risque ». |
| `les-trois-volets.mdx` | Montant dérivé on-chain, perte et friction bornées, pare-feu de contagion. |
| `token-ghost.mdx` | Quarantaine liquide sur tous les transferts, tranches, restitution, swap-id. |
| `contamination-par-ratio.mdx` | Le ratio comme prix du risque, propagation, racine de Merkle. |
| `balise-de-risque.mdx` | La balise de risque publiée et lue par l'aval (#7). |
| `recuperer-apres-coup.mdx` | Lignage rétroactif : récupérer après coup (#106). |
| `les-garde-fous.mdx` | Surveillants, 3 verbes (retarder / détruire / pause), multisig, DORA. |
| `le-parcours-dune-attaque.mdx` | Scénarios A, B, C, D et contrôles suivis pas à pas. |
| `decisions.mdx` | Ce qui est acté (OPEN_ANSWERS) vs ouvert (OPEN_QUESTIONS). |
| `promesses-jury.mdx` | Ce qu'on affirme au jury et comment on le mesure. |
| `glossaire.mdx` | ~95 termes expliqués en une phrase, avec liens. |

### Sous le capot

| Page | Sujet |
|------|-------|
| `qui-fait-quoi.mdx` | Modules, propriétaires, vagues de la roadmap. |
| `modules/architecture.mdx` | Trajet d'une donnée de la chaîne à l'écran, modèles échangés. |
| `modules/shared.mdx` | Modèles Pydantic, config `.env`, limiteur Bedrock. |
| `modules/contracts.mdx` | Contrats Solidity et tests Foundry (unitaires, fuzz, invariants). |
| `modules/data.mdx` | Générateur synthétique JSONL, scénarios, registre Ghost, calibration. |
| `modules/monitor.mdx` | Écoute on-chain des mints et transferts, checkpoint, résilience. |
| `modules/detection.mdx` | Invariants I1…I6, transferts anormaux, pipeline, prédiction conforme. |
| `modules/response.mdx` | Réponse graduée, machine à états, gel/libération, journal d'audit. |
| `modules/llm.mdx` | Bedrock Converse, prompts, rapport d'incident DORA. |
| `modules/dashboard.mdx` | Écran de démo Streamlit et scénarios simulés. |

### Mettre les mains dedans

| Page | Sujet |
|------|-------|
| `pratique/installer.mdx` | Installation pas à pas (Windows d'abord). |
| `pratique/premiere-demo.mdx` | Lancer les démos, sorties réelles commentées. |
| `pratique/tests-expliques.mdx` | pytest et Foundry, lire et écrire un test. |
| `pratique/workflow-equipe.mdx` | Issue → branche → PR → CI → merge → board. |
| `pratique/depannage.mdx` | FAQ et erreurs fréquentes. |

## Règles de rédaction (pour qui modifie cette doc)

- Toute affirmation technique vient d'un fichier du dépôt ; cite la source en fin de section.
- Recopie le **statut exact** des décisions (`docs/OPEN_ANSWERS.md`), sans le renforcer ; ce qui
  n'y est pas reste « à valider en équipe ».
- Jamais « prouvé » (au mieux « vérifié par tests ») ; aucun chiffre non mesuré.
- MDX : pas de `<lettre` ni d'accolades hors code ; composants Mintlify standard uniquement.
- Mermaid : libellés de flowchart entre guillemets ; dans un `sequenceDiagram`, le texte des
  messages **sans** guillemets (sinon ils s'affichent).

## Carte mentale

Une carte mentale du projet est dans `mindmap.mmd` (Mermaid). Elle se visualise sur
<https://mermaid.live> ou dans n'importe quel éditeur qui rend Mermaid.
