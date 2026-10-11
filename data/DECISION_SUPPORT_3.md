# Support de décision #3 — valeurs à acter (PROPOSÉ, à valider en équipe)

> Ce document **ne tranche rien**. Il rassemble les valeurs mesurées par `make calibrate` et
> `python -m data.late_marking` (données FICTIVES, simulation) et propose un point de
> fonctionnement argumenté. L'équipe valide ou ajuste, puis la décision est reportée dans
> `docs/OPEN_ANSWERS.md` §3 par le propriétaire de `docs/`. Chiffres à régénérer avec
> `make calibrate` ; une seule graine (42) pour l'instant.

Issue #3 suit désormais **les valeurs** (les mécanismes sont actés : §0, §9, §3). Tableau de
synthèse, puis le détail.

| Valeur à acter | Mesure | Proposition | Statut |
|---|---|---|---|
| Fenêtre Ghost W normale | friction 3,2 % de l'offre (p95 5,7 %) à 10 min | **10 min** | à valider |
| Tranche d'agrégation de détection | doit être < W ; alerte à la clôture | **5 min** (déjà le défaut) | à valider |
| Seuil de déclenchement `z volume` | 0 FP sur les deux profils à partir de 6 | **6** | à valider, dépend du profil |
| Seuil de déclenchement `z Herfindahl` | 2 à 4 équivalents | **3** | à valider |
| Lignage pour la récupération (#85) | prospectif seul = 0 % récupéré | **lignage d'origine (a) ou rétroactif (b)** | décision §10bis/#85 |

## 1. Fenêtre Ghost W

Friction mesurée sur le trafic normal (part de l'offre immobilisée en Ghost, non convertible) :

| W | 5 min | 10 min | 15 min | 30 min |
|---|---|---|---|---|
| médiane / p95 | 1,6 % / 3,2 % | 3,2 % / 5,7 % | 4,6 % / 7,8 % | 8,7 % / 13,5 % |

**Proposition : W = 10 min.** C'est la valeur de référence de §0bis, et elle immobilise en médiane
3,2 % de l'offre — friction supportable. 5 min réduit la friction mais laisse moins de marge de
détection ; 30 min dépasse 13 % au p95, trop coûteux pour les usages légitimes.

## 2. Seuil de déclenchement du surveillant de transferts

Balayage des z robustes (volume, Herfindahl), 864 tranches de trafic normal, deux profils de
trafic légitime. Faux positifs à zéro :

- profil **petits transferts** (1–10 % du solde) : 0 FP sur toute la grille (z ≥ 2) ;
- profil **gros transferts** (5–50 % du solde) : 0 FP seulement à partir de **`z volume` = 6**
  (quel que soit `z Herfindahl` de 2 à 4).

**Proposition : `z volume` = 6, `z Herfindahl` = 3.** C'est le seul réglage robuste **aux deux
profils** sans perte de détection. Prérequis acté séparément : l'équipe doit d'abord choisir
quel profil de trafic légitime est réaliste (voir §3bis ci-dessous). Si le trafic réel ressemble
aux « petits transferts », un seuil plus bas (z = 3) suffirait et détecterait des attaques plus
petites.

Détection, à ce seuil, sur le scénario B (attaque = part de l'offre) :

- profil gros transferts : plus petite attaque vue avant conversion = **5 % de l'offre** ;
- profil petits transferts : vue dès **0,5 %**.

Marge avant conversion : ~5 min au mieux avec W = 10 min (l'alerte part à la clôture d'une
tranche de 5 min).

## 3. Tranche d'agrégation

**Proposition : 5 min**, contrainte dure de §5 (strictement < W). C'est le défaut du détecteur.
La conséquence est que la marge de détection est bornée par la durée de la tranche : une attaque
étalée sur deux tranches n'est vue qu'à la seconde, presque à l'échéance.

## 3bis. Prérequis non chiffrable : profil de trafic légitime

Le résultat dépend plus du **profil du trafic légitime** que du seuil lui-même. C'est une
hypothèse à poser en équipe (quelle part de son solde un utilisateur déplace typiquement), pas
une valeur que la simulation peut deviner. Tant qu'elle n'est pas posée, le seuil ci-dessus reste
conditionnel.

## 4. Récupération après coup (lie #3 à #85/§10bis)

Mesure de `data/late_marking.py` sur la chaîne des 40 (détection à 3 min, W = 10 min) :

| Piste | M' récupéré |
|---|---|
| prospectif seul (ratio tel quel) | 0 % |
| lignage d'origine / recalcul rétroactif | 100 % (tant que l'alerte précède l'échéance) |

**Conséquence pour #3 :** retenir W et un seuil ne suffit pas pour l'objectif anti-blanchiment ;
il faut aussi une récupération par lignage d'origine (décision §10bis/#85). Sinon, le gel/la
destruction n'atteignent que ce que le voleur détient encore, soit 0 % d'une chaîne déjà revendue.

## 5. Valeurs encore non mesurables (ne pas acter maintenant)

- **Seuils de conversion** (ratio, montant absolu) et **seuil de la balise** : dans les scénarios
  C/D, le soupçon n'est semé qu'à l'alerte, moment où l'adresse est déjà retardée ; le seuil ne
  joue qu'après une levée ou une expiration sans destruction, pas encore simulée.
- **Budget de quarantaine, facteur d'allongement max** : il faut rejouer les alertes dans
  `response/` avec les soldes Ghost ; faisable une fois le seuil de déclenchement choisi.
- **Barème de la marge de conversion** : décision §0, rien à mesurer avant.
