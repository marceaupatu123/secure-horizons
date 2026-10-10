# docs-site — documentation grand public (Mintlify)

Doc « jolie » et pédagogique du projet, pensée pour des **novices en crypto**. Elle explique ce
que fait Secure Horizons et comment il marche, avec des analogies.

> À ne pas confondre avec le dossier `docs/` (racine), qui est la doc **technique d'équipe**
> (TEAM, ROADMAP, CONTRACTS, etc.).

## Lancer la doc en local

Mintlify utilise Node.js (pas Python). Depuis ce dossier :

```bash
npm i -g mintlify     # une seule fois
mintlify dev          # ouvre la doc sur http://localhost:3000
```

La config est dans `docs.json` ; chaque page est un fichier `.mdx`.

## Contenu

| Page | Sujet |
|------|-------|
| `index.mdx` | Vue d'ensemble + l'analogie de la banque. |
| `le-probleme.mdx` | Pourquoi une clé volée est dangereuse. |
| `lidee-cle.mdx` | « La sécurité vit dans le contrat ». |
| `les-trois-volets.mdx` | Montant verrouillé, perte plafonnée, mur anti-contagion. |
| `les-garde-fous.mdx` | Quarantaine Token Ghost + surveillants + DORA. |
| `le-parcours-dune-attaque.mdx` | Un voleur suivi étape par étape (diagramme). |
| `qui-fait-quoi.mdx` | Les modules du projet et comment ils s'emboîtent. |
| `glossaire.mdx` | Tous les termes crypto expliqués en une ligne. |

## Carte mentale

Une carte mentale rapide est disponible dans `mindmap.mmd` (format Mermaid). Elle se visualise sur
<https://mermaid.live> ou dans n'importe quel éditeur qui rend Mermaid.
