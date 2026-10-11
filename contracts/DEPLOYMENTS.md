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
| MockUSDC (démo #148) | `0x2114a5D319c084b53f3089A222C4552089058cF0` | Fuji (43113) | voir `dashboard/fuji_runs/latest.json` | [lien](https://testnet.snowtrace.io/address/0x2114a5D319c084b53f3089A222C4552089058cF0) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| VulnerableMinter (démo #148, cas 1) | `0x42c88620e131DD37A3196A2dC82F1238b8Ac3020` | Fuji (43113) | voir `latest.json` | [lien](https://testnet.snowtrace.io/address/0x42c88620e131DD37A3196A2dC82F1238b8Ac3020) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| ProtectedMinter (démo #148, cas 3) | `0x41887ce9E04c3894242044668cFC5c7ADd116E7a` | Fuji (43113) | voir `latest.json` | [lien](https://testnet.snowtrace.io/address/0x41887ce9E04c3894242044668cFC5c7ADd116E7a) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| GhostToken (démo #148, cas 3) | `0xd240Afa51ee09d22589c0f94df60Cd7d27699115` | Fuji (43113) | voir `latest.json` | [lien](https://testnet.snowtrace.io/address/0xd240Afa51ee09d22589c0f94df60Cd7d27699115) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| SettlementRouter (démo #148, cas 3) | `0x67444206749EAf926D4c0A8AC8d49362D0Ea095c` | Fuji (43113) | voir `latest.json` | [lien](https://testnet.snowtrace.io/address/0x67444206749EAf926D4c0A8AC8d49362D0Ea095c) | `04d0bee` | @marceaupatu123 | 2026-10-11 |
| AssetVault + AssetGhost (démo #148, cas 3) | `0xAf5a5afbd334725c99fC533976fC4758e7F52a32` / `0x00E3833e9a9545A492DfF6E7bCE4328F2f942438` | Fuji (43113) | voir `latest.json` | [coffre](https://testnet.snowtrace.io/address/0xAf5a5afbd334725c99fC533976fC4758e7F52a32) | `04d0bee` | @marceaupatu123 | 2026-10-11 |

> Les lignes « démo #148 » sont déployées par `python -m dashboard.scenarios.fuji_live` (3 cas :
> mint accepté / mint bloqué / vendeur de Ghost ; toutes les transactions et adresses exactes dans
> `dashboard/fuji_runs/latest.json`, source de vérité). Un nouveau rejeu redéploie des contrats
> neufs ; `latest.json` est alors mis à jour automatiquement (ces lignes sont indicatives).

### Modèle de ligne à copier

```
| <Contrat> | `0x…` | Fuji (43113) | `0x…` | [lien](https://testnet.snowtrace.io/address/<adresse>) | `<commit>` | @<pseudo> | AAAA-MM-JJ |
```

## Rappels

- Vérifier le contrat sur Snowtrace après déploiement quand c'est possible (facilite la démo).
- Lier chaque déploiement à un commit/tag précis pour pouvoir reproduire le build.
- `out/`, `cache/`, `broadcast/` restent gitignorés : ne pas committer d'artefacts ni de clés.
