# Defense sheet — Équipe 20, Crypto-Secure

**Track 1 — Fintech Security : Guardians of Value** · axe 4 (détection et réponse à incident DeFi / DORA)

> Toutes les données sont **fictives** (trafic synthétique, chaîne anvil locale, tests Foundry).
> Chaque chiffre renvoie à la commande qui le produit dans `docs/CLAIMS.md`. On dit « vérifié
> par tests », jamais « prouvé ».

## 1. Scénario de menace

Inspiré du hack Resolv : l'attaquant détient une **clé de service valide** et signe lui-même ses
autorisations de mint (référence réelle : ~200 000 USDC déposés, 80 M mintés, dépeg en 17 min).
Réagir après coup arrive trop tard. Deux variantes traitées :

- **A** — la clé volée tente de gonfler le montant du mint.
- **B** — l'attaquant reste sous les plafonds (mints 1:1) puis sort par des transferts concentrés.

## 2. Fonctions NIST CSF 2.0 couvertes

| Fonction | Ce qu'on fait |
|----------|---------------|
| **Protect** | Le contrat dérive le montant du dépôt on-chain : la signature autorise « traiter la demande n°X », pas un montant. Tout transfert passe par un Token Ghost converti 1:1 après une fenêtre sans anomalie. |
| **Detect** | Surveillants à règles sur les mints (invariants) et les transferts (volume élevé ET dispersion effondrée). |
| **Respond** | Réponse graduée : retard local auto-expirant (automatique), destruction du Ghost suspect (multisig 2/3), pause globale (multisig 3/3). Balise de risque lue par les protocoles en aval. |
| **Recover** | Transfert suspect annulable tant que son Ghost n'est pas converti ; journal d'audit et rapport d'incident pré-rempli. |
| **Govern** | L'IA ne fait que retarder ; destruction et pause globale restent des décisions humaines tracées. |

## 3. Techniques et risques adressés _(mapping proposé, à valider en équipe)_

- **MITRE ATT&CK** : T1552.004 (clés privées non protégées), T1078 (comptes valides), T1657 (vol financier).
- **OWASP Smart Contract Top 10** : défaut de contrôle d'accès (le signataire choisit le montant).
- **OWASP Top 10 LLM** : agentivité excessive — traitée en limitant l'IA à une action réversible et auto-expirante.

## 4. Métriques mesurées

| Métrique | Valeur | Source |
|----------|--------|--------|
| Perte protocole, clé de service volée (A) | **0** sur le contrat protégé ; ×1000 le dépôt sur le vulnérable | `dashboard.demo run A`, tests d'invariants Foundry |
| Détection des mints d'attaque (A vulnérable) | **2 alertes sur 2** | `data.calibrate`, seed 42 |
| Délai de détection (B) | **296 s** après le mint d'attaque, fenêtre Ghost de 10 min | `dashboard.demo run B`, seed 20 |
| Faux positifs, trafic normal | **0 sur 864 tranches** de 5 min (profil petits transferts) ; 5 à z = 2 puis 0 à partir de z volume = 6 (profil gros transferts) | `data.calibrate`, seed 42 |
| Offre touchée par la réponse (B) | **1,4 % à 1,7 %** en fenêtre allongée au pic | `dashboard.demo run B`, seeds 7, 20, 42 |
| Coût d'un faux positif (N3) | **8,1 % à 8,5 %** de l'offre retardée, retour seul à la normale, 0 destruction | `dashboard.demo run N3` |
| Friction permanente du Ghost | **3,2 %** de l'offre immobilisée en médiane (p95 5,7 %) | `data.calibrate`, W = 10 min |
| Contagion aval (C) | Mauvaise créance **76 000 mUSDC sans balise, 0 avec** | test Foundry `RiskBeacon.t.sol` |

Délai de **réponse** : le retard est posé par l'orchestrateur dès l'alerte ; il n'est pas mesuré séparément.

## 5. Limites connues

- Hypothèse : **clés d'administration non compromises** ; la borne porte sur la clé de service.
- Si la détection est plus lente que la fenêtre Ghost, tout est converti : la marge est bornée par la tranche d'agrégation de 5 min.
- Trafic synthétique, une seule graine pour la calibration ; le taux de faux positifs dépend du profil de trafic légitime, non tranché.
- Aucun contrat déployé sur Fuji : rejeux sur simulation et chaîne locale ; latence RPC réelle non mesurée.
- Multisig **simulé** ; seuils et durées sont des valeurs de départ, pas actées.
- La perte n'est pas effacée : elle est reportée sur les acheteurs de Ghost (tension assumée avec l'esprit DORA).
- Fuzzing = exploration (256 exécutions par défaut), pas une preuve formelle.
