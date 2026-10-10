# response

- **Rôle** : orchestration de la **réponse graduée** (machine à états actée en `docs/OPEN_ANSWERS.md` §3 / §9) : **retard** auto-expirant sur alerte, **décisions humaines multisig** (lever, confirmer, détruire, pause globale), **journal d'audit DORA** append-only.
- **Propriétaire** : @EnzoFB06 (voir `docs/TEAM.md`).
- **Lancer** : `python -m response` (démo fictive, affiche le journal d'audit ; `--audit-jsonl PATH` pour l'exporter) ; tests : `python -m pytest response/`.

## Ce que fait `ResponseOrchestrator`

```
NORMAL --(alerte)--> RETARDÉ --(expiration, silence)--> NORMAL
                        |--(multisig 2/3)--> DÉTRUIT
                        '--(multisig 3/3)--> PAUSE_GLOBALE (levée par le même quorum)
```

| Méthode | Qui | Effet |
|---------|-----|-------|
| `handle_alert(alert)` | surveillant / IA | retarde le sujet et chaque graine (`Alert.seeds`) ; sous `auto_delay_min_severity`, retard seulement **proposé** |
| `request_freeze(req)` | surveillant / IA | `extend` : allonge, jamais ne raccourcit, plafonné à `max_monitor_delay_minutes` depuis le début du retard (au-delà : proposé). `confirm` : **proposition** de destruction, sans effet |
| `apply_release(decision)` | multisig humain | `release` (retard ou pause globale), `confirm_freeze`, `confirm_destroy` (uniquement depuis RETARDÉ, `burn_ratio` requis), `global_pause`. Quorum non atteint, signataire inconnu ou en double → action `rejected` tracée |
| `record_audit(action)` | — | entrée `AuditLogEntry` ajoutée au journal (copie JSONL optionnelle) |
| `expire_due()` | horloge | retards échus → `expired`, retour à la normale (appelé au début de chaque méthode) |

L'IA ne peut **que retarder** : aucune méthode accessible à un surveillant ne détruit ni ne met en pause.

## Limites assumées

- **Miroir hors chaîne** : la fenêtre Ghost, le burn et le multisig réel vivent dans le contrat. Le multisig est **simulé** ici (vérification de `ReleaseDecision.signers` contre `ResponsePolicy.guardians`, sans cryptographie).
- Le **budget de quarantaine** (§9, part max de l'offre sous retard) n'est pas appliqué ici : l'orchestrateur ne connaît pas les soldes Ghost. Il relève du contrat / fuzzing (#6).

## Valeurs par défaut — à mesurer, pas actées

| Paramètre | Défaut | Source |
|-----------|--------|--------|
| `delay_minutes` | 60 | §3, « proposition de référence » (10 min → 1 h) |
| `max_monitor_delay_minutes` | 60 | §3 « facteur fixe et modeste » ; valeur à mesurer |
| `confirmed_freeze_minutes` | 60 | choix d'implémentation, à valider |
| `auto_delay_min_severity` | `warning` | choix d'implémentation, à valider |
| `perimeter_quorum` | 2 | §3 (détruire 2/3) ; appliqué aussi à lever / confirmer un retard, à valider |
| `global_pause_quorum` | unanimité | §3 (3/3) |
