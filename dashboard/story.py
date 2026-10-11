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

    who: str
    label: str
    url: str
    success: bool


class FujiStep(BaseModel):
    """Etape du rejeu Fuji et ses transactions."""

    model_config = ConfigDict(extra="forbid")

    name: str
    txs: list[FujiTx]


class FujiLink(BaseModel):
    """Contrat ou compte avec son lien Snowtrace."""

    model_config = ConfigDict(extra="forbid")

    name: str
    address: str
    url: str


class FujiStory(BaseModel):
    """Rejeu en vraies transactions sur Avalanche Fuji (montants en jetons, 18 decimales)."""

    model_config = ConfigDict(extra="forbid")

    recorded_at: str
    tx_count: int
    steps: list[FujiStep]
    contracts: list[FujiLink]
    deposit_tokens: float
    signed_tokens: float
    vulnerable_minted_tokens: float
    vulnerable_collateral_tokens: float
    protected_minted_tokens: float
    protected_collateral_tokens: float
    inflated_rejected: bool
    attacker_ghost_before_tokens: float
    attacker_ghost_after_tokens: float
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
FUJI_ACTORS: dict[str, str] = {
    "admin": "🏗️ L'équipe",
    "attacker": "🕵️ Le pirate (clé volée)",
    "watcher": "📡 Le surveillant",
    "guardian1": "👥 Gardien 1",
    "guardian2": "👥 Gardien 2",
    "guardian3": "👥 Gardien 3",
    "whale": "🙂 Un utilisateur honnête",
}


def _tokens(amount: int) -> float:
    return amount / TOKEN_UNIT


def build_fuji_story(run: FujiRun, live: LiveState | None = None) -> FujiStory:
    """Traduit un rejeu Fuji (et, si fourni, l'etat relu a l'instant) pour la page."""
    steps: list[FujiStep] = []
    for record in run.transactions:
        if not steps or steps[-1].name != record.step:
            steps.append(FujiStep(name=record.step, txs=[]))
        steps[-1].txs.append(FujiTx(who=FUJI_ACTORS.get(record.actor, record.actor),
                                    label=record.label, url=record.url, success=record.success))
    matches = None
    if live is not None:
        matches = (live.vulnerable_minted, live.protected_minted, live.attacker_ghost) == (
            run.vulnerable_minted, run.protected_minted, run.attacker_ghost_after)
    return FujiStory(
        recorded_at=run.finished_at.strftime("%d/%m/%Y %H:%M UTC"),
        tx_count=len(run.transactions),
        steps=steps,
        contracts=[FujiLink(name=name, address=address, url=address_url(address))
                   for name, address in run.contracts.items()],
        deposit_tokens=_tokens(run.deposit),
        signed_tokens=_tokens(run.signed_amount),
        vulnerable_minted_tokens=_tokens(run.vulnerable_minted),
        vulnerable_collateral_tokens=_tokens(run.vulnerable_collateral),
        protected_minted_tokens=_tokens(run.protected_minted),
        protected_collateral_tokens=_tokens(run.protected_collateral),
        inflated_rejected=run.protected_inflated_rejected,
        attacker_ghost_before_tokens=_tokens(run.attacker_ghost_before),
        attacker_ghost_after_tokens=_tokens(run.attacker_ghost_after),
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
 <p class="lead">Ici, rien n'est simulé : nous avons déployé nos contrats sur le réseau de test d'Avalanche
 (Fuji) et un « pirate » a utilisé une <b>vraie clé volée</b> pour signer un mint de
 <b id="f-mult">—</b>. Chaque ligne ci-dessous est une transaction réelle : clique pour la vérifier
 sur l'explorateur public Snowtrace.</p>
 <div id="f-empty" class="card" style="display:none">Aucun rejeu Fuji enregistré pour l'instant :
 lancer <code>python -m dashboard.scenarios.fuji_live</code> (compte de test Fuji dans .env).</div>
 <div id="f-body">
  <button class="btn" id="run-f">▶ Rejouer la chronologie réelle</button>
  <span class="badge" id="f-live" style="margin-left:8px"></span>
  <div class="grid" style="margin-top:14px">
   <div class="card"><div class="lbl">🔓 Contrat classique — jetons créés pour <span id="f-dep1"></span> USDC déposés</div>
    <div class="big bad" id="f-vmint">—</div><div class="meter"><i id="f-vbar" style="background:var(--bad)"></i></div>
    <div class="lbl" id="f-vnote"></div></div>
   <div class="card"><div class="lbl">🛡️ Secure Horizons — jetons créés pour <span id="f-dep2"></span> USDC déposés</div>
    <div class="big ok" id="f-pmint">—</div><div class="meter"><i id="f-pbar" style="background:var(--ok)"></i></div>
    <div class="lbl" id="f-pnote"></div></div>
  </div>
  <div class="card" style="margin-top:14px">
   <div class="ghost"><span class="g" id="f-ghost">👻</span>
    <div class="win"><div class="lbl">Ghost (ticket) détenu par le pirate</div>
     <div class="big" id="f-gval">—</div></div></div>
  </div>
  <div class="card" style="margin-top:14px"><div class="lbl">Chronologie réelle sur Fuji (<span id="f-count"></span> transactions)</div>
   <ul class="feed" id="f-feed" style="max-height:330px"></ul></div>
  <div class="verdict" id="f-verdict"></div>
  <p class="foot"><b>Contrats déployés :</b> <span id="f-contracts"></span><br>
  Réseau de test Avalanche Fuji (chain id 43113) : jetons de test sans valeur, attaque reproduite d'après le schéma
  de l'incident Resolv (qui, lui, a eu lieu sur Ethereum). Le signal de réponse (tentative de mint gonflé rejetée)
  est une règle de démo ; retarder et détruire passent par les vrais rôles on-chain du contrat Ghost.</p>
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
// En vrai sur Fuji
var F=S.fuji;
function link(url,text){var a=document.createElement('a');if(url.indexOf('https://testnet.snowtrace.io/')===0)a.href=url;
 a.target='_blank';a.rel='noopener noreferrer';a.style.color='var(--accent)';a.textContent=text;return a}
function tok(n){return fmt(n)}
if(!F){$('f-empty').style.display='block';$('f-body').style.display='none';$('f-mult').textContent='mille fois son dépôt'}
else{
 var mult=F.deposit_tokens?Math.round(F.signed_tokens/F.deposit_tokens):0;
 $('f-mult').textContent=fmt(mult)+' fois son dépôt';$('f-dep1').textContent=tok(F.deposit_tokens);$('f-dep2').textContent=tok(F.deposit_tokens);
 $('f-count').textContent=F.tx_count;
 $('f-live').textContent=F.live_block===null?('rejeu enregistré le '+F.recorded_at):
  (F.live_matches_record?'✔ état relu à l\u2019instant sur Fuji (bloc '+fmt(F.live_block)+') : identique':'état relu sur Fuji (bloc '+fmt(F.live_block)+')');
 var cs=$('f-contracts');F.contracts.forEach(function(c,i){if(i)cs.appendChild(document.createTextNode(' · '));cs.appendChild(link(c.url,c.name))});
 var ff=$('f-feed'),items=[];
 F.steps.forEach(function(s){var h=document.createElement('li');var b=document.createElement('div');b.className='who';b.style.color='var(--accent)';
  b.textContent=s.name;h.appendChild(b);ff.appendChild(h);items.push(h);
  s.txs.forEach(function(t){var li=document.createElement('li'),i=document.createElement('span'),d=document.createElement('div'),w=document.createElement('div'),x=document.createElement('div');
   i.textContent=t.success?'✅':'⛔';w.className='who';w.textContent=t.who;x.className='det';x.appendChild(document.createTextNode(t.label+' — '));
   x.appendChild(link(t.url,t.success?'voir la transaction':'voir le rejet on-chain'));d.appendChild(w);d.appendChild(x);li.appendChild(i);li.appendChild(d);ff.appendChild(li);items.push(li)})});
 var ftimers=[];
 function resetF(){ftimers.forEach(clearTimeout);ftimers=[];items.forEach(function(li){li.className=''});$('f-vmint').textContent='—';$('f-pmint').textContent='—';
  $('f-vbar').style.width='0';$('f-pbar').style.width='0';$('f-vnote').textContent='';$('f-pnote').textContent='';$('f-ghost').className='g';
  $('f-gval').textContent='—';$('f-verdict').className='verdict'}
 function stepAt(name){var idx=0;for(var k=0;k<items.length;k++){if(items[k].firstChild&&items[k].firstChild.textContent===name){idx=k;break}}return idx}
 $('run-f').onclick=function(){resetF();var btn=this,per=RM?0:260;btn.disabled=true;
  items.forEach(function(li,k){ftimers.push(later(function(){li.className='on';li.scrollIntoView({block:'nearest'})},k*per))});
  var tA=stepAt('Attaque n°1 : contrat classique')*per+4*per,tB=stepAt('Attaque n°2 : contrat Secure Horizons')*per+9*per,
   tR=stepAt('Réponse : le surveillant retarde, les humains détruisent')*per;
  ftimers.push(later(function(){count($('f-vmint'),F.vulnerable_minted_tokens,1600,tok);$('f-vbar').style.width='100%';
   $('f-vnote').textContent='Le contrat a cru la signature : '+fmt(F.vulnerable_minted_tokens-F.vulnerable_collateral_tokens)+' jetons sans aucun argent derrière.'},tA));
  ftimers.push(later(function(){count($('f-pmint'),F.deposit_tokens,1200,tok);$('f-pbar').style.width=Math.max(0.6,100*F.deposit_tokens/Math.max(F.vulnerable_minted_tokens,1))+'%';
   $('f-gval').textContent=tok(F.attacker_ghost_before_tokens)+' jetons Ghost';
   $('f-pnote').textContent=(F.inflated_rejected?'Mint gonflé rejeté par le contrat. ':'')+'Le pirate ne reçoit que son propre dépôt, et en Ghost.'},tB));
  ftimers.push(later(function(){$('f-ghost').className='g burn';$('f-gval').textContent=tok(F.attacker_ghost_after_tokens)+' jeton Ghost (détruit par 2 gardiens sur 3)'},tR+3*per));
  ftimers.push(later(function(){var v=$('f-verdict'),ok=F.protected_minted_tokens<=F.protected_collateral_tokens;v.className='verdict '+(ok?'good':'badv')+' on';
   v.textContent=ok?'🛡️ Sur la vraie blockchain : le contrat classique a créé '+fmt(F.vulnerable_minted_tokens)+' jetons pour '+fmt(F.deposit_tokens)+' USDC. Secure Horizons : chaque jeton reste adossé à un vrai dépôt, et le Ghost du pirate a été détruit.':'Écart détecté entre jetons et dépôts.';
   btn.disabled=false},items.length*per+300));
 };
 resetF();
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
