# contracts

- **Rôle** : smart contracts Solidity (**Foundry**), cible **Avalanche Fuji** (testnet).
- **Propriétaire** : @denybs (voir `docs/TEAM.md`).
- **Lancer** : installer Foundry (ci-dessous), puis `forge build` / `forge test` depuis `contracts/`.

> Le projet Foundry n'est **pas encore initialisé** (`forge` n'était pas installé au moment du
> setup). Le propriétaire du module initialise Foundry après installation (voir plus bas).

## À produire plus tard — _proposé, à valider en équipe_

Aucun code n'est écrit pour l'instant. Éléments envisagés (orientation « sécurité dans le
contrat ») :

- **Contrat « vulnérable »** : accepte tout montant tant que la signature est valide (reproduit le
  schéma d'attaque à des fins de démo).
- **Contrat « protégé »** : le montant est **dérivé on-chain** du dépôt (la signature autorise
  seulement « traiter la demande n°X ») + les garde-fous retenus (plafonds, quarantaine, multisig,
  séparation des clés) — **volet 1**.
- **Tests d'invariants / fuzzing** cherchant à dépasser la **perte maximale bornée** — **volet 2**.
  À formuler comme « vérifié par tests d'invariants », jamais « prouvé ».
- **Balise de risque** + **faux marché de prêt** (simulé, fictif) qui cesse d'accepter le token
  gelé comme garantie — **volet 3, optionnel**.
- **Contrat ERC20 « Token Ghost »** (quarantaine liquide) : token temporaire **librement
  échangeable**, convertible 1:1 contre le vrai token après délai sans anomalie, avec une
  **fonction de destruction réservée au guardian** pour annuler les ghosts d'un lot suspect en cas
  de gel confirmé — _proposé, à valider_.

Détails et arbitrages ouverts : voir `docs/OPEN_QUESTIONS.md` et `docs/CLAIMS.md`.

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
