"""Parametres du module `detection` — SEUL endroit ou vivent ses reglages.

Tout parametre ci-dessous porte son statut :
- PROVISOIRE — a valider par l'equipe : valeur de travail choisie pour que le
  code tourne, PAS une decision d'equipe ;
- A MESURER : valeur a obtenir sur le trafic synthetique (`docs/CLAIMS.md` :
  aucun chiffre invente). Aucune valeur ici n'est une mesure.

Les taux et tolerances sont des `Fraction` (calcul exact, jamais de `float`
sur des montants). Les montants restent des `int` en base units.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from shared.models import AlertSeverity

# Nom du surveillant reporte dans `Alert.monitor_name` (exemple de
# `docs/CONTRACTS.md` : « rule_mint »).
MINT_MONITOR_NAME = "rule_mint"

# epsilon (I1) — PROVISOIRE — a valider par l'equipe ; valeur reelle A MESURER.
# Source : docs/OPEN_ANSWERS.md §1 (Q1 I1, Q2 « tolerance = epsilon des frais,
# rien d'autre » ; Reste ouvert : « valeurs de epsilon (frais) ... a mesurer »).
# Ecart relatif tolere entre le montant minte et `depot x taux` :
# |minted - depot x taux| <= depot x taux x epsilon. Les frais reels du contrat
# protege (#5) ne sont pas connus : 0,1 % est une valeur de travail, pas une
# mesure.
I1_EPSILON = Fraction(1, 1000)

# delta (ecart d'oracle) — PROVISOIRE — a valider par l'equipe ; valeur reelle
# A MESURER. Source : docs/OPEN_ANSWERS.md §1 (Q2 « ecart du taux / de l'oracle
# au-dela de delta par rapport a une source de reference » ; Reste ouvert :
# « valeurs de ... delta (ecart d'oracle), et choix de la source de reference
# du taux, a mesurer »). Ecart relatif tolere :
# |taux applique - taux de reference| <= taux de reference x delta.
# 1 % est une valeur de travail, pas une mesure.
ORACLE_DELTA = Fraction(1, 100)

# facteur I6 — PROVISOIRE — a valider par l'equipe. Source :
# docs/OPEN_ANSWERS.md §1 (Q1 I6 « totalSupply <= valeur du collateral x
# facteur »). 1 = offre entierement couverte par le collateral (1:1). La valeur
# n'est pas tranchee par l'equipe.
I6_COLLATERAL_FACTOR = Fraction(1)

# tolerance I5 — PROVISOIRE — a valider par l'equipe. Source :
# docs/OPEN_ANSWERS.md §1 (Q1 I5 « Delta totalSupply = Somme Mint - Somme
# Burn »). Identite comptable : 0 base unit d'ecart tolere. A revoir si le
# token a des mecanismes qui modifient l'offre hors Mint/Burn (rebase, ...).
I5_SUPPLY_TOLERANCE = 0

# Gravites par regle — PROVISOIRE — a valider par l'equipe. Source :
# docs/OPEN_ANSWERS.md §1 (Q2 « une violation d'invariant detectee hors chaine
# signifie que le contrat a ete contourne : c'est le cas qui justifie l'audit
# humain ») et §3 (quelle que soit la gravite, le surveillant ne peut que
# RETARDER ; detruire / pause globale = multisig).
INVARIANT_SEVERITY = AlertSeverity.CRITICAL
ADMIN_EVENT_SEVERITY = AlertSeverity.WARNING
ORACLE_DEVIATION_SEVERITY = AlertSeverity.WARNING


@dataclass(frozen=True)
class MintRuleParams:
    """Jeu de parametres du surveillant de mint (defauts = constantes ci-dessus).

    Attributes:
        i1_epsilon: tolerance relative de I1 (PROVISOIRE, A MESURER).
        oracle_delta: ecart relatif tolere vs taux de reference (PROVISOIRE,
            A MESURER).
        i6_collateral_factor: facteur de I6 (PROVISOIRE).
        i5_supply_tolerance: ecart absolu tolere sur I5, base units
            (PROVISOIRE).
        invariant_severity: gravite d'une violation I1/I5/I6 (PROVISOIRE).
        admin_event_severity: gravite d'un evenement admin non annonce
            (PROVISOIRE).
        oracle_deviation_severity: gravite d'un ecart d'oracle (PROVISOIRE).
    """

    i1_epsilon: Fraction = I1_EPSILON
    oracle_delta: Fraction = ORACLE_DELTA
    i6_collateral_factor: Fraction = I6_COLLATERAL_FACTOR
    i5_supply_tolerance: int = I5_SUPPLY_TOLERANCE
    invariant_severity: AlertSeverity = INVARIANT_SEVERITY
    admin_event_severity: AlertSeverity = ADMIN_EVENT_SEVERITY
    oracle_deviation_severity: AlertSeverity = ORACLE_DEVIATION_SEVERITY

    def __post_init__(self) -> None:
        if self.i1_epsilon < 0:
            raise ValueError("i1_epsilon doit etre >= 0")
        if self.oracle_delta < 0:
            raise ValueError("oracle_delta doit etre >= 0")
        if self.i6_collateral_factor <= 0:
            raise ValueError("i6_collateral_factor doit etre > 0")
        if self.i5_supply_tolerance < 0:
            raise ValueError("i5_supply_tolerance doit etre >= 0")
