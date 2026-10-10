# Déploiements — Avalanche Fuji (testnet)

> Registre des adresses de contrats déployés. **Consigne staff** : enregistrer dans le repo les
> adresses de contrats déployés.
>
> **Testnet uniquement.** Les AVAX de Fuji sont des jetons de test sans valeur. Jamais de vraie
> clé privée ni de wallet contenant de vrais fonds — compte de test dédié uniquement (voir
> règles d'équipe dans `CLAUDE.md` / steering `collaboration`).

## Réseau Avalanche Fuji C-Chain

| Paramètre         | Valeur                                             |
| ----------------- | -------------------------------------------------- |
| Nom du réseau     | Avalanche Fuji C-Chain                             |
| Chain ID          | `43113`                                            |
| Symbole           | AVAX                                               |
| RPC URL (publique)| `https://api.avax-test.network/ext/bc/C/rpc`       |
| Block explorer    | https://testnet.snowtrace.io                       |
| Faucet            | https://build.avax.network/console/primary-network/faucet |

> Le mail du staff listait `https://chainlist.org/chain/43113` comme « RPC URL » : c'est la page
> d'infos Chainlist, pas une RPC. La vraie RPC publique est celle du tableau ci-dessus. Chainlist
> peut servir à ajouter le réseau au wallet en un clic.
>
> Besoin de plus d'AVAX de test ? Envoyer l'adresse EVM (`0x…`) du **wallet dédié** à Yassir
> (yassirboudda@gmail.com). Ne jamais envoyer de clé privée ni de seed phrase.

## Contrats déployés

À remplir à chaque déploiement. Une ligne par contrat (ou par redéploiement).

| Contrat | Adresse (`0x…`) | Chain | Tx hash de déploiement | Snowtrace | Commit / tag | Déployé par | Date |
| ------- | --------------- | ----- | ---------------------- | --------- | ------------ | ----------- | ---- |
| _ex: GhostToken_ | `0x…` | Fuji (43113) | `0x…` | [lien](https://testnet.snowtrace.io/address/0x…) | `abc1234` | _@pseudo_ | AAAA-MM-JJ |

### Modèle de ligne à copier

```
| <Contrat> | `0x…` | Fuji (43113) | `0x…` | [lien](https://testnet.snowtrace.io/address/<adresse>) | `<commit>` | @<pseudo> | AAAA-MM-JJ |
```

## Rappels

- Vérifier le contrat sur Snowtrace après déploiement quand c'est possible (facilite la démo).
- Lier chaque déploiement à un commit/tag précis pour pouvoir reproduire le build.
- `out/`, `cache/`, `broadcast/` restent gitignorés : ne pas committer d'artefacts ni de clés.
