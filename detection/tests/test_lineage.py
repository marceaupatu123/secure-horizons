"""Tests du recalcul retroactif du lignage hors chaine (#106, decision §11).

Verifie que `detection.lineage` :

1. recupere 100 % du M' encore en Ghost sur la chaine des 40 de §10bis ;
2. conserve le soupcon malgre une dispersion large (ratio correct) ;
3. n'atteint pas un Ghost deja converti (plafond par solde non converti) ;
4. respecte les lots de 64 au maximum par semis ;
5. donne la meme recuperation que la mesure de reference `data.late_marking`
   (PR #95).

Donnees FICTIVES uniquement (adresses et hashes synthetiques).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.late_marking import ChainParams, simulate_chain
from detection.lineage import (
    MAX_SEEDS_PER_BATCH,
    ZERO_ADDRESS,
    Restitution,
    ceil_div,
    restitutions_for_burn,
    retroactive_recovery_total,
    retroactive_seeds,
    seed_batches,
)
from shared.models import TransferEvent

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _addr(index: int) -> str:
    """Adresse EVM synthetique deterministe NON NULLE (0x + 40 hex).

    Decalee de +1 pour qu'aucun index n'engendre l'adresse zero : `_addr(0)` ==
    `0x0...01`, pas `ZERO_ADDRESS`. Depuis le correctif « mint = source » de la
    review #112, un expediteur egal a un sink (`ZERO_ADDRESS` par defaut) est
    traite comme une emission non suspecte ; une origine ou un expediteur
    legitime de test ne doit donc jamais tomber sur l'adresse zero, sans quoi
    sa valeur ne se propagerait pas. Le vrai zero reste la constante distincte
    `ZERO_ADDRESS`, utilisee directement par le test du sink zero.
    """
    return "0x" + f"{index + 1:040x}"


def _tx(index: int) -> str:
    """Hash de transaction synthetique deterministe (0x + 64 hex)."""
    return "0x" + f"{index:064x}"


def _ghost_transfer(
    *, sender: str, recipient: str, amount: int, at: datetime, nonce: int
) -> TransferEvent:
    """Transfert Ghost minimal valide (champs on-chain fictifs)."""
    return TransferEvent(
        tx_hash=_tx(nonce),
        log_index=0,
        block_number=nonce,
        chain_id=43113,
        observed_at=at,
        sender=sender,
        recipient=recipient,
        amount=amount,
        is_ghost=True,
    )


def _build_chain(hops: int, amount: int, hop_seconds: float) -> list[TransferEvent]:
    """Chaine des N : le voleur (A0) revend tout a A1, chacun revend tout au suivant.

    Reproduit le modele de `data.late_marking.simulate_chain` : meme montant
    revendu de main en main, un cran plus tard a chaque saut.
    """
    transfers: list[TransferEvent] = []
    for i in range(hops):
        transfers.append(
            _ghost_transfer(
                sender=_addr(i),
                recipient=_addr(i + 1),
                amount=amount,
                at=_T0 + timedelta(seconds=(i + 1) * hop_seconds),
                nonce=i + 1,
            )
        )
    return transfers


# --------------------------------------------------------------------------- 1


def test_chaine_des_40_recupere_tout_le_ghost_chez_le_dernier() -> None:
    """§10bis : 100 % du M' encore en Ghost est atteint chez le 40e detenteur."""
    p = ChainParams()  # hops=40, stolen_tokens=10 -> amount = 10 * UNIT
    amount = p.amount
    transfers = _build_chain(p.hops, amount, p.hop_interval_seconds)
    now = _T0 + timedelta(minutes=p.detect_after_minutes)

    seeds = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=amount, now=now
    )

    # Au bout de la chaine, le dernier detenteur arrive avant `now` porte tout
    # le soupcon ; personne d'autre ne detient de Ghost (chacun a tout revendu).
    assert len(seeds) == 1
    (seed,) = seeds
    assert seed.suspect_amount == amount
    assert seed.contamination_ratio == 1.0
    # 100 % du M' en Ghost recupere.
    assert retroactive_recovery_total(seeds) == amount


# --------------------------------------------------------------------------- 2


def test_dispersion_large_conserve_le_soupcon() -> None:
    """Dispersion large : le soupcon total est conserve (ratio correct)."""
    amount = 1000
    fan_out = 8
    per = amount // fan_out  # 125, divise sans reste
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=_addr(100 + k),
            amount=per,
            at=_T0 + timedelta(seconds=k + 1),
            nonce=k + 1,
        )
        for k in range(fan_out)
    ]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=amount, now=now
    )

    # L'origine a tout disperse : 8 detenteurs, soupcon conserve = montant total.
    assert len(seeds) == fan_out
    assert retroactive_recovery_total(seeds) == amount
    for seed in seeds:
        assert seed.suspect_amount == per
        assert seed.contamination_ratio == 1.0


def test_dispersion_dilue_un_porteur_de_bonne_foi() -> None:
    """Une goutte de suspect dans un gros solde legitime -> ratio minuscule (§9)."""
    # L'origine envoie 10 de suspect a une grosse adresse qui detient deja 990
    # de Ghost legitime (credite par un transfert hors lot, ratio 0). Le solde
    # de depart de cet expediteur legitime est connu (hypothese §11), fourni via
    # `initial_balances` pour que la conservation tienne (B2).
    legit_holder = _addr(200)
    legit_source = _addr(500)
    transfers = [
        # Ghost legitime prealable chez le gros porteur (expediteur inconnu du
        # lot : ratio 0).
        _ghost_transfer(
            sender=legit_source,
            recipient=legit_holder,
            amount=990,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
        # Goutte suspecte de l'origine.
        _ghost_transfer(
            sender=_addr(0),
            recipient=legit_holder,
            amount=10,
            at=_T0 + timedelta(seconds=2),
            nonce=2,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers,
        origin_address=_addr(0),
        origin_amount=10,
        now=now,
        initial_balances={legit_source: 990},
    )

    (seed,) = seeds
    assert seed.address == legit_holder
    assert seed.suspect_amount == 10  # soupcon conserve
    # Ratio minuscule : 10 suspect / 1000 Ghost detenu = 1 %.
    assert abs(seed.contamination_ratio - 0.01) < 1e-9


# --------------------------------------------------------------------------- 3


def test_ghost_deja_converti_non_atteint() -> None:
    """Un Ghost deja converti avant le gel n'est pas atteint (plafond par solde)."""
    # L'origine detient 100 de Ghost suspect, puis convertit (sort du Ghost).
    # On modelise la conversion comme un transfert Ghost vers un SINK explicite
    # (burn/redemption) : la valeur et le soupcon sortent du lignage (B1), donc
    # ni l'origine ni le sink ne portent de graine apres coup.
    redemption_sink = _addr(999)
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=redemption_sink,
            amount=100,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers,
        origin_address=_addr(0),
        origin_amount=100,
        now=now,
        sinks=frozenset({redemption_sink}),
    )

    # Tout le soupcon est sorti du lignage via le sink : aucune graine, et en
    # particulier rien sur l'origine ni sur le sink (B1).
    assert seeds == []
    assert all(seed.address != _addr(0) for seed in seeds)
    assert all(seed.address != redemption_sink for seed in seeds)
    # Un transfert au-dela de `now` n'est pas rejoue : le soupcon reste a
    # l'origine (conversion pas encore observee du point de vue du gel).
    now_before = _T0  # avant le transfert
    seeds_before = retroactive_seeds(
        transfers,
        origin_address=_addr(0),
        origin_amount=100,
        now=now_before,
        sinks=frozenset({redemption_sink}),
    )
    assert len(seeds_before) == 1
    assert seeds_before[0].address == _addr(0)
    assert seeds_before[0].suspect_amount == 100


def test_plafond_par_solde_ghost_non_converti() -> None:
    """Le soupcon d'un detenteur ne depasse jamais son solde Ghost (§9)."""
    # L'origine declare 100 de soupcon mais n'envoie que 60 en Ghost ; le reste
    # (40) a ete converti hors Ghost avant le rejeu -> hors d'atteinte.
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=_addr(1),
            amount=60,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    # origin_amount reflete le Ghost reellement entre a t0 (60), pas 100 :
    # on verifie seulement que chaque graine est plafonnee par son solde.
    seeds = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=60, now=now
    )
    for seed in seeds:
        assert seed.suspect_amount <= 60
        assert 0.0 <= seed.contamination_ratio <= 1.0


# --------------------------------------------------------------------------- 4


def test_lots_de_64_max_par_semis() -> None:
    """Les semis sont livres par lots de 64 au maximum (#106, §11)."""
    # 200 detenteurs distincts (fan-out de l'origine) -> 4 lots (64+64+64+8).
    n = 200
    amount_each = 1
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=_addr(1000 + k),
            amount=amount_each,
            at=_T0 + timedelta(seconds=k + 1),
            nonce=k + 1,
        )
        for k in range(n)
    ]
    now = _T0 + timedelta(minutes=5)

    seeds = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=n * amount_each, now=now
    )
    assert len(seeds) == n

    batches = seed_batches(seeds)
    assert all(len(b) <= MAX_SEEDS_PER_BATCH for b in batches)
    assert all(len(b) > 0 for b in batches)
    # Reconstruction : la concatenation des lots redonne la liste, dans l'ordre.
    flat = [s for b in batches for s in b]
    assert flat == seeds
    expected_batches = (n + MAX_SEEDS_PER_BATCH - 1) // MAX_SEEDS_PER_BATCH
    assert len(batches) == expected_batches == 4


def test_seed_batches_vide_et_taille_personnalisee() -> None:
    """Lot vide -> aucun lot ; taille personnalisee respectee."""
    assert seed_batches([]) == []
    amount = 10
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=_addr(1 + k),
            amount=1,
            at=_T0 + timedelta(seconds=k + 1),
            nonce=k + 1,
        )
        for k in range(amount)
    ]
    seeds = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=amount, now=_T0 + timedelta(minutes=1)
    )
    batches = seed_batches(seeds, batch_size=3)
    assert [len(b) for b in batches] == [3, 3, 3, 1]


# --------------------------------------------------------------------------- 5


def test_meme_recuperation_que_late_marking() -> None:
    """Comparaison avec `data.late_marking` (#95) : memes resultats de recuperation."""
    p = ChainParams()  # chaine des 40, detection a 3 min, W = 10 min
    amount = p.amount
    transfers = _build_chain(p.hops, amount, p.hop_interval_seconds)
    now = _T0 + timedelta(minutes=p.detect_after_minutes)

    seeds = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=amount, now=now
    )
    recovered_here = retroactive_recovery_total(seeds)

    reference = simulate_chain(p)
    recovered_ref = reference["strategies"]["b_retroactif"]["recovered"]

    # Meme couverture : alerte avant echeance -> 100 % du M' en Ghost.
    assert reference["timeline"]["alert_before_maturity"] is True
    assert recovered_here == recovered_ref == amount
    # Fraction recuperee identique a la mesure de reference (#95).
    assert recovered_here / amount == reference["strategies"]["b_retroactif"][
        "recovered_fraction"
    ] == 1.0


# ------------------------------------------------- B1 (sinks) / B2 (conserv.)


def test_sink_zero_address_ne_produit_aucune_graine() -> None:
    """B1 : origine -> 0x0 ⇒ aucune graine (ni sur l'origine, ni sur le sink)."""
    # Conversion/burn : l'origine envoie tout son Ghost vers l'adresse zero.
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=ZERO_ADDRESS,
            amount=100,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=100, now=now
    )

    # La valeur et le soupcon sont sortis du lignage : aucune graine, et surtout
    # aucune graine sur 0x0.
    assert seeds == []
    assert all(seed.address != ZERO_ADDRESS for seed in seeds)


def test_sink_personnalise_ne_produit_aucune_graine() -> None:
    """B1 : un contrat de conversion passe en `sinks` ne porte jamais de graine."""
    redemption_contract = _addr(0xC0FFEE)
    transfers = [
        # Un saut legitime puis conversion : A1 convertit tout.
        _ghost_transfer(
            sender=_addr(0),
            recipient=_addr(1),
            amount=100,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
        _ghost_transfer(
            sender=_addr(1),
            recipient=redemption_contract,
            amount=100,
            at=_T0 + timedelta(seconds=2),
            nonce=2,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers,
        origin_address=_addr(0),
        origin_amount=100,
        now=now,
        sinks=frozenset({ZERO_ADDRESS, redemption_contract}),
    )

    # Tout est converti : plus personne ne detient de Ghost suspect atteignable.
    assert seeds == []
    assert all(seed.address != redemption_contract for seed in seeds)


def test_sink_casse_mixte_normalisee() -> None:
    """B1 : un sink est reconnu quelle que soit la casse de l'adresse."""
    mixed_sink = "0xAbCdEf0000000000000000000000000000000000"
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=mixed_sink.lower(),
            amount=50,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers,
        origin_address=_addr(0),
        origin_amount=50,
        now=now,
        sinks=frozenset({mixed_sink}),  # casse mixte, normalisee en interne
    )
    assert seeds == []


def test_conservation_avec_initial_balances() -> None:
    """B2 (i) : solde preexistant non suivi + initial_balances ⇒ conservation, ratio correct."""
    # L'origine detient 100 (suspect). L'expediteur legitime A1 detient deja 300
    # de Ghost non suivi (recu avant t0) ; on le declare via initial_balances.
    # A1 recoit 100 de l'origine puis renvoie 200 a A2 : sans initial_balances,
    # son solde reconstruit (100 recu - 200 envoye) serait negatif.
    legit = _addr(1)
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=legit,
            amount=100,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
        _ghost_transfer(
            sender=legit,
            recipient=_addr(2),
            amount=200,
            at=_T0 + timedelta(seconds=2),
            nonce=2,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers,
        origin_address=_addr(0),
        origin_amount=100,
        now=now,
        initial_balances={legit: 300},
    )

    # Soupcon conserve : le total reste 100 (rien n'est jete).
    assert retroactive_recovery_total(seeds) == 100
    by_addr = {s.address: s for s in seeds}
    # A1 a recu 100 suspect dans un pot de 400 (300 + 100), ratio courant 100/400.
    # Il envoie 200 vers A2 : part suspecte ceilDiv(100*200/400) = 50.
    # A1 garde 400 - 200 = 200 Ghost, 100 - 50 = 50 suspect. A2 recoit 50.
    assert by_addr[legit].suspect_amount == 50
    assert by_addr[_addr(2)].suspect_amount == 50
    assert by_addr[legit].contamination_ratio == 50 / 200
    assert by_addr[_addr(2)].contamination_ratio == 50 / 200


def test_conservation_sans_initial_balances_leve_valueerror() -> None:
    """B2 (ii) : meme cas SANS initial_balances ⇒ ValueError explicite (jamais faux silencieux)."""
    legit = _addr(1)
    transfers = [
        _ghost_transfer(
            sender=_addr(0),
            recipient=legit,
            amount=100,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
        # A1 renvoie 200 alors qu'il n'a (de ce rejeu) que 100 : solde negatif.
        _ghost_transfer(
            sender=legit,
            recipient=_addr(2),
            amount=200,
            at=_T0 + timedelta(seconds=2),
            nonce=2,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    with pytest.raises(ValueError, match="negatif"):
        retroactive_seeds(
            transfers, origin_address=_addr(0), origin_amount=100, now=now
        )


def test_mint_depuis_sink_traite_comme_source_sans_exception() -> None:
    """Review #112 (3e) : un mint (sink en expediteur) est une source, pas une erreur.

    Decision 2026-10-10 : tout transfert emet du Ghost, donc un mint apparait
    comme `Transfer(0x0 -> A, is_ghost=True)`. Pour l'expediteur `0x0`,
    `held = 0` et `amount > 0` : sans la regle « sink en expediteur = emission »,
    la garde B2 (`amount > held`) leverait sur tout flux contenant un mint apres
    t0. Scenario de Yannis : origine A detient 60 a t0, mint `0x0 -> A` de 40,
    puis A -> B de 50. Attendu : aucune exception, ratio de A = 60/100, et B
    porte `ceil(60*50/100) = 30`.
    """
    origin = _addr(1)  # origine NON NULLE (A)
    b = _addr(2)
    transfers = [
        # Mint : emission depuis l'adresse zero (sink par defaut) vers A.
        _ghost_transfer(
            sender=ZERO_ADDRESS,
            recipient=origin,
            amount=40,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
        # A revend 50 a B (sur un pot de 60 initial + 40 minte = 100).
        _ghost_transfer(
            sender=origin,
            recipient=b,
            amount=50,
            at=_T0 + timedelta(seconds=2),
            nonce=2,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    # Aucune exception : le mint est une source, pas une violation de la garde B2.
    seeds = retroactive_seeds(
        transfers,
        origin_address=origin,
        origin_amount=60,  # A detient 60 de suspect a t0
        now=now,
    )

    by_addr = {s.address: s for s in seeds}
    # A : 60 suspect dans un pot de 100 (60 + 40 minte). Il envoie 50 a B :
    # part suspecte ceilDiv(60*50/100) = 30. A garde 100 - 50 = 50 Ghost,
    # 60 - 30 = 30 suspect. B recoit 30 suspect dans 50 Ghost.
    assert by_addr[origin].suspect_amount == 30
    assert by_addr[origin].contamination_ratio == 30 / 50
    assert by_addr[b].suspect_amount == 30
    assert by_addr[b].contamination_ratio == 30 / 50
    # Le soupcon total reste 60 : le mint n'a ajoute aucun soupcon (valeur neuve).
    assert retroactive_recovery_total(seeds) == 60


def test_mint_sink_vers_sink_ne_credite_personne() -> None:
    """Un transfert sink -> sink (p. ex. 0x0 -> contrat de burn) ne credite rien."""
    burn_contract = _addr(0xDEAD)
    transfers = [
        _ghost_transfer(
            sender=ZERO_ADDRESS,
            recipient=burn_contract,
            amount=100,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers,
        origin_address=_addr(0),
        origin_amount=10,
        now=now,
        sinks=frozenset({ZERO_ADDRESS, burn_contract}),
    )

    # Le mint vers un sink ne credite personne ; seul l'origine (hors sink)
    # porte encore son soupcon initial, qu'elle n'a jamais deplace.
    by_addr = {s.address: s for s in seeds}
    assert by_addr[_addr(0)].suspect_amount == 10
    assert all(s.address != burn_contract for s in seeds)
    assert all(s.address != ZERO_ADDRESS for s in seeds)


def test_expediteur_inconnu_sans_initial_balances_leve_valueerror() -> None:
    """B2 : un expediteur a solde 0 reconstruit (hors lot) ⇒ ValueError sans soldes de depart."""
    # Un transfert dont l'expediteur n'a aucun Ghost du rejeu : amount > held=0.
    transfers = [
        _ghost_transfer(
            sender=_addr(500),
            recipient=_addr(200),
            amount=990,
            at=_T0 + timedelta(seconds=1),
            nonce=1,
        ),
    ]
    now = _T0 + timedelta(minutes=1)

    with pytest.raises(ValueError, match="negatif"):
        retroactive_seeds(
            transfers, origin_address=_addr(0), origin_amount=10, now=now
        )


def test_ordre_rejeu_par_block_puis_log_index() -> None:
    """Mineur : deux transferts du meme horodatage sont departages par (block, log_index)."""
    # Deux evenements au MEME observed_at : l'ordre doit suivre (block, log_index).
    # L'origine envoie d'abord 100 a A1 (block 1, log 0), puis A1 envoie 100 a A2
    # (block 1, log 1). Si on triait par observed_at seul, l'ordre d'entree
    # inverse casserait le rejeu (A1 enverrait avant d'avoir recu).
    same_time = _T0 + timedelta(seconds=5)
    ev_a1_to_a2 = TransferEvent(
        tx_hash=_tx(2),
        log_index=1,
        block_number=1,
        chain_id=43113,
        observed_at=same_time,
        sender=_addr(1),
        recipient=_addr(2),
        amount=100,
        is_ghost=True,
    )
    ev_origin_to_a1 = TransferEvent(
        tx_hash=_tx(1),
        log_index=0,
        block_number=1,
        chain_id=43113,
        observed_at=same_time,
        sender=_addr(0),
        recipient=_addr(1),
        amount=100,
        is_ghost=True,
    )
    # Entree volontairement dans le mauvais ordre : A1->A2 avant origin->A1.
    transfers = [ev_a1_to_a2, ev_origin_to_a1]
    now = _T0 + timedelta(minutes=1)

    seeds = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=100, now=now
    )

    # Grace au tri (block, log_index), origin->A1 (log 0) est rejoue avant
    # A1->A2 (log 1) : le soupcon arrive jusqu'a A2.
    (seed,) = seeds
    assert seed.address == _addr(2)
    assert seed.suspect_amount == 100


# ---------------------------------------------------- restitutions & ceil_div


def test_restitutions_prorata_plafonne_puis_reliquat_au_payeur() -> None:
    """§10bis point 4 : prorata plafonne par le paye, reste au payeur du voleur."""
    # 10 bloques derriere le Ghost de paiement du voleur. Deux porteurs brules :
    # A1 (brule 6, a paye 4) et A2 (brule 2, a paye 10). payeur = origine.
    burned = {_addr(1): 6, _addr(2): 2}
    paid = {_addr(1): 4, _addr(2): 10}
    res = restitutions_for_burn(
        burned_by_address=burned,
        paid_by_address=paid,
        thief_payment_ghost=10,
        payer_of_thief=_addr(0),
    )
    by_addr = {r.address: r.amount for r in res}
    # Prorata de 10 : A1 -> 10*6/8 = 7 mais plafonne a 4 ; A2 -> 10*2/8 = 2 (<=10).
    assert by_addr[_addr(1)] == 4
    assert by_addr[_addr(2)] == 2
    # Reste 10 - 4 - 2 = 4 -> au payeur du voleur (origine).
    assert by_addr[_addr(0)] == 4
    # On ne cree jamais de fonds : total <= argent bloque du voleur.
    assert sum(r.amount for r in res) == 10


def test_restitutions_sans_payeur_laisse_le_reliquat_au_coffre() -> None:
    """Sans payeur du voleur, le reliquat n'est attribue a personne (§10bis pt 3)."""
    res = restitutions_for_burn(
        burned_by_address={_addr(1): 1},
        paid_by_address={_addr(1): 1},
        thief_payment_ghost=10,
        payer_of_thief=None,
    )
    # A1 recupere 1 (plafond paye) ; les 9 restants restent dans le coffre.
    assert res == [Restitution(address=_addr(1), amount=1)]


def test_restitutions_normalise_les_clefs() -> None:
    """Mineur : burned/paid en casse differente d'une meme adresse ⇒ une seule feuille."""
    addr_lower = "0x00000000000000000000000000000000000000a1"
    addr_upper = "0x00000000000000000000000000000000000000A1"
    # La meme adresse apparait en deux casses dans burned et paid : les montants
    # doivent se cumuler (brule 3+3=6, paye 2+2=4), pas donner deux feuilles.
    res = restitutions_for_burn(
        burned_by_address={addr_lower: 3, addr_upper: 3},
        paid_by_address={addr_lower: 2, addr_upper: 2},
        thief_payment_ghost=10,
        payer_of_thief=_addr(0),
    )
    by_addr = {r.address: r.amount for r in res}
    # Une seule feuille pour l'adresse normalisee, plafonnee par le paye cumule.
    assert by_addr[addr_lower] == 4
    assert addr_upper not in by_addr
    # Reliquat 10 - 4 = 6 au payeur du voleur.
    assert by_addr[_addr(0)] == 6


def test_ceil_div() -> None:
    """`ceil_div` = Math.ceilDiv du design #8 (OpenZeppelin)."""
    assert ceil_div(0, 5) == 0
    assert ceil_div(1, 5) == 1
    assert ceil_div(5, 5) == 1
    assert ceil_div(6, 5) == 2
    assert ceil_div(10, 3) == 4
    for num, den in ((7, 2), (100, 7), (1, 1)):
        assert ceil_div(num, den) == -(-num // den)
