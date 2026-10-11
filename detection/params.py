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

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from fractions import Fraction

from shared.models import AlertSeverity

_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

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


# ---------------------------------------------------------------------------
# Surveillant de transferts (#12) — « volume eleve ET dispersion effondree »
#
# Source actee : docs/OPEN_ANSWERS.md §9 (DECISION 2026-10-10, Marceau) :
# ratios normalises (volume / offre en circulation), baseline mediane + MAD sur
# fenetre glissante, declencheur = volume eleve ET dispersion effondree, JAMAIS
# volume seul. Les valeurs de tous les seuils restent A MESURER (§9 « Reste
# ouvert »).
# Sources NON actees : docs/OPEN_QUESTIONS.md §2 « Propositions (2026-10-10,
# Yannis) » (tranches de 5 min vs meme creneau, Herfindahl, adresse neuve,
# points de sortie). Tout ce qui en decoule est PROVISOIRE.
# ---------------------------------------------------------------------------

# Nom du surveillant reporte dans `Alert.monitor_name` (exemple de
# `docs/CONTRACTS.md` : « rule_transfer »).
TRANSFER_MONITOR_NAME = "rule_transfer"

# Longueur d'une tranche — PROVISOIRE — a valider par l'equipe. Source :
# docs/OPEN_QUESTIONS.md §2, proposition 1 (PRIORITE HAUTE) : la detection doit
# etre plus rapide que la fenetre Ghost normale (10 min, OPEN_ANSWERS §0bis) ;
# proposition = tranches de 5 min. Une alerte part a la CLOTURE de la tranche.
SLOT_SECONDS = 300

# Periode du « meme creneau » — PROVISOIRE — a valider par l'equipe. Source :
# docs/OPEN_QUESTIONS.md §2, proposition 1 (« comparees a la baseline du meme
# creneau »). Une tranche est comparee aux tranches de meme position dans la
# periode (1 jour : 10:05-10:10 vs 10:05-10:10 des jours precedents). Doit etre
# un multiple de SLOT_SECONDS.
BASELINE_PERIOD_SECONDS = 86_400

# Taille de la fenetre glissante (nombre de tranches passees du meme creneau)
# — PROVISOIRE — a valider par l'equipe ; A MESURER. Source :
# docs/OPEN_ANSWERS.md §9 (« mediane + MAD sur fenetre glissante », longueur
# non tranchee). 7 = une semaine de jours, valeur de travail.
BASELINE_WINDOW_SLOTS = 7

# Historique minimal avant de pouvoir alerter — PROVISOIRE — a valider par
# l'equipe ; A MESURER. Source : docs/OPEN_ANSWERS.md §9 (baseline glissante,
# taille non tranchee). En dessous, la tranche alimente la baseline mais
# n'alerte JAMAIS (mediane/MAD non significatives sur trop peu de points).
MIN_HISTORY_SLOTS = 5

# Seuil du z robuste sur le ratio volume / offre en circulation — PROVISOIRE —
# a valider par l'equipe ; A MESURER. Source : docs/OPEN_ANSWERS.md §9
# (« volume eleve » ; valeur des seuils a mesurer sur le trafic synthetique).
# z = (x - mediane) / (MAD_SCALE x MAD). 3 = valeur de travail, pas une mesure.
VOLUME_Z_THRESHOLD = 3.0

# Seuil du z robuste sur l'indice de Herfindahl (HHI = somme des parts au
# carre des destinataires ; monte quand la dispersion s'effondre) —
# PROVISOIRE — a valider par l'equipe ; A MESURER. Sources :
# docs/OPEN_ANSWERS.md §9 (« dispersion effondree ») et docs/OPEN_QUESTIONS.md
# §2, proposition 4 (Herfindahl = mesure de reference). 3 = valeur de travail.
HHI_Z_THRESHOLD = 3.0

# Facteur d'echelle du MAD — PROVISOIRE — a valider par l'equipe. Convention
# statistique usuelle (1,4826 rend le MAD comparable a un ecart-type sur une
# loi normale) ; ce n'est pas une mesure. Source : docs/OPEN_ANSWERS.md §9
# (mediane + MAD).
MAD_SCALE = 1.4826

# Plancher du MAD, relatif a la mediane — PROVISOIRE — a valider par
# l'equipe ; A MESURER. Evite un z infini quand la baseline est parfaitement
# reguliere (MAD = 0, frequent sur des donnees synthetiques) :
# echelle = max(MAD_SCALE x MAD, MAD_FLOOR_RELATIVE x |mediane|). Doit etre > 0.
# Source : docs/OPEN_ANSWERS.md §9 (mediane + MAD ; seuils a mesurer).
MAD_FLOOR_RELATIVE = 0.05

# Points de sortie (exchanges / bridges) — PROVISOIRE — a valider par
# l'equipe. Source : docs/OPEN_QUESTIONS.md §2, proposition 3 : liste FIXE
# d'adresses etiquetees « exchange » / « bridge » produite par le generateur
# de donnees (proprietaire `data/` : @EnzoFB06, #24). Vide tant que cette
# liste n'existe pas : elle est passee par `TransferRuleParams.exit_points`.
EXIT_POINTS: frozenset[str] = frozenset()

# Gravite d'une alerte « volume eleve ET dispersion effondree » — PROVISOIRE —
# a valider par l'equipe. Source : exemple `Alert` de docs/CONTRACTS.md
# (rule_transfer, critical) ; quelle que soit la gravite, le surveillant ne
# peut que RETARDER (OPEN_ANSWERS §3).
TRANSFER_ANOMALY_SEVERITY = AlertSeverity.CRITICAL


@dataclass(frozen=True)
class TransferRuleParams:
    """Jeu de parametres du surveillant de transferts (defauts = constantes
    ci-dessus, toutes PROVISOIRES / A MESURER).

    Attributes:
        slot_seconds: longueur d'une tranche, secondes (PROVISOIRE).
        baseline_period_seconds: periode du « meme creneau », secondes ;
            multiple de `slot_seconds` (PROVISOIRE).
        baseline_window_slots: tranches passees du meme creneau gardees dans
            la baseline glissante (PROVISOIRE, A MESURER).
        min_history_slots: historique minimal avant toute alerte
            (PROVISOIRE, A MESURER).
        volume_z_threshold: seuil du z robuste sur volume / offre
            (PROVISOIRE, A MESURER).
        hhi_z_threshold: seuil du z robuste sur le Herfindahl (PROVISOIRE,
            A MESURER).
        mad_scale: facteur d'echelle du MAD (PROVISOIRE).
        mad_floor_relative: plancher du MAD relatif a la mediane, > 0
            (PROVISOIRE, A MESURER).
        exit_points: adresses etiquetees exchange / bridge (PROVISOIRE,
            fournies par `data/`, #24).
        anomaly_severity: gravite de l'alerte (PROVISOIRE).
    """

    slot_seconds: int = SLOT_SECONDS
    baseline_period_seconds: int = BASELINE_PERIOD_SECONDS
    baseline_window_slots: int = BASELINE_WINDOW_SLOTS
    min_history_slots: int = MIN_HISTORY_SLOTS
    volume_z_threshold: float = VOLUME_Z_THRESHOLD
    hhi_z_threshold: float = HHI_Z_THRESHOLD
    mad_scale: float = MAD_SCALE
    mad_floor_relative: float = MAD_FLOOR_RELATIVE
    exit_points: frozenset[str] = field(default=EXIT_POINTS)
    anomaly_severity: AlertSeverity = TRANSFER_ANOMALY_SEVERITY

    def __post_init__(self) -> None:
        if self.slot_seconds <= 0:
            raise ValueError("slot_seconds doit etre > 0")
        if (
            self.baseline_period_seconds <= 0
            or self.baseline_period_seconds % self.slot_seconds != 0
        ):
            raise ValueError(
                "baseline_period_seconds doit etre un multiple > 0 de slot_seconds"
            )
        if self.baseline_window_slots < 1:
            raise ValueError("baseline_window_slots doit etre >= 1")
        if not 1 <= self.min_history_slots <= self.baseline_window_slots:
            raise ValueError(
                "min_history_slots doit etre entre 1 et baseline_window_slots"
            )
        if self.volume_z_threshold <= 0 or self.hhi_z_threshold <= 0:
            raise ValueError("les seuils de z doivent etre > 0")
        if self.mad_scale <= 0:
            raise ValueError("mad_scale doit etre > 0")
        if self.mad_floor_relative <= 0:
            raise ValueError("mad_floor_relative doit etre > 0")
        for address in self.exit_points:
            if not _ADDRESS_RE.match(address):
                raise ValueError(f"exit_points : adresse EVM invalide {address!r}")


# ---------------------------------------------------------------------------
# Profils de chauffe de la baseline (#86)
#
# Le profil par defaut (constantes ci-dessus) compare une tranche aux tranches
# du MEME creneau des jours precedents et exige MIN_HISTORY_SLOTS = 5 jours
# d'historique avant toute alerte : inutilisable sur nos donnees synthetiques
# (24 h par defaut, `data/generate.py`). Le profil DEMO raccourcit la chauffe.
# ---------------------------------------------------------------------------

# Variable d'environnement de selection du profil (la CLI `--profile` prime).
ENV_DETECTION_PROFILE = "DETECTION_PROFILE"
PROFILE_DEFAULT = "default"
PROFILE_DEMO = "demo"

# DEMO — ne pas utiliser en production, PROVISOIRE. Periode du « meme
# creneau » = une seule tranche : chaque tranche est comparee aux tranches
# IMMEDIATEMENT precedentes (plus de saisonnalite jour/nuit dans la baseline).
DEMO_BASELINE_PERIOD_SECONDS = SLOT_SECONDS

# DEMO — ne pas utiliser en production, PROVISOIRE. Fenetre glissante de 24
# tranches (2 h avec des tranches de 5 min). Valeur de travail, pas une mesure.
DEMO_BASELINE_WINDOW_SLOTS = 24

# DEMO — ne pas utiliser en production, PROVISOIRE. Historique minimal de 12
# tranches (1 h) avant de pouvoir alerter. Valeur de travail, pas une mesure :
# un essai exploratoire a 12 / 6 (fenetre / historique) a leve des alertes sur
# le trafic `normal` de certaines graines du generateur (debut de journee peu
# actif) ; 24 / 12 n'en a pas leve sur les graines 1 a 8 (24 h simulees,
# defauts du generateur). Ce n'est PAS une mesure : le taux de faux positifs
# reste A MESURER (#59).
DEMO_MIN_HISTORY_SLOTS = 12

TRANSFER_PROFILES: dict[str, TransferRuleParams] = {
    # PROVISOIRE — a valider par l'equipe (constantes ci-dessus).
    PROFILE_DEFAULT: TransferRuleParams(),
    # DEMO — ne pas utiliser en production, PROVISOIRE.
    PROFILE_DEMO: TransferRuleParams(
        baseline_period_seconds=DEMO_BASELINE_PERIOD_SECONDS,
        baseline_window_slots=DEMO_BASELINE_WINDOW_SLOTS,
        min_history_slots=DEMO_MIN_HISTORY_SLOTS,
    ),
}


def resolve_profile(
    cli_value: str | None = None, env: Mapping[str, str] | None = None
) -> str:
    """Nom du profil actif : `cli_value`, sinon `DETECTION_PROFILE`, sinon
    `PROFILE_DEFAULT`.

    Args:
        cli_value: valeur de `--profile` (None = non fournie).
        env: environnement a lire (defaut : `os.environ`).

    Returns:
        Le nom du profil, en minuscules.

    Raises:
        ValueError: si le profil n'existe pas.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    name = (cli_value or source.get(ENV_DETECTION_PROFILE, "").strip() or PROFILE_DEFAULT)
    name = name.lower()
    if name not in TRANSFER_PROFILES:
        raise ValueError(
            f"profil de detection inconnu {name!r} "
            f"(attendu : {', '.join(sorted(TRANSFER_PROFILES))})"
        )
    return name


def transfer_params_for_profile(
    profile: str, exit_points: Iterable[str] = ()
) -> TransferRuleParams:
    """Parametres du surveillant de transferts pour un profil.

    Args:
        profile: nom de profil (`PROFILE_DEFAULT` ou `PROFILE_DEMO`).
        exit_points: points de sortie a ajouter (PROVISOIRE, fournis par
            l'appelant ; vides par defaut).

    Returns:
        Les parametres du profil, avec ces points de sortie.

    Raises:
        ValueError: si le profil n'existe pas ou si une adresse est invalide.
    """
    if profile not in TRANSFER_PROFILES:
        raise ValueError(f"profil de detection inconnu {profile!r}")
    base = TRANSFER_PROFILES[profile]
    points = frozenset(exit_points)
    if not points:
        return base
    return replace(base, exit_points=base.exit_points | points)
