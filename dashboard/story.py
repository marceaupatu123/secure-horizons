"""Demo interactive animee (#148) : logique pure + rendu HTML, sans Streamlit.

`build_story` extrait des resultats REELS des scenarios A et B (moteur #47) les
grandeurs a raconter ; `render_story_html` les injecte dans une page HTML autonome
(animations CSS/JS, aucune ressource externe). Aucun chiffre n'est code en dur :
tout vient du `ScenarioResult` (cf. docs/CLAIMS.md). Les fenetres Ghost affichees
sont les valeurs de demo de `dashboard/demo_data.py` (a mesurer).
"""

from __future__ import annotations

import json
from datetime import timedelta

from pydantic import BaseModel, ConfigDict

from dashboard.demo_data import DEMO_EXTENDED_WINDOW, DEMO_NORMAL_WINDOW
from dashboard.scenarios import ScenarioResult, ScenarioStatus, get_spec
from dashboard.scenarios.fuji_live import FujiRun, LiveState, address_url

JOURNAL_MAX_ENTRIES = 12
JOURNAL_DETAIL_MAX_CHARS = 160

# Acteur du journal d'audit -> (icone, nom lisible par un novice).
ACTOR_LABELS: dict[str, tuple[str, str]] = {
    "attacker": ("🕵️", "Le pirate"),
    "contract": ("📜", "Le contrat"),
    "monitor": ("📡", "Les surveillants"),
    "multisig": ("👥", "Les humains (multisig)"),
    "simulation": ("🧪", "Le trafic"),
}
DEFAULT_ACTOR = ("•", "Système")


class JournalLine(BaseModel):
    """Ligne du journal d'audit reel, traduite pour un public novice."""

    model_config = ConfigDict(extra="forbid")

    icon: str
    who: str
    detail: str


class StoryA(BaseModel):
    """Attaque 1 : cle volee, meme attaque sur contrat vulnerable et protege."""

    model_config = ConfigDict(extra="forbid")

    deposit: int
    vulnerable_minted: int
    vulnerable_loss: int
    protected_minted: int
    protected_loss: int
    banner: str


class StoryB(BaseModel):
    """Attaque 2 : pirate sous les plafonds, detection et reponse graduee."""

    model_config = ConfigDict(extra="forbid")

    contract_rejections: int | None
    alert_count: int | None
    detection_delay_seconds: float | None
    false_positive_count: int | None
    suspect_ghost_destroyed: int | None
    protocol_loss: int | None
    delayed_supply_share: float | None
    normal_window_minutes: int
    extended_window_minutes: int
    journal: list[JournalLine]
    banner: str


class FujiTx(BaseModel):
    """Transaction reelle Fuji, prete a afficher."""

    model_config = ConfigDict(extra="forbid")

    url: str


class FujiStep(BaseModel):
    """Etape intéressante d'un cas : commande de terminal + effet."""

    model_config = ConfigDict(extra="forbid")

    command: str
    actor: str
    contract: str
    contract_url: str
    narration: str
    effect: str
    outcome: str  # accepted | rejected | defended
    tx_urls: list[str]


class FujiCase(BaseModel):
    """Un cas de la démo Fuji : un titre, un verdict et ses étapes."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    subtitle: str
    outcome: str  # bad | good | window | resolved
    verdict: str
    steps: list[FujiStep]


class FujiLink(BaseModel):
    """Contrat avec son lien Snowtrace."""

    model_config = ConfigDict(extra="forbid")

    name: str
    address: str
    url: str


class FujiStory(BaseModel):
    """Rejeu en vraies transactions sur Avalanche Fuji, raconté en cas étape par étape."""

    model_config = ConfigDict(extra="forbid")

    recorded_at: str
    tx_count: int
    step_count: int
    cases: list[FujiCase]
    contracts: list[FujiLink]
    observed_mint_count: int
    live_block: int | None
    live_matches_record: bool | None


class Story(BaseModel):
    """Tout ce que la page anime, calcule a partir des resultats reels."""

    model_config = ConfigDict(extra="forbid")

    seed: int
    a: StoryA
    b: StoryB
    fuji: FujiStory | None = None


TOKEN_UNIT = 10**18
FUJI_CASE_META: dict[str, tuple[str, str, str]] = {
    "mint-passe": ("Le mint passe", "Contrat classique : la clé volée gagne", "bad"),
    "mint-bloque": ("Le mint est bloqué", "Secure Horizons : la clé volée ne gagne rien", "good"),
    "fenetre-reprise": ("La fenêtre de reprise", "Un échange donne du M-Ghost, pas du M-Coin",
                        "window"),
    "ghost-vendeur": ("Un vendeur de Ghost pose problème",
                      "On gèle, on détruit, on rembourse l'honnête", "resolved"),
}
FUJI_CASE_VERDICT: dict[str, str] = {
    "mint-passe": "✗ Sur un contrat classique, la clé volée a réussi : des jetons sans réserve ont "
                  "été créés.",
    "mint-bloque": "🛡️ Le mint gonflé est bloqué : la clé volée ne crée rien de plus que le dépôt "
                   "réel.",
    "fenetre-reprise": "⏳ Un échange donne d'abord du M-Ghost, PAS du M-Coin. Tant que la fenêtre "
                       "de sécurité n'est pas écoulée, tout est réversible — c'est le levier de "
                       "reprise. Au bout des 10 min sans anomalie, le M-Ghost arrive à échéance et "
                       "vaut du M-Coin 1:1, automatiquement : personne n'a à le décider.",
    "ghost-vendeur": "🛡️ Problème résolu on-chain : pendant la fenêtre, tout le Ghost suspect est "
                     "détruit et l'argent gelé rendu à l'acheteur honnête ; le vendeur finit à zéro.",
}
FUJI_CASE_ORDER = ("mint-passe", "mint-bloque", "fenetre-reprise", "ghost-vendeur")


def _tokens(amount: int) -> float:
    return amount / TOKEN_UNIT


def build_fuji_story(run: FujiRun, live: LiveState | None = None) -> FujiStory:
    """Traduit un rejeu Fuji (et, si fourni, l'etat relu a l'instant) pour la page."""
    cases: list[FujiCase] = []
    for case_id in FUJI_CASE_ORDER:
        steps = [FujiStep(command=s.command, actor=s.actor_label, contract=s.contract,
                          contract_url=s.contract_url, narration=s.narration, effect=s.effect,
                          outcome=s.outcome, tx_urls=list(s.tx_urls))
                 for s in run.steps if s.case == case_id]
        if not steps:
            continue
        title, subtitle, outcome = FUJI_CASE_META[case_id]
        cases.append(FujiCase(id=case_id, title=title, subtitle=subtitle, outcome=outcome,
                              verdict=FUJI_CASE_VERDICT[case_id], steps=steps))
    matches = None
    if live is not None:
        matches = (live.vulnerable_minted, live.seller_usdc_final) == (
            run.vulnerable_minted, run.seller_usdc_final)
    return FujiStory(
        recorded_at=run.finished_at.strftime("%d/%m/%Y %H:%M UTC"),
        tx_count=len(run.transactions),
        step_count=len(run.steps),
        cases=cases,
        contracts=[FujiLink(name=name, address=address, url=address_url(address))
                   for name, address in run.contracts.items()],
        observed_mint_count=len(run.observed_mints),
        live_block=None if live is None else live.block_number,
        live_matches_record=matches,
    )


def _value(result: ScenarioResult, variant: str, key: str) -> int | float | None:
    try:
        return result.metric(variant, key).value
    except KeyError:
        return None


def _int(value: int | float | None) -> int | None:
    return None if value is None else int(value)


def _minutes(window: timedelta) -> int:
    return int(window.total_seconds() // 60)


def _actor(actor: str) -> tuple[str, str]:
    return ACTOR_LABELS.get(actor.split(":", 1)[0], DEFAULT_ACTOR)


def _journal(result: ScenarioResult) -> list[JournalLine]:
    lines = []
    for entry in result.variants[0].dataset.audit_log[:JOURNAL_MAX_ENTRIES]:
        icon, who = _actor(entry.actor)
        detail = entry.message
        if len(detail) > JOURNAL_DETAIL_MAX_CHARS:
            detail = detail[: JOURNAL_DETAIL_MAX_CHARS - 1] + "…"
        lines.append(JournalLine(icon=icon, who=who, detail=detail))
    return lines


def _require_completed(result: ScenarioResult, scenario_id: str) -> None:
    if result.scenario_id != scenario_id:
        raise ValueError(f"résultat attendu pour {scenario_id}, reçu {result.scenario_id}")
    if result.status != ScenarioStatus.COMPLETED:
        raise ValueError(f"scénario {scenario_id} non terminé : {result.message}")


def build_story(result_a: ScenarioResult, result_b: ScenarioResult,
                fuji: FujiStory | None = None) -> Story:
    """Extrait les grandeurs mesurees de A et B (ValueError si un scenario n'a pas tourne)."""
    _require_completed(result_a, "A")
    _require_completed(result_b, "B")
    story_a = StoryA(
        deposit=int(_value(result_a, "vulnerable", "collateral") or 0),
        vulnerable_minted=int(_value(result_a, "vulnerable", "minted") or 0),
        vulnerable_loss=int(_value(result_a, "vulnerable", "protocol_loss") or 0),
        protected_minted=int(_value(result_a, "protected", "minted") or 0),
        protected_loss=int(_value(result_a, "protected", "protocol_loss") or 0),
        banner=get_spec("A").result_banner(result_a),
    )
    main = result_b.variants[0].name
    delay = _value(result_b, main, "detection_delay_seconds")
    share = _value(result_b, main, "delayed_supply_share")
    story_b = StoryB(
        contract_rejections=_int(_value(result_b, main, "contract_rejections")),
        alert_count=_int(_value(result_b, main, "alert_count")),
        detection_delay_seconds=None if delay is None else float(delay),
        false_positive_count=_int(_value(result_b, main, "false_positive_count")),
        suspect_ghost_destroyed=_int(_value(result_b, main, "suspect_ghost_destroyed")),
        protocol_loss=_int(_value(result_b, main, "protocol_loss")),
        delayed_supply_share=None if share is None else float(share),
        normal_window_minutes=_minutes(DEMO_NORMAL_WINDOW),
        extended_window_minutes=_minutes(DEMO_EXTENDED_WINDOW),
        journal=_journal(result_b),
        banner=get_spec("B").result_banner(result_b),
    )
    return Story(seed=result_a.seed, a=story_a, b=story_b, fuji=fuji)


def story_json(story: Story) -> str:
    """JSON injectable sans risque dans un <script> (pas de fermeture de balise possible)."""
    return (json.dumps(story.model_dump(), ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def render_story_html(story: Story) -> str:
    """Page HTML autonome animee ; les textes dynamiques passent par textContent (pas d'HTML)."""
    return _TEMPLATE.replace("__STORY_JSON__", story_json(story))


_TEMPLATE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<style>
:root{--bg:#0b1020;--panel:#141b33;--panel2:#1b2445;--text:#eef1fb;--muted:#9aa6c8;
--accent:#6ea8ff;--ok:#3ddc97;--bad:#ff5c7a;--warn:#ffc35c;--border:#2a3560}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:980px;margin:auto;padding:18px}
.tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.tab{flex:1;min-width:180px;padding:12px 14px;border-radius:12px;background:var(--panel);color:var(--text);
border:1px solid var(--border);cursor:pointer;font-size:15px;font-weight:600;text-align:left}
.tab small{display:block;color:var(--muted);font-weight:400;font-size:12px;margin-top:2px}
.tab[aria-selected=true]{background:var(--panel2);border-color:var(--accent);box-shadow:0 0 0 2px #6ea8ff33}
.act{display:none}.act.on{display:block;animation:fade .5s ease}
@keyframes fade{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
h2{margin:0 0 6px;font-size:26px}
.lead{color:var(--muted);margin:0 0 16px;font-size:15px;line-height:1.5}
.card{background:var(--panel);color:var(--text);border:1px solid var(--border);border-radius:14px;padding:16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:720px){.grid{grid-template-columns:1fr}}
.btn{background:var(--accent);color:#06102a;border:0;border-radius:10px;padding:11px 18px;font-size:15px;
font-weight:700;cursor:pointer}
.btn:disabled{opacity:.5;cursor:default}
.switch{display:inline-flex;background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:3px;gap:3px}
.switch button{background:transparent;color:var(--muted);border:0;border-radius:8px;padding:8px 12px;font-size:14px;cursor:pointer;font-weight:600}
.switch button[aria-pressed=true]{background:var(--bg);color:var(--text)}
.stage{position:relative;height:200px;border-radius:12px;background:linear-gradient(180deg,#121a36,#0d1328);
border:1px solid var(--border);overflow:hidden;margin:14px 0}
.vault,.printer{position:absolute;bottom:18px;text-align:center;font-size:13px;color:var(--muted)}
.vault{left:6%}.printer{right:6%}
.vault .ico,.printer .ico{font-size:52px;display:block}
.key{position:absolute;left:44%;top:30px;font-size:40px;opacity:0}
.key.go{animation:key 1.2s ease forwards}
@keyframes key{0%{opacity:0;transform:translate(-80px,0) rotate(-30deg)}40%{opacity:1}
100%{opacity:1;transform:translate(160px,60px) rotate(20deg)}}
.coin{position:absolute;font-size:22px;top:-30px;animation:fall 1.4s ease-in forwards}
@keyframes fall{to{transform:translateY(240px) rotate(360deg);opacity:.2}}
.shield{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) scale(0);font-size:70px;transition:transform .5s}
.shield.on{transform:translate(-50%,-50%) scale(1)}
.meter{height:22px;background:var(--panel2);border-radius:11px;overflow:hidden;margin:6px 0 2px;position:relative}
.meter i{display:block;height:100%;width:0;border-radius:11px;transition:width 2s cubic-bezier(.2,.8,.2,1)}
.lbl{font-size:12px;color:var(--muted)}
.big{font-size:30px;font-weight:800;font-variant-numeric:tabular-nums}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.verdict{margin-top:12px;padding:12px 14px;border-radius:12px;font-size:16px;font-weight:600;opacity:0;transition:opacity .6s}
.verdict.on{opacity:1}
.verdict.good{background:#3ddc9722;border:1px solid var(--ok)}.verdict.badv{background:#ff5c7a22;border:1px solid var(--bad)}
.clock{font-size:42px;font-weight:800;font-variant-numeric:tabular-nums}
.ghost{display:flex;align-items:center;gap:12px}
.ghost .g{font-size:46px;transition:transform .6s,opacity .6s,filter .6s}
.ghost .g.burn{transform:scale(1.4);opacity:0;filter:hue-rotate(-60deg)}
.win{flex:1}.win .meter i{background:linear-gradient(90deg,var(--accent),var(--warn))}
.feed{list-style:none;margin:0;padding:0;max-height:250px;overflow:auto}
.feed li{display:flex;gap:10px;padding:8px 4px;border-bottom:1px dashed var(--border);opacity:0;transform:translateX(-8px);transition:all .45s}
.feed li.on{opacity:1;transform:none}
.feed .who{font-weight:700;font-size:13px}.feed .det{font-size:12px;color:var(--muted)}
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}
@media(max-width:720px){.steps{grid-template-columns:1fr 1fr}}
.st{padding:10px;border-radius:10px;background:var(--panel2);border:1px solid var(--border);font-size:13px;opacity:.35;transition:all .5s}
.st.on{opacity:1;border-color:var(--accent)}
.st b{display:block;font-size:22px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:720px){.kpis{grid-template-columns:1fr 1fr}}
.kpi{text-align:center}.kpi .big{font-size:34px}
.foot{font-size:12px;color:var(--muted);margin-top:14px;line-height:1.5}
.badge{display:inline-block;font-size:11px;padding:3px 8px;border-radius:20px;background:var(--panel2);color:var(--muted);border:1px solid var(--border)}
.cases{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 14px}
.casebtn{flex:1;min-width:150px;text-align:left;padding:10px 12px;border-radius:10px;background:var(--panel2);
color:var(--text);border:1px solid var(--border);cursor:pointer;font-size:14px;font-weight:600}
.casebtn small{display:block;color:var(--muted);font-weight:400;font-size:11px;margin-top:2px}
.casebtn[aria-pressed=true]{border-color:var(--accent);box-shadow:0 0 0 2px #6ea8ff33}
.casebtn .pill{font-size:10px;padding:1px 7px;border-radius:20px;float:right}
.pill.bad{background:#ff5c7a22;color:var(--bad)}.pill.good{background:#3ddc9722;color:var(--ok)}
.pill.resolved{background:#6ea8ff22;color:var(--accent)}.pill.window{background:#ffc35c22;color:var(--warn)}
.termwrap{display:grid;grid-template-columns:1fr 230px;gap:14px}
@media(max-width:720px){.termwrap{grid-template-columns:1fr}}
.term{background:#060b18;border:1px solid var(--border);border-radius:12px;overflow:hidden;min-height:300px;display:flex;flex-direction:column}
.termbar{display:flex;gap:6px;align-items:center;padding:8px 12px;background:#0d1430;border-bottom:1px solid var(--border);font-size:12px;color:var(--muted)}
.termbar i{width:11px;height:11px;border-radius:50%;display:inline-block}
.termout{flex:1;padding:12px 14px;font-family:"SF Mono",Consolas,"Liberation Mono",monospace;font-size:13px;line-height:1.6;overflow:auto;max-height:340px}
.termline{white-space:pre-wrap;word-break:break-word}
.termcmd{color:var(--text)}.termcmd .pr{color:var(--ok)}
.termcmd .cur{color:var(--accent)}
.fx{display:block;margin:2px 0 10px;padding-left:2px}
.fx.accepted{color:var(--bad)}.fx.rejected{color:var(--ok)}.fx.defended{color:var(--ok)}
.fx a,.termline a{color:var(--accent)}
.cmdbtn{display:block;width:100%;text-align:left;margin-top:10px;padding:11px 13px;border-radius:10px;border:1px solid var(--accent);
background:var(--accent);color:#06102a;cursor:pointer;font-weight:700;font-size:13px}
.cmdbtn:disabled{opacity:.45;cursor:default}
.cmdbtn code{display:block;font-size:12px;font-weight:600;margin-top:4px;color:#06102a;opacity:.8;font-family:monospace}
.cmdbtn.done{background:var(--panel2);color:var(--muted);border-color:var(--border)}
.cmdbtn.done code{color:var(--muted)}
.rail{display:flex;flex-direction:column;gap:7px}
.rail .rlbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.rchip{padding:7px 9px;border-radius:9px;background:var(--panel);border:1px solid var(--border);font-size:12px;transition:all .3s}
.rchip.active{border-color:var(--accent);box-shadow:0 0 0 2px #6ea8ff33}
.rchip a{color:var(--accent)}.rchip .rt{display:block;font-size:10px;color:var(--muted)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="wrap">

<div class="tabs" role="tablist">
 <button class="tab" role="tab" data-t="f" aria-selected="true">⛓️ En vrai sur Avalanche<small>Vraies transactions, vérifiables</small></button>
 <button class="tab" role="tab" data-t="0" aria-selected="false">🔑 Acte 1 — La clé volée<small>Le pirate a le tampon officiel</small></button>
 <button class="tab" role="tab" data-t="1" aria-selected="false">🕵️ Acte 2 — Le pirate discret<small>Il joue petit pour passer inaperçu</small></button>
 <button class="tab" role="tab" data-t="2" aria-selected="false">📊 Le bilan<small>Ce qu'on a mesuré</small></button>
</div>

<section class="act on" data-a="f">
 <h2>La même attaque que Resolv, jouée pour de vrai sur Avalanche</h2>
 <p class="lead">Rien n'est simulé : nos contrats sont déployés sur le réseau de test d'Avalanche (Fuji).
 Choisis un cas, puis clique sur le bouton de chaque étape : la commande s'écrit dans le terminal
 et s'exécute pour de vrai. Chaque effet renvoie à sa transaction, vérifiable sur Snowtrace.</p>
 <div id="f-empty" class="card" style="display:none">Aucun rejeu Fuji enregistré pour l'instant :
 lancer <code>python -m dashboard.scenarios.fuji_live</code> (compte de test Fuji dans .env).</div>
 <div id="f-body">
  <span class="badge" id="f-live"></span>
  <div class="cases" id="f-cases" role="group" aria-label="Choix du cas"></div>
  <div class="termwrap">
   <div class="term">
    <div class="termbar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i>
     <span style="margin-left:8px" id="f-termtitle">terminal — Avalanche Fuji</span></div>
    <div class="termout" id="f-termout"></div>
   </div>
   <div>
    <div id="f-next"></div>
    <div class="rail" style="margin-top:14px"><span class="rlbl">Contrats en jeu</span>
     <div id="f-rail"></div></div>
   </div>
  </div>
  <div class="verdict" id="f-verdict"></div>
  <p class="foot">Réseau de test Avalanche Fuji (chain id 43113) : jetons de test sans valeur, schéma reproduit
  d'après l'incident Resolv (qui a eu lieu sur Ethereum). Dans le cas 3, <b>comment</b> le vendeur est repéré n'est
  pas divulgué ; geler, détruire et restituer passent par les vrais rôles on-chain des contrats.</p>
 </div>
</section>

<section class="act" data-a="0">
 <h2>Que se passe-t-il quand un pirate vole la clé ?</h2>
 <p class="lead">Imagine qu'un cambrioleur vole le <b>tampon officiel</b> d'une banque : tout billet qu'il tamponne
 paraît authentique. C'est exactement ce qui arrive quand la clé de signature d'un protocole est volée.
 Choisis le contrat, puis lance l'attaque.</p>
 <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
  <div class="switch" role="group" aria-label="Type de contrat">
   <button id="sw-v" aria-pressed="true">🔓 Contrat classique</button>
   <button id="sw-p" aria-pressed="false">🛡️ Secure Horizons</button>
  </div>
  <button class="btn" id="run-a">▶ Lancer l'attaque</button>
 </div>
 <div class="stage" id="stage" aria-hidden="true">
  <div class="vault"><span class="ico">🏦</span>Le coffre (vrais dépôts)</div>
  <div class="key" id="key">🔑</div>
  <div class="shield" id="shield">🛡️</div>
  <div class="printer"><span class="ico">🖨️</span>La planche à jetons</div>
 </div>
 <div class="grid">
  <div class="card"><div class="lbl">Argent réellement déposé dans le coffre</div>
   <div class="big" id="a-dep">—</div><div class="meter"><i id="m-dep" style="background:var(--ok)"></i></div></div>
  <div class="card"><div class="lbl">Jetons fabriqués par le pirate</div>
   <div class="big" id="a-mint">—</div><div class="meter"><i id="m-mint" style="background:var(--bad)"></i></div></div>
 </div>
 <div class="verdict" id="verdict-a"></div>
 <p class="foot">Pourquoi ça marche ? Comme un <b>distributeur de billets</b> : même avec ta carte, il ne te donne
 que ce qu'il y a sur ton compte. Chez nous, la signature dit seulement « traite la demande n°X » ;
 le montant, c'est le contrat qui le lit dans le coffre. <span class="badge" id="banner-a"></span></p>
</section>

<section class="act" data-a="1">
 <h2>Et si le pirate reste sous tous les plafonds ?</h2>
 <p class="lead">Plus malin, il ne vole qu'un peu à la fois : chaque opération est « légale », le contrat ne voit rien.
 C'est là qu'intervient le <b>Token Ghost</b> : comme un <b>chèque</b>, tout transfert donne d'abord un ticket
 échangeable, qui ne devient du vrai argent qu'après un délai <b>sans alarme</b>.</p>
 <button class="btn" id="run-b">▶ Rejouer l'attaque (vrai moteur de détection)</button>
 <div class="steps">
  <div class="st" id="s0"><b>🕵️</b>Le pirate vide le protocole petit à petit</div>
  <div class="st" id="s1"><b>📡</b>Les surveillants repèrent le motif</div>
  <div class="st" id="s2"><b>⏳</b>Ses tickets Ghost sont retenus plus longtemps</div>
  <div class="st" id="s3"><b>🔥</b>Des humains confirment : tickets détruits</div>
 </div>
 <div class="grid">
  <div class="card">
   <div class="lbl">Temps écoulé depuis le début de l'attaque</div>
   <div class="clock" id="clock">0:00</div>
   <div class="lbl" id="clock-note">Contrat seul : <span id="b-rej">—</span> opération bloquée</div>
   <div class="ghost" style="margin-top:12px"><span class="g" id="ghost">👻</span>
    <div class="win"><div class="lbl" id="win-lbl">Délai du ticket</div><div class="meter"><i id="m-win"></i></div></div></div>
  </div>
  <div class="card"><div class="lbl">Journal en direct (vrai journal d'audit de ce rejeu)</div>
   <ul class="feed" id="feed"></ul></div>
 </div>
 <div class="verdict" id="verdict-b"></div>
 <p class="foot">L'IA et les surveillants ne font que <b>retarder</b> (et ce retard expire tout seul) ;
 détruire des tickets exige l'accord de plusieurs humains. <span class="badge" id="banner-b"></span></p>
</section>

<section class="act" data-a="2">
 <h2>Une clé volée ne rapporte presque rien</h2>
 <p class="lead">Les chiffres ci-dessous viennent du rejeu qui vient de tourner. On ne promet que ce qu'on mesure.</p>
 <div class="kpis">
  <div class="card kpi"><div class="big ok" id="k-loss">—</div><div class="lbl">perte du protocole sur les deux attaques</div></div>
  <div class="card kpi"><div class="big" id="k-delay">—</div><div class="lbl">pour repérer le pirate discret</div></div>
  <div class="card kpi"><div class="big ok" id="k-fp">—</div><div class="lbl">fausse alerte sur des utilisateurs honnêtes</div></div>
  <div class="card kpi"><div class="big warn" id="k-share">—</div><div class="lbl">de l'offre ralentie au pic : le prix de la sécurité</div></div>
 </div>
 <div class="card" style="margin-top:14px">
  <div class="lbl">Contrat classique vs Secure Horizons — part des jetons émis sans argent derrière</div>
  <div style="margin-top:8px">🔓 Classique <span class="bad" id="k-vpct"></span><div class="meter"><i id="k-vbar" style="background:var(--bad)"></i></div></div>
  <div style="margin-top:8px">🛡️ Secure Horizons <span class="ok" id="k-ppct"></span><div class="meter"><i id="k-pbar" style="background:var(--ok)"></i></div></div>
 </div>
 <p class="foot" id="foot-c"></p>
</section>
</div>
<script>
(function(){
var S=__STORY_JSON__;
var RM=matchMedia('(prefers-reduced-motion: reduce)').matches;
function $(i){return document.getElementById(i)}
function fmt(n){return Math.round(n).toLocaleString('fr-FR')}
function pct(n,d){return d?100*n/d:0}
function pc(v){return (Math.round(v*10)/10).toString().replace('.',',')}
function mmss(s){s=Math.round(s);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')}
function count(el,to,ms,f){if(RM||!ms){el.textContent=f(to);return}var t0=null;
 (function step(ts){if(!t0)t0=ts;var p=Math.min((ts-t0)/ms,1);el.textContent=f(to*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(step)})(performance.now())}
function later(fn,ms){return setTimeout(fn,RM?0:ms)}
// Onglets
var tabs=[].slice.call(document.querySelectorAll('.tab')),acts=[].slice.call(document.querySelectorAll('.act'));
tabs.forEach(function(t){t.onclick=function(){var k=t.dataset.t;tabs.forEach(function(x){x.setAttribute('aria-selected',x===t)});
 acts.forEach(function(a){a.classList.toggle('on',a.dataset.a===k)});if(k==='2')bilan()}});
// En vrai sur Fuji — terminal étape par étape
var F=S.fuji;
function link(url,text){var a=document.createElement('a');if(url.indexOf('https://testnet.snowtrace.io/')===0)a.href=url;
 a.target='_blank';a.rel='noopener noreferrer';a.textContent=text;return a}
if(!F){$('f-empty').style.display='block';$('f-body').style.display='none';}
else{
 $('f-live').textContent=F.live_block===null?('rejeu enregistré le '+F.recorded_at+' · '+F.tx_count+' transactions'):
  (F.live_matches_record?'✔ état relu à l\u2019instant sur Fuji (bloc '+fmt(F.live_block)+') : identique au rejeu':'état relu sur Fuji (bloc '+fmt(F.live_block)+')');
 var curCase=null,stepIdx=0,typing=false,out=$('f-termout');
 // Boutons de cas
 F.cases.forEach(function(c){var b=document.createElement('button');b.className='casebtn';b.setAttribute('aria-pressed','false');
  var names={bad:'✗ échec',good:'✓ bloqué',window:'⏳ réversible',resolved:'✓ résolu'};
  var pill='<span class="pill '+c.outcome+'">'+(names[c.outcome]||'')+'</span>';
  b.innerHTML=pill+'<b>'+c.title+'</b><small>'+c.subtitle+'</small>';b.onclick=function(){selectCase(c)};$('f-cases').appendChild(b)});
 function typeCmd(cmd,done){var pr='<span class="pr">fuji$</span> ';var el=document.createElement('div');el.className='termline termcmd';
  out.appendChild(el);if(RM){el.innerHTML=pr+cmd;done();return}typing=true;var i=0;
  (function tick(){el.innerHTML=pr+cmd.slice(0,i)+'<span class="cur">▋</span>';i++;
   if(i<=cmd.length){setTimeout(tick,16)}else{el.innerHTML=pr+cmd;typing=false;out.scrollTop=out.scrollHeight;done()}})()}
 function printEffect(step){var fx=document.createElement('div');fx.className='fx '+step.outcome;
  fx.appendChild(document.createTextNode(step.effect+' '));
  step.tx_urls.forEach(function(u,i){fx.appendChild(link(u,i?'(tx '+(i+1)+')':'↗ voir la transaction'));
   if(i<step.tx_urls.length-1)fx.appendChild(document.createTextNode(' '))});
  out.appendChild(fx);out.scrollTop=out.scrollHeight}
 function renderRail(active){var r=$('f-rail');r.innerHTML='';F.contracts.forEach(function(c){var d=document.createElement('div');
  d.className='rchip'+(c.name===active?' active':'');var a=link(c.url,c.name);var t=document.createElement('span');t.className='rt';
  t.textContent=c.address.slice(0,10)+'…';d.appendChild(a);d.appendChild(t);r.appendChild(d)})}
 function renderNext(){var box=$('f-next');box.innerHTML='';if(!curCase)return;
  if(stepIdx>=curCase.steps.length){var v=$('f-verdict');v.className='verdict '+(curCase.outcome==='bad'?'badv':'good')+' on';
   v.textContent=curCase.verdict;
   return}
  var s=curCase.steps[stepIdx];var b=document.createElement('button');b.className='cmdbtn';
  b.innerHTML=s.narration+'<code>▶ '+s.command+'</code>';b.disabled=typing;b.onclick=function(){runStep()};box.appendChild(b)}
 function runStep(){if(typing||!curCase||stepIdx>=curCase.steps.length)return;var s=curCase.steps[stepIdx];
  renderRail(s.contract);$('f-next').innerHTML='';
  typeCmd(s.command,function(){printEffect(s);stepIdx++;renderNext()})}
 function selectCase(c){curCase=c;stepIdx=0;typing=false;out.innerHTML='';$('f-verdict').className='verdict';
  [].forEach.call($('f-cases').children,function(b,i){b.setAttribute('aria-pressed',F.cases[i]===c)});
  var intro=document.createElement('div');intro.className='termline';intro.style.color='var(--muted)';
  intro.textContent='# '+c.title+' — '+c.subtitle+'. Clique le bouton pour exécuter chaque étape.';
  out.appendChild(intro);renderRail(null);renderNext()}
 selectCase(F.cases[0]);
}
// Acte 1
var A=S.a,prot=false;$('banner-a').textContent=A.banner+' · seed '+S.seed;
function setSw(p){prot=p;$('sw-v').setAttribute('aria-pressed',!p);$('sw-p').setAttribute('aria-pressed',p);resetA()}
$('sw-v').onclick=function(){setSw(false)};$('sw-p').onclick=function(){setSw(true)};
function units(n){return A.deposit?n/A.deposit:0}
function resetA(){$('a-dep').textContent='1 part';$('a-mint').textContent='—';$('m-dep').style.width='0';$('m-mint').style.width='0';
 $('verdict-a').className='verdict';$('key').className='key';$('shield').className='shield';
 [].slice.call(document.querySelectorAll('.coin')).forEach(function(c){c.remove()})}
$('run-a').onclick=function(){resetA();var b=this;b.disabled=true;
 var minted=prot?A.protected_minted:A.vulnerable_minted,loss=prot?A.protected_loss:A.vulnerable_loss,r=units(minted);
 void $('key').offsetWidth;$('key').className='key go';
 later(function(){if(prot){$('shield').className='shield on'}else{var st=$('stage');
  for(var i=0;i<28;i++){(function(i){later(function(){var c=document.createElement('div');c.className='coin';c.textContent='🪙';
   c.style.left=(55+Math.random()*38)+'%';st.appendChild(c)},i*55)})(i)}}
  $('m-dep').style.width=Math.max(1,100/Math.max(r,1))+'%';$('m-mint').style.width=(prot?Math.max(1,100/Math.max(r,1)):100)+'%';
  count($('a-mint'),r,1800,function(v){return fmt(v)+(Math.round(v)>1?' parts':' part')});
 },1100);
 later(function(){var v=$('verdict-a');if(loss===0){v.className='verdict good on';
  v.textContent='🛡️ Attaque neutralisée : le pirate n\u2019a pu créer que ce qui était vraiment déposé. Perte du protocole : 0.'}
  else{v.className='verdict badv on';v.textContent='💥 Le protocole est vidé : '+pc(pct(loss,minted))+' % des jetons émis n\u2019ont aucun argent derrière.'}
  b.disabled=false},3200)};
resetA();
// Acte 2
var B=S.b;$('banner-b').textContent=B.banner+' · seed '+S.seed;$('b-rej').textContent=B.contract_rejections===null?'non mesuré':fmt(B.contract_rejections);
var feed=$('feed');B.journal.forEach(function(j){var li=document.createElement('li'),i=document.createElement('span'),d=document.createElement('div'),w=document.createElement('div'),t=document.createElement('div');
 i.textContent=j.icon;w.className='who';w.textContent=j.who;t.className='det';t.textContent=j.detail;d.appendChild(w);d.appendChild(t);li.appendChild(i);li.appendChild(d);feed.appendChild(li)});
var timers=[];function clearB(){timers.forEach(clearTimeout);timers=[]}
function resetB(){clearB();for(var k=0;k<4;k++)$('s'+k).className='st';$('clock').textContent='0:00';$('ghost').className='g';
 $('m-win').style.width=(100*B.normal_window_minutes/B.extended_window_minutes)+'%';$('win-lbl').textContent='Délai normal du ticket : '+B.normal_window_minutes+' min';
 $('verdict-b').className='verdict';[].forEach.call(feed.children,function(li){li.className=''})}
$('run-b').onclick=function(){resetB();var btn=this;btn.disabled=true;var lis=feed.children,n=lis.length,delay=B.detection_delay_seconds||0;
 function at(ms,fn){timers.push(later(fn,ms))}
 at(100,function(){$('s0').className='st on'});
 count($('clock'),delay,RM?0:3000,mmss);
 for(var i=0;i<n;i++){(function(i){at(300+i*(5200/Math.max(n,1)),function(){lis[i].className='on';lis[i].scrollIntoView({block:'nearest'})})})(i)}
 at(3100,function(){$('s1').className='st on'});
 at(3900,function(){$('s2').className='st on';$('m-win').style.width='100%';$('win-lbl').textContent='Délai allongé : '+B.extended_window_minutes+' min (le pirate ne peut pas encaisser)'});
 at(5600,function(){$('s3').className='st on';$('ghost').className='g burn'});
 at(6200,function(){var v=$('verdict-b'),ok=B.protocol_loss===0;v.className='verdict '+(ok?'good':'badv')+' on';
  v.textContent=(ok?'✅ Pirate repéré en '+mmss(delay)+' min, ses tickets Ghost détruits avant conversion. Perte du protocole : 0.':'Perte du protocole : '+fmt(B.protocol_loss||0)+' base units.');btn.disabled=false});
};
resetB();
// Bilan
function bilan(){var loss=(A.protected_loss||0)+(B.protocol_loss||0);count($('k-loss'),loss,900,fmt);
 $('k-delay').textContent=B.detection_delay_seconds===null?'non mesuré':'~'+Math.round(B.detection_delay_seconds/60)+' min';
 $('k-fp').textContent=B.false_positive_count===null?'non mesuré':fmt(B.false_positive_count);
 $('k-share').textContent=B.delayed_supply_share===null?'non mesuré':B.delayed_supply_share.toFixed(1).replace('.',',')+' %';
 var vp=pct(A.vulnerable_loss,A.vulnerable_minted),pp=pct(A.protected_loss,A.protected_minted);
 $('k-vpct').textContent=pc(vp)+' %';$('k-ppct').textContent=pc(pp)+' %';
 $('k-vbar').style.width='0';$('k-pbar').style.width='0';later(function(){$('k-vbar').style.width=vp+'%';$('k-pbar').style.width=Math.max(pp,0.5)+'%'},80);
 $('foot-c').textContent='Données synthétiques et fictives (seed '+S.seed+'). Acte 1 : '+A.banner+'. Acte 2 : '+B.banner+'. Résultats testés et mesurés sur ce rejeu, pas des garanties.'}
})();
</script></body></html>"""


__all__ = [
    "FujiStory",
    "JournalLine",
    "Story",
    "StoryA",
    "StoryB",
    "build_fuji_story",
    "build_story",
    "render_story_html",
    "story_json",
]
