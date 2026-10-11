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
| MockUSDC (démo #148) | `0x4369CF4545C8d66C5aeeF1A71A3cc00f2B5ca06f` | Fuji (43113) | `0xc25ac58243919a884afcdcc561a550e51bef235503c1092fa76488386024a259` | [lien](https://testnet.snowtrace.io/address/0x4369CF4545C8d66C5aeeF1A71A3cc00f2B5ca06f) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| VulnerableMinter (démo #148) | `0xf538aBf585928534f499b0c13290Dac4632d5e18` | Fuji (43113) | `0x9beaee64508889860d25df98d90fca97bf04ff14ce57c6f3bb585677a02f9e8e` | [lien](https://testnet.snowtrace.io/address/0xf538aBf585928534f499b0c13290Dac4632d5e18) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| StableToken du VulnerableMinter (démo #148) | `0x8c7bfEbEB9Ee1edfa294627339Ad29303acAA7B1` | Fuji (43113) | `0x9beaee64508889860d25df98d90fca97bf04ff14ce57c6f3bb585677a02f9e8e` (créé par le minter) | [lien](https://testnet.snowtrace.io/address/0x8c7bfEbEB9Ee1edfa294627339Ad29303acAA7B1) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| ProtectedMinter (démo #148) | `0x95AfF45e8BE8E72Aa43A618A91698171830fBD56` | Fuji (43113) | `0x9712857fdb5a1d6e296ab4e6d18d56284f3bcd7847ba20c61336c350369bfcf3` | [lien](https://testnet.snowtrace.io/address/0x95AfF45e8BE8E72Aa43A618A91698171830fBD56) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| GhostToken du ProtectedMinter (démo #148) | `0xEa199016C51566d017B6D8BA8107f1c9C2CE462c` | Fuji (43113) | `0x9712857fdb5a1d6e296ab4e6d18d56284f3bcd7847ba20c61336c350369bfcf3` (créé par le minter) | [lien](https://testnet.snowtrace.io/address/0xEa199016C51566d017B6D8BA8107f1c9C2CE462c) | `04d0bee` | @marceaupatu123 | 2026-10-11 |

> Les lignes « démo #148 » sont déployées par `python -m dashboard.scenarios.fuji_live` (rejeu du
> schéma Resolv, toutes les transactions dans `dashboard/fuji_runs/latest.json`). Un nouveau rejeu
> redéploie des contrats neufs : mettre ces lignes à jour en même temps que `latest.json`.

### Modèle de ligne à copier

```
| <Contrat> | `0x…` | Fuji (43113) | `0x…` | [lien](https://testnet.snowtrace.io/address/<adresse>) | `<commit>` | @<pseudo> | AAAA-MM-JJ |
```

## Rappels

- Vérifier le contrat sur Snowtrace après déploiement quand c'est possible (facilite la démo).
- Lier chaque déploiement à un commit/tag précis pour pouvoir reproduire le build.
- `out/`, `cache/`, `broadcast/` restent gitignorés : ne pas committer d'artefacts ni de clés.
