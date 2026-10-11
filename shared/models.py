"""Modeles de donnees partages (Pydantic STRICT) — contrat de `docs/CONTRACTS.md`.

Ce module implemente EXACTEMENT les 15 modeles specifies dans `docs/CONTRACTS.md`
(13 d'origine, PR #53 ; `AdminEvent` et `SupplySnapshot` ajoutes par la revision
groupee #104, decidee en OPEN_ANSWERS §79). Les conventions transverses y sont
actees (voir aussi `docs/OPEN_ANSWERS.md` §0, §0bis, §9) :

- Pydantic strict : chaque modele interdit tout champ hors schema
  (`model_config = ConfigDict(extra="forbid")`). Il n'y a plus de base
  permissive `_OpenModel`.
- Temps : tous les champs temporels sont des `datetime` UTC (suffixe `_at`),
  serialises en ISO 8601 avec offset. Jamais d'int epoch.
- Identites EVM : `Address` = `0x` + 40 hex ; `TxHash` = `0x` + 64 hex,
  valides par `pattern`.
- Montants : toujours des `int` en base units (jamais de `float` monetaire).
  Positivite imposee (`gt=0` quand le zero n'a pas de sens, `ge=0` sinon).
- Soupcon : partout ou il circule, un ratio borne `[0, 1]` (`float`) ET un
  montant absolu suspect (`int`, base units) coexistent.
- Ensembles fermes : `Enum` (str Enum), jamais de chaines libres.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Alias de types reutilisables (identites EVM, valides par regex) ---

Address = Annotated[
    str,
    Field(
        pattern=r"^0x[a-fA-F0-9]{40}$",
        description="Adresse EVM (20 octets hex).",
    ),
]
TxHash = Annotated[
    str,
    Field(
        pattern=r"^0x[a-fA-F0-9]{64}$",
        description="Hash de transaction / de log (32 octets hex).",
    ),
]
Bytes32 = Annotated[
    str,
    Field(
        pattern=r"^0x[a-fA-F0-9]{64}$",
        description="Mot de 32 octets hex (ex. identifiant de role AccessControl).",
    ),
]

#: Echelle des taux `*_rate_wad` : la valeur brute `ProtectedMinter.rate` du
#: contrat, x 10**18 (1e18 = 1 unite de M par unite de collateral). Base units
#: mintees = depot x 10**(decimales M - decimales collateral) x rate_wad / 1e18
#: (`ProtectedMinter.quoteMint`) ; la conversion reste au consommateur
#: (ex. `detection.provenance.rate_from_wad`).
RATE_WAD_SCALE = 10**18


# --- Enums fermes (cf. docs/CONTRACTS.md) ---


class AlertKind(str, Enum):
    """Nature d'une anomalie detectee."""

    MINT = "mint"
    TRANSFER = "transfer"
    BASELINE_ANOMALY = "baseline_anomaly"
    BEACON = "beacon"


class AlertSeverity(str, Enum):
    """Gravite d'une alerte."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ResponseActionType(str, Enum):
    """Les trois verbes de la reponse graduee (OPEN_ANSWERS §9)."""

    DELAY = "delay"
    DESTROY = "destroy"
    GLOBAL_PAUSE = "global_pause"


class ResponseActionStatus(str, Enum):
    """Cycle de vie d'une action de reponse."""

    PROPOSED = "proposed"
    APPLIED = "applied"
    EXPIRED = "expired"
    REJECTED = "rejected"


class FreezeDirection(str, Enum):
    """Sens d'une demande de gel (veto asymetrique)."""

    EXTEND = "extend"
    CONFIRM = "confirm"


class ReleaseVerdict(str, Enum):
    """Verdict d'une decision humaine multisig."""

    RELEASE = "release"
    CONFIRM_FREEZE = "confirm_freeze"
    CONFIRM_DESTROY = "confirm_destroy"
    GLOBAL_PAUSE = "global_pause"


class QuarantineStatus(str, Enum):
    """Statut d'un enregistrement de quarantaine."""

    ACTIVE = "active"
    EXTENDED = "extended"
    RELEASED = "released"
    BURNED = "burned"


class BeaconRiskLevel(str, Enum):
    """Niveau de risque publie par la balise."""

    NORMAL = "normal"
    ELEVATED = "elevated"
    FROZEN = "frozen"


class AdminEventKind(str, Enum):
    """Evenements d'administration surveilles (OPEN_ANSWERS §1 Q2, §79).

    `role_granted` / `role_revoked` / `rate_changed` sont emis aujourd'hui par
    le contrat protege #5 (AccessControl + `RateChanged`) et decodes par le
    monitor (#116). `upgraded` et `oracle_changed` sont les deux autres cas de
    §1 : aucun contrat du depot ne les emet encore, ils restent dans l'enum
    pour que detection garde une seule liste.
    """

    UPGRADED = "upgraded"
    ROLE_GRANTED = "role_granted"
    ROLE_REVOKED = "role_revoked"
    RATE_CHANGED = "rate_changed"
    ORACLE_CHANGED = "oracle_changed"


class MintProvenanceSource(str, Enum):
    """D'ou viennent les champs de demande d'un `MintEvent` (#104).

    - `request` : lus dans `SwapRequested`, enregistre au depot AVANT tout
      traitement (independant du traitement qui minte).
    - `completion` : demande anterieure a l'ecoute, champs relus dans
      `SwapCompleted`, ecrit par le contrat surveille (moins fiables).
    """

    REQUEST = "request"
    COMPLETION = "completion"


# --- Base stricte commune : interdit tout champ hors schema ---


class _StrictModel(BaseModel):
    """Base commune : Pydantic strict, aucun champ hors schema tolere."""

    model_config = ConfigDict(extra="forbid")


# --- Modeles partages (15), conformes a docs/CONTRACTS.md ---


class MintEvent(_StrictModel):
    """Evenement de mint observe on-chain sur Fuji.

    Le montant est celui derive on-chain par le contrat (volet 1), pas un
    montant signe par le demandeur.

    Revision groupee #104 (OPEN_ANSWERS §79) : en mode contrat protege, le
    monitor rattache le mint a sa demande (`SwapRequested` / `SwapCompleted` de
    la meme transaction) et renseigne les champs de demande ci-dessous. Hors de
    ce mode (Transfer ERC-20 nu), ils valent `None` = INCONNU. `amount` et
    `recipient` restent la verite du solde credite (le log du token), jamais
    les champs ecrits par le contrat surveille.
    """

    tx_hash: TxHash = Field(..., description="Hash de la transaction de mint.")
    log_index: int = Field(
        ..., ge=0, description="Index du log dans la transaction (unicite event)."
    )
    block_number: int = Field(..., ge=0, description="Numero de bloc.")
    chain_id: int = Field(
        ..., ge=1, description="Identifiant de chaine EVM (43113 = Fuji)."
    )
    observed_at: datetime = Field(
        ..., description="Horodatage d'observation par le monitor (UTC)."
    )
    recipient: Address = Field(..., description="Adresse creditee par le mint.")
    amount: int = Field(
        ..., gt=0, description="Montant minte en base units (derive on-chain)."
    )
    request_id: int | None = Field(
        None,
        ge=0,
        description=(
            "Identifiant de la MintRequest traitee (« demande n°X »), ou None "
            "quand il n'est pas porte par l'observation (un Transfer ERC-20 nu "
            "ne porte pas l'id de demande). None = INCONNU, jamais une vraie "
            "demande : les demandes reelles sont numerotees a partir de 0 "
            "(cf. `data/generate.py`, `MintRequest.request_id` ge=0), donc une "
            "sentinelle entiere (ex. 0) entrerait en collision. Le decodeur "
            "ERC-20 nu du monitor met None ; en mode contrat protege, il vient "
            "de `SwapCompleted` (#104)."
        ),
    )
    depositor: Address | None = Field(
        None,
        description=(
            "Deposant enregistre de la demande (I3 : doit egaler `recipient`). "
            "None = inconnu."
        ),
    )
    deposit_amount: int | None = Field(
        None,
        gt=0,
        description=(
            "Depot de la demande, base units du collateral depose (I1). "
            "None = inconnu."
        ),
    )
    rate_wad: int | None = Field(
        None,
        gt=0,
        description=(
            "Taux fige a la demande, valeur brute du contrat x 1e18 "
            "(`ProtectedMinter.rate`, echelle RATE_WAD_SCALE). None = inconnu."
        ),
    )
    provenance_source: MintProvenanceSource | None = Field(
        None,
        description=(
            "Origine des champs de demande : `request` (SwapRequested) ou "
            "`completion` (SwapCompleted, moins fiable). None = aucune demande "
            "rattachee."
        ),
    )
    claimed_minted: int | None = Field(
        None,
        ge=0,
        description=(
            "Montant que `SwapCompleted` DIT avoir minte (ecrit par le contrat "
            "surveille ; a comparer a `amount`, qui fait foi). None = inconnu."
        ),
    )
    via_protected_path: bool | None = Field(
        None,
        description=(
            "True = mint rattache au chemin prevu du contrat protege (demande "
            "dans la transaction) ; False = mint SANS provenance, chemin non "
            "prevu (I4 viole) ; None = non verifie (observation hors mode "
            "contrat protege)."
        ),
    )

    @model_validator(mode="after")
    def _check_provenance(self) -> MintEvent:
        """Coherence des champs de demande (#104).

        Les champs de demande ne viennent que des evenements du minter, et un
        mint rattache au chemin prevu a toujours sa demande :
        `provenance_source` est renseignee SI ET SEULEMENT SI
        `via_protected_path=True`, et elle exige `request_id` et `depositor`.
        Sans provenance, aucun champ de demande n'est porte (pas de
        `request_id` non plus quand le mint est explicitement sans provenance).
        """
        request_fields = (
            self.depositor,
            self.deposit_amount,
            self.rate_wad,
            self.claimed_minted,
        )
        if (self.provenance_source is not None) != (self.via_protected_path is True):
            raise ValueError(
                "provenance_source est renseignee si et seulement si "
                "via_protected_path=True"
            )
        if self.provenance_source is None:
            if any(value is not None for value in request_fields):
                raise ValueError(
                    "depositor/deposit_amount/rate_wad/claimed_minted exigent "
                    "provenance_source"
                )
        elif self.request_id is None or self.depositor is None:
            raise ValueError("provenance_source exige request_id et depositor")
        if self.via_protected_path is False and self.request_id is not None:
            raise ValueError(
                "via_protected_path=False (mint sans provenance) exclut request_id"
            )
        return self


class TransferEvent(_StrictModel):
    """Transfert de tokens observe on-chain.

    Tout transfert declenche une emission de Ghost chez le destinataire
    (OPEN_ANSWERS §0bis) ; cet evenement est l'observation brute du transfert,
    pas le Ghost lui-meme.
    """

    tx_hash: TxHash = Field(..., description="Hash de la transaction de transfert.")
    log_index: int = Field(
        ..., ge=0, description="Index du log dans la transaction."
    )
    block_number: int = Field(..., ge=0, description="Numero de bloc.")
    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")
    observed_at: datetime = Field(
        ..., description="Horodatage d'observation (UTC)."
    )
    sender: Address = Field(..., description="Adresse emettrice.")
    recipient: Address = Field(..., description="Adresse receptrice.")
    amount: int = Field(..., gt=0, description="Montant transfere en base units.")
    is_ghost: bool = Field(
        ...,
        description=(
            "True si le log vient du contrat Ghost M' (contrat separe, #8 ; "
            "transfert de Ghost), False s'il vient du vrai token M. Il n'existe "
            "pas de « Ghost d'un Ghost » (OPEN_ANSWERS §0bis-b)."
        ),
    )


class AlertSeed(_StrictModel):
    """Adresse « graine » suspecte a marquer au depart de la contamination.

    Chaque graine porte son propre soupcon (ratio + montant absolu) : le modele
    de contamination par ratio (OPEN_ANSWERS §9) a besoin de savoir quelles
    adresses marquer au depart et pour quels montants. Une `Alert` en transporte
    une liste (champ `seeds`).
    """

    address: Address = Field(
        ..., description="Adresse graine a marquer suspecte au depart."
    )
    suspect_amount: int = Field(
        ..., ge=0, description="Montant absolu suspect de la graine, base units."
    )
    contamination_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction suspecte normalisee de la graine."
    )


class Alert(_StrictModel):
    """Anomalie detectee sur un mint, un transfert ou la baseline adaptative.

    Porte le soupcon (ratio + montant absolu). Le discriminant acte est
    « volume eleve ET dispersion effondree » (OPEN_ANSWERS §9).
    """

    alert_id: str = Field(
        ..., min_length=1, description="Identifiant unique de l'alerte (UUID synthetique)."
    )
    kind: AlertKind = Field(..., description="Nature de l'anomalie.")
    severity: AlertSeverity = Field(..., description="Gravite de l'alerte.")
    created_at: datetime = Field(
        ..., description="Horodatage de creation de l'alerte (UTC)."
    )
    monitor_name: str = Field(
        ..., min_length=1, description="Surveillant emetteur (ex. rule_mint, ml)."
    )
    subject_address: Address = Field(
        ..., description="Adresse concernee par le soupcon."
    )
    source_tx_hash: TxHash | None = Field(
        None, description="Transaction declenchante (si applicable)."
    )
    contamination_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction suspecte normalisee."
    )
    suspect_amount: int = Field(
        ..., ge=0, description="Montant absolu suspect, base units."
    )
    dispersion_score: float | None = Field(
        None, ge=0.0, description="Mesure de dispersion (effondree = concentration)."
    )
    volume_zscore: float | None = Field(
        None, description="Ecart du volume courant vs baseline mediane+MAD."
    )
    reason: str = Field(
        ..., min_length=1, description="Explication lisible (regle declenchee)."
    )
    seeds: list[AlertSeed] = Field(
        default_factory=list,
        description=(
            "Adresses graines a marquer suspectes au depart et leur montant, "
            "pour amorcer la contamination par ratio (OPEN_ANSWERS §9). Les "
            "champs scalaires ci-dessus restent le resume/raccourci de l'alerte."
        ),
    )


class ResponseAction(_StrictModel):
    """Action de la reponse graduee (un des trois verbes actes).

    `delay` est auto-expirant (`expires_at` renseigne) ; `destroy` et
    `global_pause` referencent la decision multisig (`decision_id`).
    """

    action_id: str = Field(
        ..., min_length=1, description="Identifiant unique de l'action."
    )
    action_type: ResponseActionType = Field(
        ..., description="delay / destroy / global_pause."
    )
    status: ResponseActionStatus = Field(
        ..., description="proposed / applied / expired / rejected."
    )
    created_at: datetime = Field(..., description="Horodatage de creation (UTC).")
    expires_at: datetime | None = Field(
        None, description="Expiration (obligatoire si action_type=delay)."
    )
    perimeter_address: Address | None = Field(
        None, description="Perimetre cible (None si global_pause)."
    )
    triggering_alert_id: str | None = Field(
        None, description="Alerte a l'origine de l'action."
    )
    decision_id: str | None = Field(
        None,
        description="ReleaseDecision multisig (requis pour destroy/global_pause).",
    )
    contamination_ratio: float | None = Field(
        None, ge=0.0, le=1.0, description="Ratio au moment de l'action."
    )
    suspect_amount: int | None = Field(
        None, ge=0, description="Montant suspect vise (base units)."
    )


class AuditLogEntry(_StrictModel):
    """Entree immuable du journal d'audit (DORA).

    Trace qui a fait quoi, quand, sur quoi, et pourquoi. Append-only ; jamais
    modifiee apres ecriture.
    """

    entry_id: str = Field(
        ..., min_length=1, description="Identifiant unique de l'entree."
    )
    recorded_at: datetime = Field(..., description="Horodatage d'ecriture (UTC).")
    actor: str = Field(
        ..., min_length=1, description="Auteur (monitor:rule_transfer, multisig, ...)."
    )
    event_type: str = Field(
        ..., min_length=1, description="Type d'evenement journalise."
    )
    subject_address: Address | None = Field(
        None, description="Adresse concernee."
    )
    related_action_id: str | None = Field(
        None, description="ResponseAction liee, le cas echeant."
    )
    related_tx_hash: TxHash | None = Field(
        None, description="Transaction on-chain liee."
    )
    payload: dict[str, str] = Field(
        ...,
        description="Details structures cle->valeur (donnees fictives uniquement).",
    )
    message: str = Field(
        ..., min_length=1, description="Resume lisible pour un auditeur humain."
    )


class MintRequest(_StrictModel):
    """Demande de mint et depot associe enregistre on-chain.

    La signature autorise « traiter la demande n°X », PAS un montant : le
    contrat derive lui-meme le montant du depot on-chain (OPEN_ANSWERS §0).
    `requested_amount` n'est donc pas un champ.
    """

    request_id: int = Field(
        ...,
        ge=0,
        description="Identifiant de la demande (autorisee par la signature).",
    )
    requester: Address = Field(..., description="Adresse du demandeur.")
    deposit_token: Address = Field(
        ..., description="Token du depot enregistre on-chain."
    )
    deposit_amount: int = Field(
        ...,
        gt=0,
        description="Montant du depot en base units (le contrat en derive le mint).",
    )
    created_at: datetime = Field(
        ..., description="Horodatage d'enregistrement de la demande (UTC)."
    )
    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")
    signature: str = Field(
        ...,
        pattern=r"^0x[a-fA-F0-9]+$",
        description="Signature autorisant « traiter la demande n°X » (hex).",
    )


class QuarantineRecord(_StrictModel):
    """Etat de quarantaine d'un perimetre (adresse) : solde Ghost non converti,
    fenetre courante, ratio de contamination.

    La fenetre normale est courte (ex. 10 min) ; elle peut etre allongee
    (status=extended, auto-expirante). `active`->`released` (conversion 1:1) ou
    `active`->`burned` (gel confirme).
    """

    record_id: str = Field(
        ..., min_length=1, description="Identifiant unique de l'enregistrement."
    )
    address: Address = Field(
        ..., description="Adresse (perimetre) sous quarantaine."
    )
    status: QuarantineStatus = Field(
        ..., description="active / extended / released / burned."
    )
    ghost_balance: int = Field(
        ..., ge=0, description="Solde Ghost non converti, base units."
    )
    contamination_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio de contamination de l'adresse."
    )
    suspect_amount: int = Field(
        ...,
        ge=0,
        description="Montant absolu suspect (= ratio x ghost_balance), base units.",
    )
    window_opened_at: datetime = Field(
        ..., description="Ouverture de la fenetre courante (UTC)."
    )
    window_expires_at: datetime = Field(
        ...,
        description="Fin de la fenetre courante (apres quoi conversion possible, UTC).",
    )
    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")


class FreezeRequest(_StrictModel):
    """Demande de gel emanant d'un surveillant.

    Veto asymetrique : tout surveillant peut ralentir (direction=extend,
    auto-expirant) ; une demande dans le sens risque (direction=confirm) est
    seulement une proposition tranchee par une ReleaseDecision multisig.
    """

    request_id: str = Field(
        ..., min_length=1, description="Identifiant unique de la demande de gel."
    )
    direction: FreezeDirection = Field(
        ...,
        description="extend (allonger, sur) / confirm (proposer gel/destruction).",
    )
    requested_by: str = Field(
        ..., min_length=1, description="Surveillant/IA a l'origine (ex. ai)."
    )
    created_at: datetime = Field(
        ..., description="Horodatage de la demande (UTC)."
    )
    perimeter_address: Address = Field(..., description="Perimetre vise.")
    triggering_alert_id: str | None = Field(
        None, description="Alerte a l'origine."
    )
    contamination_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio justifiant la demande."
    )
    suspect_amount: int = Field(
        ..., ge=0, description="Montant absolu suspect, base units."
    )
    extend_minutes: int | None = Field(
        None,
        gt=0,
        description="Duree d'allongement demandee (si direction=extend).",
    )


class ReleaseDecision(_StrictModel):
    """Decision humaine (multisig) levant un gel ou confirmant une action
    irreversible.

    Seule voie pour `destroy` et `global_pause` (OPEN_ANSWERS §9). Porte les
    signatures multisig : voler une cle ne suffit pas.
    """

    decision_id: str = Field(
        ..., min_length=1, description="Identifiant unique de la decision."
    )
    verdict: ReleaseVerdict = Field(
        ...,
        description="release / confirm_freeze / confirm_destroy / global_pause.",
    )
    decided_at: datetime = Field(
        ..., description="Horodatage de la decision (UTC)."
    )
    perimeter_address: Address | None = Field(
        None, description="Perimetre (None si global_pause)."
    )
    related_freeze_id: str | None = Field(
        None, description="FreezeRequest tranchee."
    )
    signers: list[Address] = Field(
        ..., min_length=1, description="Signataires multisig (au moins une adresse)."
    )
    threshold: int = Field(
        ..., ge=1, description="Seuil M du multisig (M parmi N) requis."
    )
    burn_ratio: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Fraction a detruire si confirm_destroy.",
    )
    rationale: str = Field(
        ..., min_length=1, description="Justification humaine consignee (audit)."
    )


class RiskBeaconUpdate(_StrictModel):
    """Publication de l'etat de risque d'une adresse/perimetre — le prix du
    risque continu.

    L'aval lit le ratio pour accepter/refuser une garantie au-dessus d'un
    seuil. Un pool AMM est une adresse avec un ratio comme une autre.
    """

    beacon_id: str = Field(
        ..., min_length=1, description="Identifiant unique de la publication."
    )
    address: Address = Field(
        ..., description="Adresse/perimetre couvert (y compris pool AMM)."
    )
    risk_level: BeaconRiskLevel = Field(
        ..., description="normal / elevated / frozen."
    )
    contamination_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Prix du risque : fraction suspecte publiee."
    )
    suspect_amount: int = Field(
        ..., ge=0, description="Montant absolu suspect publie, base units."
    )
    published_at: datetime = Field(
        ..., description="Horodatage de publication (UTC)."
    )
    window_expires_at: datetime | None = Field(
        None, description="Fin de fenetre allongee en cours, le cas echeant (UTC)."
    )
    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")


class GhostTokenMintEvent(_StrictModel):
    """Emission d'un Token Ghost chez le destinataire lors d'un transfert ou
    d'un mint (quarantaine liquide, OPEN_ANSWERS §0bis).

    Le Ghost porte son ratio de contamination entrant (lignage par ratio par
    adresse) : le montant envoye porte le ratio courant de l'expediteur.
    """

    tx_hash: TxHash = Field(..., description="Transaction ayant emis le Ghost.")
    log_index: int = Field(..., ge=0, description="Index du log.")
    block_number: int = Field(..., ge=0, description="Numero de bloc.")
    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")
    minted_at: datetime = Field(
        ..., description="Horodatage d'emission du Ghost (UTC)."
    )
    recipient: Address = Field(..., description="Adresse recevant le Ghost.")
    amount: int = Field(..., gt=0, description="Montant de Ghost emis, base units.")
    incoming_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Ratio porte par le montant entrant (ratio expediteur).",
    )
    window_expires_at: datetime = Field(
        ...,
        description="Fin de fenetre avant conversion 1:1 possible (UTC).",
    )
    source_transfer_tx: TxHash | None = Field(
        None, description="Transfert sous-jacent (si issu d'un transfert)."
    )


class GhostTokenRedemptionEvent(_StrictModel):
    """Conversion 1:1 d'un Token Ghost en vrai token, apres la fenetre sans
    anomalie.

    Autorisee uniquement si le ratio ET le montant absolu suspect sont sous
    seuil au moment de la conversion (OPEN_ANSWERS §9).
    """

    tx_hash: TxHash = Field(..., description="Transaction de conversion.")
    log_index: int = Field(..., ge=0, description="Index du log.")
    block_number: int = Field(..., ge=0, description="Numero de bloc.")
    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")
    redeemed_at: datetime = Field(
        ..., description="Horodatage de conversion (UTC)."
    )
    holder: Address = Field(..., description="Adresse convertissant son Ghost.")
    ghost_amount: int = Field(
        ..., gt=0, description="Montant de Ghost converti, base units."
    )
    token_amount: int = Field(
        ...,
        ge=0,
        description="Montant de vrai token recu (apres marge eventuelle), base units.",
    )
    fee_amount: int = Field(
        ..., ge=0, description="Marge prelevee a la conversion, base units (0 si aucune)."
    )
    contamination_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Ratio au moment de la conversion (sous seuil).",
    )


class GhostTokenBurnEvent(_StrictModel):
    """Destruction de la fraction suspecte du Ghost non converti d'une adresse
    (burn_ratio x ghost_balance), pas tout le solde (OPEN_ANSWERS §9).

    Porte le ratio ET le montant absolu suspect detruits : destruction
    proportionnelle a l'exposition reelle.
    """

    tx_hash: TxHash = Field(..., description="Transaction de destruction.")
    log_index: int = Field(..., ge=0, description="Index du log.")
    block_number: int = Field(..., ge=0, description="Numero de bloc.")
    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")
    burned_at: datetime = Field(
        ..., description="Horodatage de destruction (UTC)."
    )
    address: Address = Field(
        ..., description="Adresse dont le Ghost suspect est detruit."
    )
    burned_amount: int = Field(
        ...,
        gt=0,
        description="Montant de Ghost detruit, base units (= fraction suspecte).",
    )
    contamination_ratio: float = Field(
        ..., ge=0.0, le=1.0, description="Ratio applique pour la destruction."
    )
    suspect_amount: int = Field(
        ..., ge=0, description="Montant absolu suspect detruit, base units."
    )
    decision_id: str = Field(
        ...,
        min_length=1,
        description="ReleaseDecision multisig autorisant la destruction.",
    )


# --- Revision groupee #104 (OPEN_ANSWERS §79) : administration, offre/collateral ---

_ROLE_KINDS = frozenset({AdminEventKind.ROLE_GRANTED, AdminEventKind.ROLE_REVOKED})


class AdminEvent(_StrictModel):
    """Evenement d'administration observe on-chain (OPEN_ANSWERS §1 Q2, §79).

    Le surveillant de mint verifie que les hypotheses du volet 1 tiennent : un
    role accorde/retire, un changement de taux, un upgrade ou un changement
    d'oracle NON annonce est une alerte. Les champs propres a un type
    d'evenement sont types (pas de dictionnaire libre) et exiges seulement pour
    ce type : `role` pour `role_granted` / `role_revoked`, `old_rate_wad` et
    `new_rate_wad` pour `rate_changed`.
    """

    tx_hash: TxHash = Field(..., description="Transaction ayant emis l'evenement.")
    log_index: int = Field(..., ge=0, description="Index du log dans la transaction.")
    block_number: int = Field(..., ge=0, description="Numero de bloc.")
    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")
    observed_at: datetime = Field(
        ..., description="Horodatage d'observation par le monitor (UTC)."
    )
    contract_address: Address = Field(
        ..., description="Contrat emetteur du log (minter, token, Ghost...)."
    )
    kind: AdminEventKind = Field(..., description="Nature de l'evenement.")
    subject_address: Address = Field(
        ...,
        description=(
            "Compte concerne : recoit/perd le role, auteur du changement de taux, "
            "nouvelle implementation ou nouvel oracle."
        ),
    )
    actor: Address | None = Field(
        None,
        description=(
            "Compte ayant declenche le changement quand le log le porte "
            "(`sender` de RoleGranted/RoleRevoked). None = non porte."
        ),
    )
    role: Bytes32 | None = Field(
        None,
        description=(
            "Identifiant bytes32 du role (AccessControl ; DEFAULT_ADMIN_ROLE = "
            "0x00..00). Exige pour role_granted / role_revoked, interdit sinon."
        ),
    )
    old_rate_wad: int | None = Field(
        None,
        gt=0,
        description="Ancien taux x 1e18 (rate_changed seulement).",
    )
    new_rate_wad: int | None = Field(
        None,
        gt=0,
        description="Nouveau taux x 1e18 (rate_changed seulement).",
    )

    @model_validator(mode="after")
    def _check_kind_fields(self) -> AdminEvent:
        """Les champs types ne sont portes que par le type qui les emet."""
        is_role = self.kind in _ROLE_KINDS
        if is_role != (self.role is not None):
            raise ValueError("role est exige pour role_granted/role_revoked, interdit sinon")
        is_rate = self.kind is AdminEventKind.RATE_CHANGED
        rates = (self.old_rate_wad, self.new_rate_wad)
        if is_rate and any(value is None for value in rates):
            raise ValueError("rate_changed exige old_rate_wad et new_rate_wad")
        if not is_rate and any(value is not None for value in rates):
            raise ValueError("old_rate_wad/new_rate_wad reserves a rate_changed")
        return self


class SupplySnapshot(_StrictModel):
    """Lecture de l'offre et du collateral a un bloc donne (invariants I5, I6).

    I5 compare deux lectures successives de `total_supply` aux mints et burns
    observes entre elles ; I6 compare la valeur en circulation
    (`total_supply + ghost_supply`, = `GhostToken.supplyValue()` avec #8) a
    `collateral_value`. Lectures de fonctions `view` a un bloc (pas des
    evenements) : `totalSupply()`, `balanceOf(minter)` du collateral.
    """

    chain_id: int = Field(..., ge=1, description="Identifiant de chaine EVM.")
    block_number: int = Field(..., ge=0, description="Bloc de la lecture.")
    observed_at: datetime = Field(..., description="Horodatage de la lecture (UTC).")
    token_address: Address = Field(..., description="Contrat du vrai token M lu.")
    total_supply: int = Field(
        ..., ge=0, description="`totalSupply()` de M au bloc, base units de M."
    )
    ghost_supply: int | None = Field(
        None,
        ge=0,
        description=(
            "`totalSupply()` du Ghost M' au bloc, base units (meme echelle que M). "
            "None = pas de Ghost deploye ou non lu."
        ),
    )
    collateral_value: int | None = Field(
        None,
        ge=0,
        description=(
            "Collateral detenu par le minter, exprime en base units de M (I6) : "
            "solde du collateral x 10**(decimales M - decimales collateral), sans "
            "taux. None = non lu."
        ),
    )
