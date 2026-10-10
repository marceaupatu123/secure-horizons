# contracts

- **Rôle** : smart contracts Solidity (**Foundry**), cible **Avalanche Fuji** (testnet).
- **Propriétaire** : _(à renseigner — voir `docs/TEAM.md`)_
- **Lancer** : installer Foundry (ci-dessous), puis `forge build` / `forge test` depuis `contracts/`.

> Le projet Foundry n'est **pas encore initialisé** (`forge` n'était pas installé au moment du
> setup). Le propriétaire du module initialise Foundry après installation.

## Installer Foundry (Windows)

Foundry s'installe principalement via `foundryup`, pensé pour un shell Unix. Sous Windows :

**Option A — WSL (recommandé)** dans un terminal Ubuntu/WSL :

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

**Option B — Git Bash** : même commande que ci-dessus, depuis Git Bash.

Vérifier l'installation :

```bash
forge --version
```

Doc officielle : https://book.getfoundry.sh/getting-started/installation

## Initialiser le projet Foundry (après installation)

Depuis le dossier `contracts/` :

```bash
forge init --no-git .        # --no-git : le repo git existe deja a la racine
forge build
forge test
```

`forge init` crée `foundry.toml`, `src/`, `test/` et un contrat d'exemple. Pense à configurer la
cible Fuji (RPC + chain id) dans `foundry.toml` et à utiliser un **compte de test** uniquement.

> Rappel sécurité : `out/`, `cache/` et `broadcast/` sont déjà ignorés par `.gitignore`. Jamais
> de vraie clé privée — comptes de test Fuji seulement.
