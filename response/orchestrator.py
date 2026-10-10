"""Orchestration de la reponse graduee (issues #17, #18, #19).

Implemente la machine a etats actee dans `docs/OPEN_ANSWERS.md` §3 / §9 :

```
NORMAL --(alerte)--> RETARDE --(expiration, silence)--> NORMAL
                        |--(multisig 2/3)--> DETRUIT
                        '--(multisig 3/3)--> PAUSE_GLOBALE (levee par le meme multisig)
```

Trois verbes (`ResponseActionType`) :

- `delay` (retarder) : allonge la fenetre Ghost d'un perimetre. Decidable par un
  surveillant / l'IA **seul**, car c'est la direction sure. **Auto-expirant** :
  le silence ramene le perimetre a la normale. Pendant un retard les Ghost
  circulent, seule la conversion Ghost -> vrai token est suspendue.
- `destroy` (detruire la fraction suspecte) : multisig humain uniquement.
- `global_pause` : multisig humain unanime uniquement, levee par le meme quorum.

Vocabulaire acte (§3) : « l'IA ne decide jamais seule d'un blocage » se lit
« l'IA ne decide jamais seule d'une destruction ni d'une pause globale ». Un
surveillant qui demande plus (`FreezeDirection.CONFIRM`) ne produit qu'une
**proposition** (`status=proposed`).

Ce module est un **miroir hors chaine** : la verite on-chain (fenetre Ghost,
burn, multisig simule par `guardians`) vit dans le contrat. Ici, le multisig
est verifie sur la liste `ReleaseDecision.signers` (pas de verification
cryptographique) : c'est un multisig **simule**, a presenter comme tel.

Chaque etape est tracee dans un journal d'audit append-only (DORA), optionnellement
recopie en JSONL.

Les valeurs par defaut (durees, quorums) reprennent les propositions de reference
de la §3 et restent **a mesurer** sur le trafic synthetique (`docs/CLAIMS.md`).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from shared.models import (
    Alert,
    AlertSeverity,
    AuditLogEntry,
    FreezeDirection,
    FreezeRequest,
    ReleaseDecision,
    ReleaseVerdict,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
)

# --- Valeurs de reference (OPEN_ANSWERS §3) : a mesurer, pas des chiffres actes ---

DEFAULT_DELAY_MINUTES = 60
"""Fenetre allongee de reference : 10 min -> 1 h (§3, « proposition de reference »)."""

DEFAULT_PERIMETER_QUORUM = 2
"""Quorum multisig pour les decisions sur un perimetre (detruire : 2 sur 3, §3)."""

AUTO_EXPIRY_ACTOR = "response:auto_expiry"
MULTISIG_ACTOR = "multisig"

_SEVERITY_RANK: dict[AlertSeverity, int] = {
    AlertSeverity.INFO: 0,
    AlertSeverity.WARNING: 1,
    AlertSeverity.CRITICAL: 2,
}


class PerimeterState(str, Enum):
    """Etat d'un perimetre (adresse) dans la machine a etats §3.

    La pause globale est un etat du protocole, pas d'un perimetre : voir
    `ResponseOrchestrator.global_pause_active`.
    """

    NORMAL = "normal"
    DELAYED = "delayed"
    DESTROYED = "destroyed"


@dataclass(frozen=True)
class ResponsePolicy:
    """Parametres de la reponse graduee.

    Attributes:
        guardians: adresses des guardians du multisig simule (fictives).
        delay_minutes: duree d'un retard declenche par une alerte.
        max_monitor_delay_minutes: plafond d'allongement qu'un surveillant peut
            atteindre seul, compte depuis le debut du retard (garde-fou §9 :
            « facteur d'allongement maximal par perimetre »). Au-dela, le
            surveillant ne fait que proposer.
        confirmed_freeze_minutes: duree d'un retard confirme par le multisig
            (`ReleaseVerdict.CONFIRM_FREEZE`).
        auto_delay_min_severity: gravite minimale d'une alerte pour appliquer
            un retard automatiquement ; en dessous, le retard est seulement
            propose.
        perimeter_quorum: signatures requises pour lever, confirmer ou detruire
            sur un perimetre.
        global_pause_quorum: signatures requises pour decreter ou lever la
            pause globale. `None` = unanimite des guardians (3 sur 3, §3).
    """

    guardians: frozenset[str]
    delay_minutes: int = DEFAULT_DELAY_MINUTES
    max_monitor_delay_minutes: int = DEFAULT_DELAY_MINUTES
    confirmed_freeze_minutes: int = DEFAULT_DELAY_MINUTES
    auto_delay_min_severity: AlertSeverity = AlertSeverity.WARNING
    perimeter_quorum: int = DEFAULT_PERIMETER_QUORUM
    global_pause_quorum: int | None = None

    def __post_init__(self) -> None:
        guardians = frozenset(g.lower() for g in self.guardians)
        object.__setattr__(self, "guardians", guardians)
        if not guardians:
            raise ValueError("ResponsePolicy : au moins un guardian est requis.")
        for name in ("delay_minutes", "max_monitor_delay_minutes", "confirmed_freeze_minutes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"ResponsePolicy : {name} doit etre > 0.")
        for name, quorum in (
            ("perimeter_quorum", self.perimeter_quorum),
            ("global_pause_quorum", self.required_global_quorum),
        ):
            if not 1 <= quorum <= len(guardians):
                raise ValueError(
                    f"ResponsePolicy : {name}={quorum} hors de [1, {len(guardians)}]."
                )

    @property
    def required_global_quorum(self) -> int:
        """Quorum effectif de la pause globale (unanimite par defaut)."""
        if self.global_pause_quorum is None:
            return len(self.guardians)
        return self.global_pause_quorum


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _key(address: str) -> str:
    """Cle de perimetre : les adresses EVM sont comparees sans la casse."""
    return address.lower()


def _monitor_actor(monitor_name: str) -> str:
    return monitor_name if ":" in monitor_name else f"monitor:{monitor_name}"


class ResponseOrchestrator:
    """Coordonne la reponse graduee : alerte -> retard -> decision humaine.

    Toutes les methodes publiques commencent par appliquer les expirations dues
    (silence = retour automatique a la normale).
    """

    def __init__(
        self,
        policy: ResponsePolicy,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
        audit_path: Path | None = None,
    ) -> None:
        """Cree un orchestrateur.

        Args:
            policy: parametres de la reponse graduee.
            clock: horloge UTC (timezone-aware), injectable pour les tests.
            id_factory: generateur d'identifiants `prefix -> id`.
            audit_path: si fourni, chaque entree d'audit y est ajoutee en JSONL.
        """
        self._policy = policy
        self._clock = clock or _default_clock
        self._new_id = id_factory or _default_id_factory
        self._audit_path = audit_path

        self._actions: dict[str, ResponseAction] = {}
        self._active_delays: dict[str, str] = {}  # perimetre -> action_id
        self._delay_started_at: dict[str, datetime] = {}  # perimetre -> debut du retard
        self._destroyed: set[str] = set()
        self._proposals_by_freeze: dict[str, str] = {}  # FreezeRequest.request_id -> action_id
        self._freeze_perimeter: dict[str, str] = {}  # FreezeRequest.request_id -> perimetre
        self._alert_tx: dict[str, str] = {}  # alert_id -> source_tx_hash
        self._global_pause_id: str | None = None
        self._audit_log: list[AuditLogEntry] = []

    # ------------------------------------------------------------------ lecture

    @property
    def policy(self) -> ResponsePolicy:
        """Parametres en vigueur."""
        return self._policy

    @property
    def audit_log(self) -> tuple[AuditLogEntry, ...]:
        """Copie du journal d'audit (append-only, ordre chronologique)."""
        return tuple(entry.model_copy(deep=True) for entry in self._audit_log)

    @property
    def actions(self) -> tuple[ResponseAction, ...]:
        """Etat courant de toutes les actions connues."""
        return tuple(self._actions.values())

    @property
    def global_pause_active(self) -> bool:
        """True si une pause globale decidee par multisig est en vigueur."""
        return self._global_pause_id is not None

    def perimeter_state(self, address: str) -> PerimeterState:
        """Etat courant d'un perimetre (apres application des expirations)."""
        self.expire_due()
        key = _key(address)
        if key in self._active_delays:
            return PerimeterState.DELAYED
        if key in self._destroyed:
            return PerimeterState.DESTROYED
        return PerimeterState.NORMAL

    def active_delay(self, address: str) -> ResponseAction | None:
        """Retard en cours sur un perimetre, s'il existe."""
        self.expire_due()
        action_id = self._active_delays.get(_key(address))
        return self._actions[action_id] if action_id else None

    def is_conversion_suspended(self, address: str) -> bool:
        """True si la conversion Ghost -> vrai token est suspendue pour l'adresse.

        Pendant un retard, les Ghost circulent mais ne se convertissent pas (§3).
        """
        return self.global_pause_active or self.active_delay(address) is not None

    # --------------------------------------------------------------- #17 alerte

    def handle_alert(self, alert: Alert) -> ResponseAction:
        """Declenche la reponse graduee pour une alerte.

        Le perimetre suspect est `alert.subject_address` plus chaque graine de
        `alert.seeds`. Si la gravite atteint `auto_delay_min_severity`, chaque
        perimetre est retarde (direction sure, decidable seul) ; sinon le retard
        est seulement propose. Jamais de destruction ni de pause ici.

        Args:
            alert: l'alerte emise par un surveillant.

        Returns:
            L'action portant sur `alert.subject_address`.
        """
        self.expire_due()
        actor = _monitor_actor(alert.monitor_name)
        if alert.source_tx_hash is not None:
            self._alert_tx[alert.alert_id] = alert.source_tx_hash
        self._audit(
            actor=actor,
            event_type="alert_received",
            subject_address=alert.subject_address,
            related_tx_hash=alert.source_tx_hash,
            payload={
                "alert_id": alert.alert_id,
                "kind": alert.kind.value,
                "severity": alert.severity.value,
                "contamination_ratio": str(alert.contamination_ratio),
                "suspect_amount": str(alert.suspect_amount),
                "seeds": str(len(alert.seeds)),
            },
            message=f"Alerte {alert.severity.value} recue de {actor} : {alert.reason}",
        )

        # Perimetres : sujet d'abord, puis graines distinctes (soupcon propre a chacune).
        perimeters: dict[str, tuple[str, float, int]] = {
            _key(alert.subject_address): (
                alert.subject_address,
                alert.contamination_ratio,
                alert.suspect_amount,
            )
        }
        for seed in alert.seeds:
            perimeters.setdefault(
                _key(seed.address),
                (seed.address, seed.contamination_ratio, seed.suspect_amount),
            )

        auto = (
            _SEVERITY_RANK[alert.severity]
            >= _SEVERITY_RANK[self._policy.auto_delay_min_severity]
        )
        if not auto:
            address, ratio, amount = perimeters[_key(alert.subject_address)]
            return self._propose_delay(
                actor=actor,
                address=address,
                alert_id=alert.alert_id,
                ratio=ratio,
                amount=amount,
                minutes=self._policy.delay_minutes,
                message=(
                    f"Gravite {alert.severity.value} sous le seuil automatique : retard "
                    f"propose sur {address}, non applique (revue humaine possible)"
                ),
            )

        subject_action: ResponseAction | None = None
        for key, (address, ratio, amount) in perimeters.items():
            request = FreezeRequest(
                request_id=self._new_id("fr"),
                direction=FreezeDirection.EXTEND,
                requested_by=actor,
                created_at=self._now(),
                perimeter_address=address,
                triggering_alert_id=alert.alert_id,
                contamination_ratio=ratio,
                suspect_amount=amount,
                extend_minutes=self._policy.delay_minutes,
            )
            action = self.request_freeze(request)
            if key == _key(alert.subject_address):
                subject_action = action
        assert subject_action is not None  # le sujet est toujours le premier perimetre
        return subject_action

    # ------------------------------------------------------------ #18 gel/levee

    def request_freeze(self, request: FreezeRequest) -> ResponseAction:
        """Enregistre une demande de gel emanant d'un surveillant / de l'IA.

        Veto asymetrique :

        - `extend` : allonge (jamais ne raccourcit) le retard du perimetre,
          dans la limite `max_monitor_delay_minutes` depuis le debut du retard.
          Au-dela du plafond, l'allongement est seulement propose.
        - `confirm` : proposition de destruction, sans effet tant qu'une
          `ReleaseDecision` multisig ne l'a pas tranchee.

        Args:
            request: la demande de gel.

        Returns:
            L'action appliquee, inchangee ou proposee.
        """
        self.expire_due()
        actor = request.requested_by
        self._freeze_perimeter[request.request_id] = _key(request.perimeter_address)
        self._audit(
            actor=actor,
            event_type="freeze_request",
            subject_address=request.perimeter_address,
            related_tx_hash=self._tx_for(request.triggering_alert_id),
            payload={
                "request_id": request.request_id,
                "direction": request.direction.value,
                "extend_minutes": str(request.extend_minutes),
                "contamination_ratio": str(request.contamination_ratio),
                "suspect_amount": str(request.suspect_amount),
            },
            message=f"Demande de gel ({request.direction.value}) par {actor}",
        )

        if request.direction is FreezeDirection.CONFIRM:
            return self._propose_destroy(request)
        return self._extend(request)

    def apply_release(self, decision: ReleaseDecision) -> ResponseAction:
        """Applique une decision humaine multisig.

        - `release` avec perimetre : leve le retard du perimetre (quorum perimetre).
        - `release` sans perimetre : leve la pause globale (quorum global).
        - `confirm_freeze` : maintient le retard `confirmed_freeze_minutes`.
        - `confirm_destroy` : autorise la destruction de la fraction suspecte
          (`burn_ratio`) d'un perimetre retarde (RETARDE -> DETRUIT).
        - `global_pause` : decrete la pause globale (quorum global).

        Une decision invalide (quorum non atteint, signataire inconnu, etat
        incompatible) produit une action `rejected`, tracee dans l'audit.

        Args:
            decision: la decision humaine (multisig).

        Returns:
            L'action resultante (appliquee, expiree ou rejetee).
        """
        self.expire_due()
        self._audit(
            actor=MULTISIG_ACTOR,
            event_type="release_decision",
            subject_address=decision.perimeter_address,
            payload={
                "decision_id": decision.decision_id,
                "verdict": decision.verdict.value,
                "signers": str(len(decision.signers)),
                "threshold": str(decision.threshold),
                "related_freeze_id": str(decision.related_freeze_id),
                "burn_ratio": str(decision.burn_ratio),
            },
            message=f"Decision multisig {decision.verdict.value} : {decision.rationale}",
        )

        global_scope = decision.verdict is ReleaseVerdict.GLOBAL_PAUSE or (
            decision.verdict is ReleaseVerdict.RELEASE and decision.perimeter_address is None
        )
        quorum = (
            self._policy.required_global_quorum if global_scope else self._policy.perimeter_quorum
        )
        error = self._multisig_error(decision, quorum)
        if error is not None:
            return self._reject(decision, error)

        if decision.verdict is ReleaseVerdict.GLOBAL_PAUSE:
            return self._start_global_pause(decision)
        if global_scope:
            return self._end_global_pause(decision)
        if decision.perimeter_address is None:
            return self._reject(decision, "perimetre requis pour ce verdict")
        if decision.related_freeze_id is not None:
            linked = self._freeze_perimeter.get(decision.related_freeze_id)
            if linked is not None and linked != _key(decision.perimeter_address):
                return self._reject(decision, "related_freeze_id vise un autre perimetre")
        if decision.verdict is ReleaseVerdict.RELEASE:
            return self._release_perimeter(decision, decision.perimeter_address)
        if decision.verdict is ReleaseVerdict.CONFIRM_FREEZE:
            return self._confirm_freeze(decision, decision.perimeter_address)
        return self._destroy(decision, decision.perimeter_address)

    # ------------------------------------------------------------ #19 audit DORA

    def record_audit(
        self,
        action: ResponseAction,
        *,
        actor: str = "response",
        message: str | None = None,
    ) -> AuditLogEntry:
        """Journalise une action de reponse (conformite DORA).

        Args:
            action: l'action de reponse a tracer.
            actor: auteur de l'action (`monitor:<nom>`, `multisig`, ...).
            message: resume lisible ; genere a partir de l'action si absent.

        Returns:
            L'entree de journal d'audit creee (ajoutee au journal append-only).
        """
        payload = {
            "action_type": action.action_type.value,
            "status": action.status.value,
        }
        optional = {
            "expires_at": action.expires_at.isoformat() if action.expires_at else None,
            "triggering_alert_id": action.triggering_alert_id,
            "decision_id": action.decision_id,
            "contamination_ratio": (
                str(action.contamination_ratio)
                if action.contamination_ratio is not None
                else None
            ),
            "suspect_amount": (
                str(action.suspect_amount) if action.suspect_amount is not None else None
            ),
        }
        payload.update({k: v for k, v in optional.items() if v is not None})
        target = action.perimeter_address or "protocole (global)"
        return self._audit(
            actor=actor,
            event_type="response_action",
            subject_address=action.perimeter_address,
            related_action_id=action.action_id,
            related_tx_hash=self._tx_for(action.triggering_alert_id),
            payload=payload,
            message=message
            or f"{action.action_type.value} -> {action.status.value} sur {target}",
        )

    # --------------------------------------------------------------- expiration

    def expire_due(self) -> list[ResponseAction]:
        """Termine les retards arrives a echeance (silence = retour a la normale).

        Returns:
            Les actions `delay` passees en `expired` lors de cet appel.
        """
        now = self._now()
        expired: list[ResponseAction] = []
        for key, action_id in list(self._active_delays.items()):
            action = self._actions[action_id]
            if action.expires_at is not None and action.expires_at <= now:
                updated = self._store(
                    action.model_copy(update={"status": ResponseActionStatus.EXPIRED})
                )
                del self._active_delays[key]
                self._delay_started_at.pop(key, None)
                self.record_audit(
                    updated,
                    actor=AUTO_EXPIRY_ACTOR,
                    message=(
                        f"Retard expire sans decision humaine sur {updated.perimeter_address} : "
                        "retour automatique a la normale"
                    ),
                )
                expired.append(updated)
        return expired

    # ---------------------------------------------------------------- internes

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("L'horloge doit renvoyer un datetime UTC timezone-aware.")
        return now.astimezone(timezone.utc)

    def _tx_for(self, alert_id: str | None) -> str | None:
        return self._alert_tx.get(alert_id) if alert_id else None

    def _store(self, action: ResponseAction) -> ResponseAction:
        self._actions[action.action_id] = action
        return action

    def _audit(
        self,
        *,
        actor: str,
        event_type: str,
        payload: dict[str, str],
        message: str,
        subject_address: str | None = None,
        related_action_id: str | None = None,
        related_tx_hash: str | None = None,
    ) -> AuditLogEntry:
        entry = AuditLogEntry(
            entry_id=self._new_id("audit"),
            recorded_at=self._now(),
            actor=actor,
            event_type=event_type,
            subject_address=subject_address,
            related_action_id=related_action_id,
            related_tx_hash=related_tx_hash,
            payload=payload,
            message=message,
        )
        self._audit_log.append(entry)
        if self._audit_path is not None:
            with self._audit_path.open("a", encoding="utf-8") as sink:
                sink.write(entry.model_dump_json() + "\n")
        return entry.model_copy(deep=True)

    def _new_action(
        self,
        action_type: ResponseActionType,
        status: ResponseActionStatus,
        *,
        expires_at: datetime | None = None,
        perimeter_address: str | None = None,
        triggering_alert_id: str | None = None,
        decision_id: str | None = None,
        contamination_ratio: float | None = None,
        suspect_amount: int | None = None,
    ) -> ResponseAction:
        return self._store(
            ResponseAction(
                action_id=self._new_id("act"),
                action_type=action_type,
                status=status,
                created_at=self._now(),
                expires_at=expires_at,
                perimeter_address=perimeter_address,
                triggering_alert_id=triggering_alert_id,
                decision_id=decision_id,
                contamination_ratio=contamination_ratio,
                suspect_amount=suspect_amount,
            )
        )

    def _propose_delay(
        self,
        *,
        actor: str,
        address: str,
        alert_id: str | None,
        ratio: float,
        amount: int,
        minutes: int,
        message: str,
    ) -> ResponseAction:
        action = self._new_action(
            ResponseActionType.DELAY,
            ResponseActionStatus.PROPOSED,
            expires_at=self._now() + timedelta(minutes=minutes),
            perimeter_address=address,
            triggering_alert_id=alert_id,
            contamination_ratio=ratio,
            suspect_amount=amount,
        )
        self.record_audit(action, actor=actor, message=message)
        return action

    def _extend(self, request: FreezeRequest) -> ResponseAction:
        now = self._now()
        key = _key(request.perimeter_address)
        minutes = request.extend_minutes or self._policy.delay_minutes
        wanted = now + timedelta(minutes=minutes)
        started = self._delay_started_at.get(key, now)
        cap = started + timedelta(minutes=self._policy.max_monitor_delay_minutes)
        target = min(wanted, cap)
        capped = wanted > cap

        current_id = self._active_delays.get(key)
        if current_id is None:
            action = self._new_action(
                ResponseActionType.DELAY,
                ResponseActionStatus.APPLIED,
                expires_at=target,
                perimeter_address=request.perimeter_address,
                triggering_alert_id=request.triggering_alert_id,
                contamination_ratio=request.contamination_ratio,
                suspect_amount=request.suspect_amount,
            )
            self._active_delays[key] = action.action_id
            self._delay_started_at[key] = now
            self._destroyed.discard(key)
            note = " (plafonne)" if capped else ""
            self.record_audit(
                action,
                actor=request.requested_by,
                message=(
                    f"Retard applique sur {request.perimeter_address} jusqu'a "
                    f"{target.isoformat()}{note} : auto-expirant, conversion Ghost suspendue, "
                    "circulation autorisee"
                ),
            )
            return action

        current = self._actions[current_id]
        assert current.expires_at is not None
        if target <= current.expires_at:
            if capped:
                return self._propose_delay(
                    actor=request.requested_by,
                    address=request.perimeter_address,
                    alert_id=request.triggering_alert_id,
                    ratio=request.contamination_ratio,
                    amount=request.suspect_amount,
                    minutes=minutes,
                    message=(
                        f"Plafond d'allongement atteint sur {request.perimeter_address} : "
                        "au-dela, decision humaine (multisig) requise"
                    ),
                )
            self.record_audit(
                current,
                actor=request.requested_by,
                message=(
                    f"Retard deja en cours sur {request.perimeter_address} jusqu'a "
                    f"{current.expires_at.isoformat()} : aucun raccourcissement possible"
                ),
            )
            return current

        updated = self._store(
            current.model_copy(
                update={
                    "expires_at": target,
                    "contamination_ratio": max(
                        current.contamination_ratio or 0.0, request.contamination_ratio
                    ),
                    "suspect_amount": max(current.suspect_amount or 0, request.suspect_amount),
                }
            )
        )
        self.record_audit(
            updated,
            actor=request.requested_by,
            message=(
                f"Retard prolonge sur {request.perimeter_address} jusqu'a "
                f"{target.isoformat()}" + (" (plafonne)" if capped else "")
            ),
        )
        return updated

    def _propose_destroy(self, request: FreezeRequest) -> ResponseAction:
        action = self._new_action(
            ResponseActionType.DESTROY,
            ResponseActionStatus.PROPOSED,
            perimeter_address=request.perimeter_address,
            triggering_alert_id=request.triggering_alert_id,
            contamination_ratio=request.contamination_ratio,
            suspect_amount=request.suspect_amount,
        )
        self._proposals_by_freeze[request.request_id] = action.action_id
        self.record_audit(
            action,
            actor=request.requested_by,
            message=(
                f"Destruction proposee par {request.requested_by} sur "
                f"{request.perimeter_address} : sans effet tant que le multisig "
                f"({self._policy.perimeter_quorum} signatures) n'a pas tranche"
            ),
        )
        return action

    def _multisig_error(self, decision: ReleaseDecision, quorum: int) -> str | None:
        signers = [s.lower() for s in decision.signers]
        if len(set(signers)) != len(signers):
            return "signataire en double"
        unknown = [s for s in signers if s not in self._policy.guardians]
        if unknown:
            return f"signataire(s) non guardian : {len(unknown)}"
        required = max(quorum, decision.threshold)
        if len(signers) < required:
            return f"quorum non atteint ({len(signers)}/{required})"
        return None

    def _reject(self, decision: ReleaseDecision, reason: str) -> ResponseAction:
        verdict_type = {
            ReleaseVerdict.RELEASE: (
                ResponseActionType.GLOBAL_PAUSE
                if decision.perimeter_address is None
                else ResponseActionType.DELAY
            ),
            ReleaseVerdict.CONFIRM_FREEZE: ResponseActionType.DELAY,
            ReleaseVerdict.CONFIRM_DESTROY: ResponseActionType.DESTROY,
            ReleaseVerdict.GLOBAL_PAUSE: ResponseActionType.GLOBAL_PAUSE,
        }[decision.verdict]
        action = self._new_action(
            verdict_type,
            ResponseActionStatus.REJECTED,
            expires_at=self._now() if verdict_type is ResponseActionType.DELAY else None,
            perimeter_address=decision.perimeter_address,
            decision_id=decision.decision_id,
            contamination_ratio=decision.burn_ratio,
        )
        self.record_audit(
            action,
            actor=MULTISIG_ACTOR,
            message=f"Decision {decision.decision_id} rejetee : {reason}",
        )
        return action

    def _start_global_pause(self, decision: ReleaseDecision) -> ResponseAction:
        if self._global_pause_id is not None:
            current = self._actions[self._global_pause_id]
            self.record_audit(
                current, actor=MULTISIG_ACTOR, message="Pause globale deja active : inchangee"
            )
            return current
        action = self._new_action(
            ResponseActionType.GLOBAL_PAUSE,
            ResponseActionStatus.APPLIED,
            decision_id=decision.decision_id,
        )
        self._global_pause_id = action.action_id
        self.record_audit(
            action,
            actor=MULTISIG_ACTOR,
            message=(
                f"Pause globale decretee par multisig ({len(decision.signers)} signatures) : "
                "dernier recours, reversible par le meme quorum"
            ),
        )
        return action

    def _end_global_pause(self, decision: ReleaseDecision) -> ResponseAction:
        if self._global_pause_id is None:
            return self._reject(decision, "aucune pause globale active")
        current = self._actions[self._global_pause_id]
        updated = self._store(current.model_copy(update={"status": ResponseActionStatus.EXPIRED}))
        self._global_pause_id = None
        self.record_audit(
            updated,
            actor=MULTISIG_ACTOR,
            message=f"Pause globale levee par multisig (decision {decision.decision_id})",
        )
        return updated

    def _release_perimeter(self, decision: ReleaseDecision, address: str) -> ResponseAction:
        key = _key(address)
        action_id = self._active_delays.get(key)
        if action_id is None:
            return self._reject(decision, "aucun retard actif sur ce perimetre")
        updated = self._store(
            self._actions[action_id].model_copy(
                update={"status": ResponseActionStatus.EXPIRED, "decision_id": decision.decision_id}
            )
        )
        del self._active_delays[key]
        self._delay_started_at.pop(key, None)
        self.record_audit(
            updated,
            actor=MULTISIG_ACTOR,
            message=f"Retard leve par multisig sur {address} : retour a la normale",
        )
        return updated

    def _confirm_freeze(self, decision: ReleaseDecision, address: str) -> ResponseAction:
        key = _key(address)
        target = self._now() + timedelta(minutes=self._policy.confirmed_freeze_minutes)
        action_id = self._active_delays.get(key)
        if action_id is None:
            action = self._new_action(
                ResponseActionType.DELAY,
                ResponseActionStatus.APPLIED,
                expires_at=target,
                perimeter_address=address,
                decision_id=decision.decision_id,
            )
            self._active_delays[key] = action.action_id
            self._delay_started_at[key] = self._now()
            self._destroyed.discard(key)
        else:
            current = self._actions[action_id]
            assert current.expires_at is not None
            action = self._store(
                current.model_copy(
                    update={
                        "expires_at": max(current.expires_at, target),
                        "decision_id": decision.decision_id,
                    }
                )
            )
        assert action.expires_at is not None
        self.record_audit(
            action,
            actor=MULTISIG_ACTOR,
            message=(
                f"Retard confirme par multisig sur {address} jusqu'a "
                f"{action.expires_at.isoformat()} (toujours auto-expirant)"
            ),
        )
        return action

    def _destroy(self, decision: ReleaseDecision, address: str) -> ResponseAction:
        key = _key(address)
        delay_id = self._active_delays.get(key)
        if delay_id is None:
            return self._reject(decision, "destruction possible seulement depuis l'etat RETARDE")
        if decision.burn_ratio is None:
            return self._reject(decision, "burn_ratio requis pour confirm_destroy")
        delay = self._actions[delay_id]

        proposal_id = (
            self._proposals_by_freeze.get(decision.related_freeze_id)
            if decision.related_freeze_id
            else None
        )
        update = {
            "status": ResponseActionStatus.APPLIED,
            "decision_id": decision.decision_id,
            "contamination_ratio": decision.burn_ratio,
        }
        if proposal_id is not None:
            action = self._store(self._actions[proposal_id].model_copy(update=update))
        else:
            action = self._new_action(
                ResponseActionType.DESTROY,
                ResponseActionStatus.APPLIED,
                perimeter_address=address,
                triggering_alert_id=delay.triggering_alert_id,
                decision_id=decision.decision_id,
                contamination_ratio=decision.burn_ratio,
                suspect_amount=delay.suspect_amount,
            )

        self._store(delay.model_copy(update={"status": ResponseActionStatus.EXPIRED}))
        del self._active_delays[key]
        self._delay_started_at.pop(key, None)
        self._destroyed.add(key)
        self.record_audit(
            action,
            actor=MULTISIG_ACTOR,
            message=(
                f"Destruction de la fraction suspecte ({decision.burn_ratio:.2%} du Ghost non "
                f"converti) autorisee par multisig sur {address} : irreversible, burn on-chain"
            ),
        )
        return action
