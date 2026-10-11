"""Parametres de la simulation hors chaine des scenarios de demo (#47).

AUCUN seuil ni aucune valeur n'est acte ici : ce sont des valeurs de depart
pour un generateur SYNTHETIQUE, toutes a calibrer et a valider en equipe
(docs/OPEN_QUESTIONS.md §6, et §5 pour la mesure). Les fenetres Ghost
(10 min / 1 h) sont reprises de `dashboard.demo_data` (proposition §3.1).
Montants en base units (int), ratios en float [0, 1].
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dashboard.demo_data import DEMO_EXTENDED_WINDOW
from detection.params import TransferRuleParams


class SimulationParams(BaseModel):
    """Parametres de la simulation ; chaque champ est a calibrer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Trafic legitime ---
    supply: int = Field(1_000_000_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    legit_address_count: int = Field(200, ge=2)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    legit_transfers_per_bucket: int = Field(40, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    legit_amount_min: int = Field(1_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    legit_amount_max: int = Field(50_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)

    # --- Surveillant simule (mediane + MAD, OPEN_ANSWERS §9) ---
    bucket_minutes: int = Field(5, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    warmup_buckets: int = Field(12, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    baseline_buckets: int = Field(12, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    volume_zscore_threshold: float = 4.0  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    dispersion_threshold: float = Field(0.2, ge=0.0, le=1.0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    mad_floor: float = Field(1e-6, gt=0.0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    growth_factor: float = Field(5.0, gt=0.0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)

    # --- Attaquant (B, C, D) ---
    attacker_address_count: int = Field(3, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    attack_transfers_per_bucket: int = Field(300, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    attack_amount_per_tx: int = Field(100_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    onchain_cap_per_tx: int = Field(500_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    attack_buckets: int = Field(3, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    human_confirmation_delay_minutes: int = Field(20, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)

    # --- A : minter vulnerable vs protege ---
    deposit_amount: int = Field(1_000_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    signed_amount_multiplier: int = Field(1_000, gt=1)  # a calibrer (docs/OPEN_QUESTIONS.md §6)

    # --- C : faux marche de pret + balise ---
    lending_ltv: float = Field(0.5, gt=0.0, le=1.0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    beacon_ratio_threshold: float = Field(0.5, ge=0.0, le=1.0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    attacker_loan_count: int = Field(12, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    legit_loan_count: int = Field(6, ge=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)

    # --- D : pool AMM du Token Ghost ---
    pool_ghost_reserve: int = Field(100_000_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    pool_stable_reserve: int = Field(100_000_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    attacker_ghost_sold: int = Field(15_000_000_000, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)

    # --- N3 : burst legitime concentre ---
    consolidation_transfers: int = Field(300, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)

    # --- Trafic du generateur `data/` (#24) pour B, N1, N2, N3 (#70) ---
    # Jours simules : le surveillant #12 compare chaque tranche au MEME creneau des jours
    # precedents et exige `min_history_slots` jours d'historique (detection/params.py).
    real_traffic_days: int = Field(6, gt=0)  # a calibrer (docs/OPEN_QUESTIONS.md §6)
    # Part du solde envoyee par un transfert legitime. Profil « petits transferts » (1-10 %)
    # de `data/DECISION_SUPPORT_3.md` §2, choisi pour la demo (#70, a valider en equipe) :
    # aux seuils par defaut du surveillant #12 (z = 3 / 3), il donne 0 faux positif sur N1/N2
    # (seeds 7, 20, 42) et detecte B. Avec le profil « gros transferts » du generateur
    # (5-50 %), le meme surveillant leve 1 faux positif sur N1 (seed 20) : mesure a montrer,
    # pas a cacher (docs/CLAIMS.md).
    real_transfer_fraction_min: float = Field(0.01, gt=0.0, le=1.0)  # a calibrer (§6)
    real_transfer_fraction_max: float = Field(0.1, gt=0.0, le=1.0)  # a calibrer (§6)

    @model_validator(mode="after")
    def _coherent(self) -> SimulationParams:
        """Coherence interne (pas un choix de seuil) : sinon le scenario n'a pas de sens."""
        if self.legit_amount_min > self.legit_amount_max:
            raise ValueError("legit_amount_min doit etre <= legit_amount_max")
        if self.real_transfer_fraction_min > self.real_transfer_fraction_max:
            raise ValueError("real_transfer_fraction_min doit etre <= real_transfer_fraction_max")
        if self.real_traffic_days <= TransferRuleParams().min_history_slots:
            raise ValueError("real_traffic_days : la baseline du surveillant #12 n'aurait "
                             "jamais assez d'historique")
        if self.attack_amount_per_tx >= self.onchain_cap_per_tx:
            raise ValueError("B : l'attaquant doit rester sous le plafond on-chain")
        if timedelta(minutes=self.human_confirmation_delay_minutes) >= DEMO_EXTENDED_WINDOW:
            raise ValueError("la confirmation humaine doit tomber dans la fenetre allongee")
        return self


DEFAULT_PARAMS = SimulationParams()
