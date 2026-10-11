"""Recalcul retroactif du lignage hors chaine -> `list[AlertSeed]` (#106, suite #85).

Decision `docs/OPEN_ANSWERS.md` §11 (piste b, recalcul hors chaine + racine de
Merkle). Quand une alerte designe une origine frauduleuse *apres* que la valeur
a deja circule, son ratio de contamination (§9) valait 0 au moment des ventes :
le soupcon n'a pas suivi la chaine. Ce module **rejoue les transferts publics**
depuis l'entree de la valeur dans le Ghost (`t0`), **comme si** l'origine avait
ete marquee suspecte a `t0`, et en deduit le soupcon retroactif de chaque
**detenteur actuel**, plafonne par son solde Ghost non converti.

Modele reutilise (aucune invention locale) :

- **Contamination par ratio (§9).** On ne suit pas des pieces. Chaque adresse
  porte un unique montant suspect absolu ; a chaque transfert, le montant envoye
  porte le **ratio courant de l'expediteur** (`suspect / solde_ghost`), et le
  destinataire accumule ce soupcon (moyenne ponderee par les montants). Le
  soupcon est **conserve** : fractionner et disperser ne nettoie pas. C'est le
  meme modele que `data.ghost_ledger` (reference hors chaine, #25) et que la
  mesure `data.late_marking` (#95).
- **Arrondi `ceilDiv` (design #8, OpenZeppelin `Math.ceilDiv`).** Le montant
  suspect derive d'un ratio est arrrondi a l'unite **superieure** (sens sur :
  aucune poussiere suspecte n'echappe a la destruction, coherent avec
  `GhostLedger.burn_suspect`). `ceil_div(a, b) == (a + b - 1) // b` pour `b > 0`.
- **Plafond par solde Ghost non converti (§9).** Le soupcon retroactif d'un
  detenteur ne depasse jamais ce qu'il detient *encore* en Ghost : un Ghost deja
  converti avant le gel est hors d'atteinte (irreversible et voulu, §9).
- **Restitutions (§10bis point 4).** Si les Ghost de **paiement** des graines
  sont fournis, on produit en plus la liste de restitution : d'abord aux
  porteurs dont le M' a ete brule dans ce lot, au prorata du montant brule et
  **plafonne par ce qu'ils avaient paye** ; le reste a celui qui avait paye le
  voleur (l'origine). Format fige par §10bis / #84 : feuille
  `(adresse, lot, montant_detruit, montant_restitue)`.

Lots (§11 / #106) : les graines sont **livrees par lots de 64 au maximum** par
semis (`seed_batches`).

Pas d'effet de bord, typage complet, aucune dependance nouvelle : on ne lit que
`shared.models` et la bibliotheque standard.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from shared.models import AlertSeed, TransferEvent

#: Nombre maximal de graines (`AlertSeed`) livrees par semis (#106, §11).
MAX_SEEDS_PER_BATCH = 64

#: Adresse zero EVM : destination canonique d'une conversion/burn Ghost. Un
#: transfert *vers* un sink (conversion Ghost -> vrai token, burn) sort la valeur
#: du lignage et ne produit jamais de graine (B1 de la review #112, §9).
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def ceil_div(numerator: int, denominator: int) -> int:
    """Division entiere plafond (`Math.ceilDiv` du design #8, OpenZeppelin).

    Le meme arrondi que le contrat Ghost : le montant suspect derive d'un ratio
    est pousse a l'unite superieure, de sorte qu'aucune poussiere suspecte ne
    survive a la destruction.

    Args:
        numerator: dividende, >= 0.
        denominator: diviseur, > 0.

    Returns:
        Le plus petit entier >= `numerator / denominator`.

    Raises:
        ValueError: si `denominator <= 0` ou `numerator < 0`.
    """
    if denominator <= 0:
        raise ValueError("denominator doit etre > 0")
    if numerator < 0:
        raise ValueError("numerator doit etre >= 0")
    if numerator == 0:
        return 0
    return (numerator + denominator - 1) // denominator


@dataclass(frozen=True)
class _Holder:
    """Etat retroactif d'une adresse pendant le rejeu.

    Attributes:
        ghost: solde Ghost non converti reconstruit depuis le rejeu (base units).
        suspect: montant suspect absolu porte par l'adresse (base units).
    """

    ghost: int = 0
    suspect: int = 0


@dataclass(frozen=True)
class Restitution:
    """Une feuille de restitution (§10bis point 4, format §11 / #84).

    Attributes:
        address: adresse remboursee.
        amount: montant restitue (base units), plafonne par ce qui a ete paye.
    """

    address: str
    amount: int


def _normalise(address: str) -> str:
    """Clef de compte insensible a la casse EVM (comme `detector.py`)."""
    return address.lower()


def _merge_normalised(mapping: dict[str, int]) -> dict[str, int]:
    """Normalise les clefs d'adresse (casse) en cumulant les montants doublons.

    Deux clefs qui ne different que par la casse (`0xAB...` et `0xab...`)
    designent la meme adresse EVM : on les fusionne pour qu'elles ne produisent
    pas deux feuilles distinctes (mineur de la review #112).
    """
    merged: defaultdict[str, int] = defaultdict(int)
    for address, value in mapping.items():
        merged[_normalise(address)] += value
    return dict(merged)


def _replay_order_key(event: TransferEvent) -> tuple[int, int, datetime]:
    """Clef de tri du rejeu : `(block_number, log_index)` puis `observed_at`.

    `observed_at` seul ne departage pas deux transferts du meme bloc ou de la
    meme transaction (mineur de la review #112). `TransferEvent` porte toujours
    `block_number`/`log_index` (on-chain), donc on trie d'abord dessus — ordre
    canonique de la chaine — et on garde `observed_at` en depart final stable.
    """
    return (event.block_number, event.log_index, event.observed_at)


def retroactive_seeds(
    transfers: list[TransferEvent],
    origin_address: str,
    origin_amount: int,
    now: datetime,
    *,
    sinks: frozenset[str] = frozenset({ZERO_ADDRESS}),
    initial_balances: dict[str, int] | None = None,
    ghost_balance_of: Callable[[str], int] | None = None,
) -> list[AlertSeed]:
    """Recalcule le soupcon retroactif de chaque detenteur actuel du lot frauduleux.

    Rejoue `transfers` (par ordre on-chain `(block_number, log_index)`, les plus
    anciens d'abord, `observed_at` en depart final) **comme si** `origin_address`
    avait porte `origin_amount` de soupcon des `t0` (entree de la valeur dans le
    Ghost). A chaque transfert Ghost, le montant envoye porte le ratio courant de
    l'expediteur (§9) et le destinataire accumule ce soupcon ; le soupcon derive
    est arrondi en `ceilDiv` (design #8). Le soupcon final de chaque adresse est
    **plafonne par son solde Ghost non converti** reconstruit depuis le rejeu
    (§9 : un Ghost deja converti est hors d'atteinte).

    Plafond par la verite on-chain (§14, option (c), decision 2026-10-11). Le
    rejeu seul **peut surestimer** le solde d'un detenteur : le monitor n'emet
    pas les burns/conversions Ghost (`Ghost -> 0x0`), donc un porteur qui a deja
    converti garde dans le rejeu un **solde fictif** et recevrait une graine pour
    du Ghost qu'il ne detient plus (c'est exactement le trou §14). Quand
    `ghost_balance_of` est fourni, le solde final de chaque detenteur est
    **plafonne par son vrai solde on-chain** `min(solde_reconstruit,
    ghost_balance_of(addr))` : c'est la verite de la chaine au moment du semis,
    et c'est l'option (c) retenue (§14). L'appelant branche `ghost_balance_of`
    sur un vrai `balanceOf` du contrat Ghost — **une lecture RPC par graine** ;
    le module ne lit lui-meme aucune chaine (callback injectable, deterministe
    et testable hors ligne). Quand `ghost_balance_of` est `None`, le
    comportement est **inchange** (retrocompatibilite) : seul le rejeu borne le
    solde, qui peut donc surestimer (le trou §14 reste ouvert dans ce mode).

    Les transferts sont supposes **publics et complets** (§11, hypothese
    explicite). Seuls les transferts Ghost (`is_ghost=True`) propagent le
    soupcon : un transfert de vrai token (`is_ghost=False`) ne porte pas de
    Ghost et n'est donc pas rejoue dans le lignage.

    Sinks (B1, review #112). Une conversion Ghost -> vrai token (ou un burn)
    apparait comme un transfert Ghost **vers un sink** (`ZERO_ADDRESS` par
    defaut, ou le contrat de conversion). La valeur et le soupcon envoyes vers
    un sink **sortent du lignage** : ils ne restent pas atteignables et un sink
    ne produit **jamais** d'`AlertSeed`. Sinon un Ghost deja converti produirait
    quand meme une graine (sur `0x0...0`), ce qui contredirait §9.

    Emission (mint / emission Ghost, review #112, decision 2026-10-10). Depuis
    que **tout transfert emet du Ghost**, un mint apparait comme un transfert
    Ghost **depuis un sink** (`Transfer(0x0 -> x, is_ghost=True)`, ce que le
    monitor produit depuis #116). La valeur emise est **nouvelle et non
    suspecte** : un transfert dont l'expediteur est un sink credite le
    destinataire **sans soupcon**, avant la garde B2. Sans cette regle, un sink
    expediteur (`held = 0`, `amount > 0`) ferait lever la garde `amount > held`
    sur tout flux reel contenant un mint apres `t0`.

    Conservation du soupcon (B2, review #112, §9). Le rejeu ne connait que le
    lot frauduleux. Si un expediteur detient aussi du Ghost **non suivi** (recu
    avant `t0` ou hors rejeu), son solde reconstruit deviendrait negatif
    (`amount > held`) et le soupcon serait silencieusement perdu, ou le ratio
    surestime. Deux issues, selon `initial_balances` :

    - `initial_balances` **fourni** (hypothese §11, soldes de depart connus) :
      les soldes de depart des adresses sont pre-charges, donc le solde
      reconstruit ne devient pas negatif et la conservation est respectee ;
    - `initial_balances` **absent ou incomplet** et un solde reconstruit
      deviendrait negatif : on leve `ValueError` explicite plutot que de fausser
      silencieusement le resultat. **Jamais de resultat silencieusement faux.**

    La feuille Merkle (#84) s'appuie sur `suspect_amount` (entier, exact) et non
    sur `contamination_ratio` (flottant, affichage seulement).

    Args:
        transfers: evenements de transfert publics observes (Ghost ou non).
        origin_address: adresse de l'origine frauduleuse (graine a `t0`).
        origin_amount: montant frauduleux entre dans le Ghost a `t0` (base
            units, > 0).
        now: horodatage courant (UTC) ; borne le rejeu aux transferts
            `observed_at <= now`.
        sinks: adresses de sortie (conversion/burn) ; un transfert vers l'une
            d'elles sort du lignage et ne produit jamais de graine. Defaut :
            `{ZERO_ADDRESS}`. Casse normalisee comme le reste du module.
        initial_balances: soldes Ghost de depart connus par adresse (base
            units). S'il est fourni, les expediteurs ne deviennent pas negatifs
            (hypothese §11). Casse normalisee a l'entree.
        ghost_balance_of: callback optionnel `addr -> solde Ghost on-chain`
            (base units) lu au moment du semis (§14, option (c)). S'il est
            fourni, le solde final de chaque detenteur est plafonne par
            `min(solde_reconstruit, ghost_balance_of(addr))` — la verite de la
            chaine, qui ferme le trou §14 (un porteur ayant converti, dont le
            vrai solde vaut 0, ne recoit aucune graine). L'appelant le branche
            sur un vrai `balanceOf` du contrat Ghost (**une lecture RPC par
            graine**) ; `None` conserve le comportement actuel (rejeu seul,
            retrocompatible), qui peut surestimer. Appele avec l'adresse
            normalisee (casse minuscule), uniquement pour les detenteurs
            candidats a une graine (sinks exclus).

    Returns:
        La liste des `AlertSeed` des detenteurs actuels dont le soupcon
        retroactif est > 0, chacun porte par son solde Ghost non converti,
        **sinks exclus**. Triee par montant suspect decroissant puis par adresse
        (deterministe).

    Raises:
        ValueError: si `origin_amount <= 0`, si un solde reconstruit devient
            negatif (`amount > held`) sans `initial_balances` suffisant (B2), ou
            si `ghost_balance_of` renvoie un solde negatif.
    """
    if origin_amount <= 0:
        raise ValueError("origin_amount doit etre > 0")

    origin = _normalise(origin_address)
    normalised_sinks = frozenset(_normalise(s) for s in sinks)
    # Soldes Ghost et soupcon absolu par adresse, reconstruits par le rejeu.
    ghost: defaultdict[str, int] = defaultdict(int)
    suspect: defaultdict[str, int] = defaultdict(int)

    # Soldes de depart connus (B2, hypothese §11) : pre-charges avant t0 pour
    # qu'un expediteur a solde preexistant non suivi ne devienne pas negatif.
    if initial_balances is not None:
        for address, balance in initial_balances.items():
            if balance < 0:
                raise ValueError("initial_balances : soldes >= 0 requis")
            ghost[_normalise(address)] += balance

    # t0 : l'origine detient `origin_amount` de Ghost, entierement suspect.
    ghost[origin] += origin_amount
    suspect[origin] += origin_amount

    ordered = sorted(
        (t for t in transfers if t.observed_at <= now),
        key=_replay_order_key,
    )
    for event in ordered:
        if not event.is_ghost:
            # Un transfert de vrai token ne porte pas de Ghost : hors lignage.
            continue
        sender = _normalise(event.sender)
        recipient = _normalise(event.recipient)
        amount = event.amount
        held = ghost[sender]
        if sender in normalised_sinks:
            # Emission : un transfert dont l'expediteur est un sink (`0x0` ->
            # x) est un mint / une emission de Ghost (decision 2026-10-10 : tout
            # transfert emet du Ghost ; c'est ce que le monitor produit depuis
            # #116). La valeur est **nouvelle, non suspecte** : on credite le
            # destinataire sans soupcon, avant la garde B2. Sans cela, pour un
            # expediteur sink `held = 0` et la garde `amount > held` leverait
            # sur tout flux reel contenant un mint apres t0. Un transfert
            # sink -> sink (p. ex. 0x0 -> contrat de burn) ne credite personne.
            if recipient not in normalised_sinks:
                ghost[recipient] += amount
            continue
        if amount > held:
            # B2 (§9) : le solde reconstruit deviendrait negatif. Sans solde de
            # depart connu couvrant ce transfert, on refuse plutot que de perdre
            # le soupcon ou de surestimer le ratio. Jamais de resultat faux.
            raise ValueError(
                "solde Ghost reconstruit negatif pour "
                f"{sender} (amount={amount} > held={held}) : fournir "
                "initial_balances (hypothese §11) ou corriger le rejeu"
            )
        if held <= 0:
            # L'expediteur ne detient aucun Ghost : amount vaut 0 ici (sinon la
            # garde B2 au-dessus aurait leve). Rien a deplacer.
            continue
        moved = amount
        # Ratio courant de l'expediteur, applique en ceilDiv (design #8) : part
        # suspecte du montant deplace, bornee par le soupcon detenu.
        sent_suspect = min(
            suspect[sender], ceil_div(suspect[sender] * moved, held)
        )
        ghost[sender] = held - amount
        suspect[sender] = max(0, suspect[sender] - sent_suspect)
        if recipient in normalised_sinks:
            # B1 : la valeur sort du lignage (conversion/burn). Le soupcon
            # envoye vers un sink n'est plus atteignable : on ne le propage pas
            # et le sink ne portera jamais de graine.
            continue
        ghost[recipient] += amount
        suspect[recipient] += sent_suspect

    seeds: list[AlertSeed] = []
    for address, balance in ghost.items():
        if address in normalised_sinks:
            # B1 : un sink ne produit jamais de graine, quel que soit son solde.
            continue
        if balance <= 0:
            continue
        # Plafond par la verite on-chain (§14, option (c)). Le solde reconstruit
        # par le rejeu peut surestimer (une conversion Ghost -> 0x0 n'est pas
        # emise par le monitor, cf. §14). Quand `ghost_balance_of` est fourni, on
        # borne le solde par le vrai solde on-chain lu au semis : un porteur qui
        # a deja converti (balanceOf == 0) ne produit alors AUCUNE graine. Sans
        # callback, seul le rejeu borne (comportement historique, retrocompat).
        if ghost_balance_of is not None:
            onchain = ghost_balance_of(address)
            if onchain < 0:
                raise ValueError(
                    f"ghost_balance_of({address}) doit etre >= 0, recu {onchain}"
                )
            balance = min(balance, onchain)
            if balance <= 0:
                continue
        # Plafond par solde Ghost non converti (§9) : le soupcon ne peut depasser
        # ce que l'adresse detient encore (deja borne par la verite on-chain
        # ci-dessus quand `ghost_balance_of` est fourni).
        capped = min(suspect[address], balance)
        if capped <= 0:
            continue
        seeds.append(
            AlertSeed(
                address=address,
                suspect_amount=capped,
                contamination_ratio=min(1.0, capped / balance),
            )
        )
    seeds.sort(key=lambda s: (-s.suspect_amount, s.address))
    return seeds


def seed_batches(
    seeds: list[AlertSeed], batch_size: int = MAX_SEEDS_PER_BATCH
) -> list[list[AlertSeed]]:
    """Decoupe une liste de graines en lots de `batch_size` au maximum (#106, §11).

    Les semis sont envoyes par lots bornes (64 par defaut). L'ordre des graines
    est preserve ; aucun lot n'est vide, aucun ne depasse `batch_size`.

    Args:
        seeds: graines a decouper (p. ex. la sortie de `retroactive_seeds`).
        batch_size: taille maximale d'un lot, > 0 (defaut `MAX_SEEDS_PER_BATCH`).

    Returns:
        La liste des lots, dans l'ordre. Liste vide si `seeds` est vide.

    Raises:
        ValueError: si `batch_size <= 0`.
    """
    if batch_size <= 0:
        raise ValueError("batch_size doit etre > 0")
    return [seeds[i : i + batch_size] for i in range(0, len(seeds), batch_size)]


def restitutions_for_burn(
    burned_by_address: dict[str, int],
    paid_by_address: dict[str, int],
    thief_payment_ghost: int,
    payer_of_thief: str | None = None,
) -> list[Restitution]:
    """Liste de restitution d'un lot detruit (§10bis point 4, format §11 / #84).

    A la destruction confirmee (multisig 2/3, §3), l'argent bloque derriere le
    Ghost de paiement du voleur n'a jamais ete a lui : il est restitue selon une
    regle fixe et verifiable :

    1. **d'abord** aux porteurs dont le M' a ete brule dans ce lot, au prorata du
       montant brule, **plafonne par ce qu'ils avaient paye** ;
    2. **le reste**, s'il y en a, a **celui qui avait paye le voleur**
       (`payer_of_thief`, p. ex. l'origine ou son acheteur direct).

    La restitution totale est bornee par `thief_payment_ghost` (l'argent bloque
    du voleur) ; on ne cree jamais de fonds et le protocole ne garde rien.

    Args:
        burned_by_address: montant de M' brule par adresse dans ce lot (base
            units) ; typiquement derive des `AlertSeed` graines detruites. Clefs
            normalisees a l'entree (casse insensible, comme `payer_of_thief`).
        paid_by_address: montant que chaque adresse avait **paye** on-chain
            (plafond de sa restitution). Clefs normalisees a l'entree.
        thief_payment_ghost: argent bloque derriere le Ghost de paiement du
            voleur, disponible a la restitution (base units, >= 0).
        payer_of_thief: adresse ayant paye le voleur, destinataire du reliquat.
            None = le reliquat n'est pas attribue (reste dans le coffre selon
            §10bis point 3, aucune sortie vers le protocole).

    Returns:
        Les feuilles de restitution (montant > 0), triees par adresse
        (deterministe).

    Raises:
        ValueError: si `thief_payment_ghost < 0` ou un montant brule/paye < 0.
    """
    if thief_payment_ghost < 0:
        raise ValueError("thief_payment_ghost doit etre >= 0")
    for name, mapping in (("burned", burned_by_address), ("paid", paid_by_address)):
        if any(v < 0 for v in mapping.values()):
            raise ValueError(f"{name}_by_address : montants >= 0 requis")

    # Normalisation de casse a l'entree (meme regle que `payer_of_thief`) : une
    # meme adresse en casse differente ne doit pas donner deux feuilles. Les
    # montants d'une meme adresse normalisee sont cumules.
    burned_by_address = _merge_normalised(burned_by_address)
    paid_by_address = _merge_normalised(paid_by_address)

    total_burned = sum(burned_by_address.values())
    remaining = thief_payment_ghost
    payouts: defaultdict[str, int] = defaultdict(int)

    if total_burned > 0 and remaining > 0:
        # 1. Prorata du montant brule, plafonne par ce qui a ete paye.
        #    Repartition entiere deterministe : part theorique par floor, le
        #    reliquat d'arrondi aux plus gros brules d'abord (ordre stable).
        order = sorted(
            burned_by_address,
            key=lambda a: (-burned_by_address[a], a),
        )
        theoretical = {
            a: remaining * burned_by_address[a] // total_burned for a in order
        }
        leftover = remaining - sum(theoretical.values())
        for addr in order:
            if leftover == 0:
                break
            theoretical[addr] += 1
            leftover -= 1
        for addr in order:
            cap = paid_by_address.get(addr, 0)
            pay = min(theoretical[addr], cap, remaining)
            if pay > 0:
                payouts[addr] += pay
                remaining -= pay

    # 2. Le reste a celui qui avait paye le voleur.
    if remaining > 0 and payer_of_thief is not None:
        payouts[_normalise(payer_of_thief)] += remaining
        remaining = 0

    return sorted(
        (Restitution(address=a, amount=amt) for a, amt in payouts.items() if amt > 0),
        key=lambda r: r.address,
    )


def retroactive_recovery_total(seeds: Iterable[AlertSeed]) -> int:
    """Total du M' recupere par le lignage retroactif (somme des soupcons des graines).

    Mesure de couverture comparable a la fraction recuperee de
    `data.late_marking` (#95) : sur la chaine des 40 de §10bis, detection avant
    echeance, cette somme vaut 100 % du M' encore en Ghost.

    Args:
        seeds: graines produites par `retroactive_seeds`.

    Returns:
        La somme des montants suspects (base units).
    """
    return sum(seed.suspect_amount for seed in seeds)
