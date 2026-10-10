# contracts

- **Rôle** : smart contracts Solidity (**Foundry**), cible **Avalanche Fuji** (testnet).
- **Propriétaire** : @denybs (voir `docs/TEAM.md`).
- **Lancer** : installer Foundry et les dépendances (ci-dessous), puis `forge build` /
  `forge test` depuis `contracts/`.

> Données **fictives** uniquement (collatéral `MockUSDC`, stables « (fictif) »). Jamais de vraie
> clé privée : les tests utilisent des adresses `makeAddr(...)`, sans clé.

## Contenu

```
contracts/
├── foundry.toml            # solc 0.8.33, evm cancun, profils default / deep
├── .gitignore              # lib/ (dépendances installées localement), .plan/
├── DEPLOYMENTS.md          # adresses déployées sur Fuji (aucune pour l'instant)
├── src/
│   ├── MockUSDC.sol        # collatéral FICTIF, 6 décimales, faucet ouvert
│   ├── StableToken.sol     # stable FICTIF, 18 décimales, mint réservé au minter (immuable)
│   └── VulnerableMinter.sol# VOLONTAIREMENT vulnérable (démo de l'attaque)
└── test/
    ├── utils/BaseTest.sol
    ├── Tokens.t.sol
    └── VulnerableMinter.t.sol
```

## Installer Foundry (Windows)

Foundry s'installe principalement via `foundryup`, pensé pour un shell Unix. Sous Windows :

**Option A — WSL (recommandé)** dans un terminal Ubuntu/WSL :

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

**Option B — Git Bash** : même commande que ci-dessus, depuis Git Bash.

**Option C — zip officiel** : télécharger `foundry_stable_win32_amd64.zip` depuis les releases
<https://github.com/foundry-rs/foundry/releases> et extraire `forge.exe` (par ex. dans
`%USERPROFILE%\.foundry\bin`).

Vérifier l'installation :

```bash
forge --version
```

Si `forge` n'est pas dans le `PATH` (PowerShell) : appeler le binaire directement,
`& "$env:USERPROFILE\.foundry\bin\forge.exe" test`.

Doc officielle : https://book.getfoundry.sh/getting-started/installation

## Dépendances (une commande, tags figés)

Choix : **`lib/` n'est pas versionné** (gitignoré) ; chacun installe les dépendances à des tags
figés avec `--no-git` (pas de sous-module git, pas de `.gitmodules`). Raison : OpenZeppelin
complet représente des centaines de fichiers, illisibles en revue de PR si on les vendore.

Depuis `contracts/` :

```bash
forge install --no-git foundry-rs/forge-std@v1.17.0 OpenZeppelin/openzeppelin-contracts@v5.4.0
```

- `forge-std` **v1.17.0**, `openzeppelin-contracts` **v5.4.0** (remappings dans `foundry.toml`).
- **Toujours `--no-git`** : sans cette option, `forge install` ajoute des sous-modules git à la
  racine du dépôt — à éviter.
- Repli si `forge install` échoue (réseau, proxy) : télécharger
  `https://github.com/foundry-rs/forge-std/archive/refs/tags/v1.17.0.zip` et
  `https://github.com/OpenZeppelin/openzeppelin-contracts/archive/refs/tags/v5.4.0.zip`, puis
  extraire leur contenu dans `contracts/lib/forge-std/` et
  `contracts/lib/openzeppelin-contracts/` (même arborescence que le dépôt d'origine).

Le projet n'a pas été créé par `forge init` : `foundry.toml` est écrit à la main (équivalent),
ce qui évite le contrat d'exemple `Counter` et l'écrasement de ce README.

## Compiler et tester

```bash
forge build
forge test -vv
```

> Rappel : `out/`, `cache/` et `broadcast/` sont ignorés par le `.gitignore` racine.

## Contrat vulnérable (`VulnerableMinter`) — démo uniquement

**Volontairement vulnérable, à ne jamais déployer comme « vrai » contrat.** Il reproduit le
schéma Resolv :

1. un utilisateur appelle `requestSwap(depositAmount)` : le collatéral est prélevé et la demande
   enregistrée ;
2. un compte `SERVICE_ROLE` appelle `completeSwap(requestId, recipient, mintAmount)` : le contrat
   vérifie le rôle et que la demande est en attente, mais **mint le montant choisi vers le
   destinataire choisi**, sans lien avec le dépôt.

Une clé de service volée transforme donc un petit dépôt réel en mint arbitraire.
Tests : `test/VulnerableMinter.t.sol` (`test_attack_smallDepositHugeMint`,
`test_attack_mintToArbitraryRecipient`, `testFuzz_vulnerable_mintsAnyAmount`). Les montants
utilisés (200 000 USDC déposés, 80 M de stables mintés) sont des **fixtures** reprenant l'ordre
de grandeur de l'incident cité dans `docs/OPEN_ANSWERS.md` §1, pas des mesures.

```bash
forge test --match-contract VulnerableMinterTest -vv
```

## À produire plus tard — _proposé, à valider en équipe_

- **Contrat « protégé »** : le montant est **dérivé on-chain** du dépôt (la clé de service
  autorise seulement « traiter la demande n°X ») + les garde-fous retenus (multisig, séparation
  des clés ; pas de plafond fixe, `docs/OPEN_ANSWERS.md` §0) — **volet 1**.
- **Tests d'invariants / fuzzing** cherchant à dépasser la **perte maximale bornée** — **volet 2**.
  À formuler comme « vérifié par tests d'invariants », jamais « prouvé ».
- **Balise de risque** + **faux marché de prêt** (simulé, fictif) qui cesse d'accepter le token
  gelé comme garantie — **volet 3, optionnel**.
- **Contrat ERC20 « Token Ghost »** (quarantaine liquide) : token temporaire **librement
  échangeable**, convertible 1:1 contre le vrai token après délai sans anomalie, avec une
  **fonction de destruction réservée au guardian** pour annuler les ghosts d'un lot suspect en cas
  de gel confirmé — _proposé, à valider_.

Détails et arbitrages ouverts : voir `docs/OPEN_QUESTIONS.md` et `docs/CLAIMS.md`.
