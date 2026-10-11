# GHOST_MARKET_SEIZURE.md — marché du Ghost (décote de rapidité + commission) et séquestre / saisie

> **Statut : PROPOSITION — à valider en équipe.** Ce document introduit une orientation produit
> et une mécanique de sécurité qui **étendent et, sur un point, contredisent** des décisions déjà
> actées dans `docs/OPEN_ANSWERS.md` (voir §5 « Frictions avec le code acté »). Rien ici n'est
> tranché tant que l'équipe ne l'a pas marqué **DÉCISION** et recopié dans `OPEN_ANSWERS.md`.
> Données **fictives** uniquement.
>
> Référence d'implémentation : `data/ghost_ledger.py` (registre hors chaîne). **Ce n'est pas le
> contrat** (#7, #8) : c'est le point de comparaison chiffré, à aligner sur le contrat Ghost quand
> il existera.

---

## 1. Le récit mis en avant au jury : le Ghost est un **jeton de rapidité**

Aujourd'hui (`OPEN_ANSWERS.md` §0bis), un Ghost se convertit **1:1** en vrai token après la
fenêtre de quarantaine (ex. 10 min) sans anomalie. Cette proposition **ne change pas** ce 1:1 pour
qui attend la fin de la fenêtre. Elle ajoute un **marché secondaire** pour qui ne veut pas
attendre :

- **Le vendeur paie la rapidité.** Celui qui veut sortir avant la fin de la fenêtre vend son Ghost
  sur le marché secondaire avec une **décote** (il reçoit moins que la valeur faciale). Il
  échange « 1 token dans 10 min » contre « un peu moins de token tout de suite ».
- **L'acheteur achète moins cher car il assume le risque.** Il reçoit un Ghost encore non vérifié ;
  si la fraude est confirmée pendant la fenêtre, **son Ghost est détruit** et il perd sa mise.
  La décote est le **prix de ce risque**.
- **Le protocole prélève une commission** sur chaque transaction de Ghost sur le marché secondaire.

C'est l'incarnation marchande du cœur acté en §0 : « on ne bloque pas la fraude on/off, on la
**rend visible et chiffrée**, et on laisse le marché réagir à ce prix ». La décote **est** le prix
du risque, fixé par le marché plutôt que décrété.

### 1.1 Décote et commission — définitions

- **Valeur faciale** `V` : le montant de vrai token qu'un Ghost vaudra à conversion (1:1).
- **Prix de marché** `P ≤ V` : ce que l'acheteur paie réellement. `décote = V − P` (en valeur, ou
  `(V − P) / V` en %). Fixé par l'offre/la demande, **pas** par le contrat.
- **Commission protocole** `c` : une fraction prélevée **sur le montant échangé** `P` (jamais
  mintée — invariant de solvabilité, §3). Deux variantes à trancher (§5).

### 1.2 Invariant de solvabilité à préserver

La commission et la décote **ne doivent jamais créer de vrai token non adossé**. Règle dure :
> toute commission est prélevée en **valeur déjà existante** (part de `P`), par transfert interne ;
> aucune conversion Ghost→token au-delà des tranches échues et non suspectes n'est autorisée.

Ainsi `supply_real ≤ collateral` (affirmation **principale** du jury, §0bis-a) reste vrai.

---

## 2. La mécanique de sécurité : **séquestre à la source + saisie (clawback)**

Problème à résoudre (demande produit) : pouvoir **geler**, dès l'émission, la **vraie valeur**
derrière un Ghost non vérifié, et la **saisir** si la fraude est confirmée — **avant** que le
fraudeur n'en fasse quoi que ce soit — pour la restituer aux autorités.

### 2.1 Définitions

- **Séquestre (*escrow*)** : vraie valeur (collatéral / vrai token) **bloquée** par le contrat,
  rattachée à l'identifiant d'un Ghost, que l'émetteur **ne peut pas récupérer** tant que le Ghost
  n'est pas vérifié (fenêtre écoulée sans anomalie confirmée).
- **Saisie / clawback** : reprise de force de la valeur séquestrée, **autorisée uniquement par le
  multisig humain** (`OPEN_ANSWERS.md` §3) — jamais une clé seule. Destination : l'**adresse de
  restitution** (« coffre autorités »), adresse connue, auditée, consignée au journal DORA.
- **Premier émetteur de la chaîne** : voir §3 (décision actée) — **la première adresse à avoir
  déclenché une alerte lors de son achat de Ghost**. C'est le point d'ancrage du séquestre et de
  la saisie.

### 2.2 Cycle de vie de la valeur

```
   émission du Ghost
        │  collatéral placé en SÉQUESTRE (lié à l'ancre, pas rendu à l'émetteur)
        ▼
   fenêtre de quarantaine (le Ghost circule / se vend sur le marché 2ndaire)
        │
        ├── pas d'anomalie à l'échéance ───────────► SÉQUESTRE LIBÉRÉ
        │                                            conversion 1:1 des porteurs
        │
        └── fraude confirmée (multisig) ───────────► SAISIE (clawback)
                                                     • Ghost frauduleux non convertis : DÉTRUITS
                                                     • séquestre : transféré vers l'ADRESSE AUTORITÉS
                                                     • la valeur n'a jamais quitté le séquestre
                                                       → le fraudeur n'a rien pu en faire
```

### 2.3 Pourquoi ça répond à la demande

| Exigence | Réponse |
|---|---|
| Geler l'argent du premier émetteur | Collatéral en **séquestre** dès l'émission ; non récupérable avant vérification. |
| Avant que le fraudeur agisse | La valeur ne quitte jamais le séquestre pendant la fenêtre : rien à déplacer pour lui. |
| Saisir si fraude confirmée | **clawback** multisig : destruction des Ghost + séquestre → adresse autorités. |
| Rendre aux autorités | Adresse de restitution connue, auditée, journalisée (DORA). |
| Ne pas punir les honnêtes | Pas d'anomalie = libération normale + 1:1. Friction = immobilisation du collatéral pendant la fenêtre (à **mesurer**). |

---

## 3. Décisions actées par l'équipe (ce document) — à recopier en `OPEN_ANSWERS.md` après validation

> Précisions données par EnzoFB06 le 2026-10-11. Marquées **PROPOSITION** tant que l'équipe
> entière ne les a pas validées.

### D1 — Sort du collatéral d'un Ghost détruit

- **Le dernier acheteur du Ghost perd tout.** Il assumait le risque en achetant un Ghost non
  vérifié sur le marché secondaire (c'est le prix de la rapidité qu'il a acquise à décote). Son
  Ghost détruit n'ouvre droit à aucune restitution.
- **Le fraudeur restitue aux autorités** la vraie valeur qu'il détient : le **séquestre** attaché
  à l'ancre frauduleuse est saisi et transféré à l'**adresse de restitution**.
- Conséquence : la perte est **transférée au marché** (acheteurs de Ghost), et la **vraie valeur**
  (collatéral séquestré) est **récupérée pour les autorités**, pas pour le protocole.

### D2 — Définition du « premier émetteur » de la chaîne

- **Le premier émetteur = la première adresse ayant déclenché une alerte lors de son achat de
  Ghost.** C'est elle qui ancre le séquestre et que vise la saisie. Les maillons en aval (qui ont
  acheté après, sans déclencher d'alerte) relèvent de D1 (dernier acheteur = perte).

### D3 — Marché de la rapidité + commission

- Le Ghost est **revendable avant échéance avec décote** (prix du risque, fixé par le marché).
- Le protocole prélève une **commission sur les transactions de Ghost**.
- **Reste à trancher (§5)** : commission forfaitaire vs indexée sur le ratio de contamination, et
  **affectation** des montants collectés (bénéfice protocole vs fonds d'assurance des acheteurs).

---

## 4. Chemin d'implémentation (hors chaîne, `data/ghost_ledger.py`)

L'implémentation de référence vit dans le registre hors chaîne (modifiable sans toucher aux
contrats Solidity ni à `shared/`). Elle ajoute :

- un **séquestre** par ancre : `collateral` cantonné et non libérable par l'émetteur ;
- une **ancre d'alerte** (`alert_anchor`) = première adresse ayant déclenché une alerte ;
- une **vente de marché** `market_sell(seller, buyer, amount, price, at)` qui déplace le Ghost
  avec décote et prélève une **commission** (en valeur existante) ;
- une **saisie** `seize(anchor, authorities, at, decision_id)` : détruit les Ghost frauduleux non
  convertis chez les porteurs **en aval** et transfère le séquestre de l'ancre vers l'adresse
  autorités ;
- la préservation des invariants existants (`reserve`, `deficit`, conservation du soupçon).

Les tests chiffrent : valeur saisie, perte du dernier acheteur, commission encaissée, et
solvabilité (`supply_real ≤ collateral`) à chaque étape.

---

## 5. Frictions avec le code acté (à arbitrer AVANT de figer)

1. **Commission « bénéfice » vs §0.** `OPEN_ANSWERS.md` §0 dit qu'une marge sur conversion « entre
   en tension avec l'esprit DORA (protéger l'écosystème, **pas en tirer une rente**) » et
   recommande d'affecter les montants collectés à un **fonds d'assurance**. La variante « bénéfice
   protocole » **contredit** cette recommandation. À trancher explicitement (produit + éthique du
   track « Fintech Security »). Piste de compromis : commission → fonds d'assurance des acheteurs
   de Ghost détruits, part de bénéfice résiduelle **bornée** une fois le fonds abondé.
2. **Conversion 1:1 vs décote.** §0bis acte « converti 1:1 ». La décote ne s'applique qu'à la
   **revente anticipée** sur le marché secondaire ; le 1:1 reste vrai à l'échéance. À écrire
   clairement pour ne pas laisser croire que la conversion elle-même est décotée.
3. **Séquestre vs nature du Ghost.** Si le collatéral est bloqué à la source, le Ghost devient de
   fait une **créance** sur le séquestre (ticket « 1 token à l'échéance, sauf saisie »). Cela
   clarifie la décote (= prix du risque de saisie) mais change la nature de l'objet échangé.
   Décision de design.
4. **Lignage obligatoire (#85).** La saisie à la source exige le **lignage d'origine** du Ghost
   (piste a/b de #85, `data/late_marking.py`). Sans lui, impossible de rattacher un Ghost aval à
   son ancre. Cette proposition rend le lignage **indispensable**, plus seulement souhaitable.
5. **Qui porte réellement la perte (D1) vs §10bis.** D1 (« dernier acheteur perd tout ») doit être
   confronté à `OPEN_ANSWERS.md` §10bis (qui porte le risque : M' protégé / pur / chèque). Vérifier
   la cohérence avant de figer.

---

## 6. Reste ouvert

- Barème de la commission (forfaitaire vs indexée ratio) et affectation (bénéfice vs fonds).
- Mécanisme de prix du marché secondaire (ordre book fictif, AMM, OTC) — pour la démo, OTC suffit.
- Formalisation on-chain du séquestre et de la saisie (contrat Ghost #8).
- Mesure de la friction (collatéral immobilisé pendant la fenêtre) sur le trafic synthétique.
