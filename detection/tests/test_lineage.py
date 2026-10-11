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

from data.late_marking import ChainParams, simulate_chain
from detection.lineage import (
    MAX_SEEDS_PER_BATCH,
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
    """Adresse EVM synthetique deterministe (0x + 40 hex)."""
    return "0x" + f"{index:040x}"


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
    # de Ghost legitime (credite par un transfert hors lot, ratio 0).
    legit_holder = _addr(200)
    transfers = [
        # Ghost legitime prealable chez le gros porteur (expediteur inconnu du
        # lot : ratio 0).
        _ghost_transfer(
            sender=_addr(500),
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
        transfers, origin_address=_addr(0), origin_amount=10, now=now
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
    # On modelise la conversion comme un transfert Ghost vers une adresse de
    # "sortie" (burn/redemption) qui ne fait plus partie des detenteurs vises :
    # apres coup, l'origine ne detient plus rien en Ghost.
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
        transfers, origin_address=_addr(0), origin_amount=100, now=now
    )

    # Tout le soupcon a suivi la valeur vers le sink ; l'origine ne porte plus
    # rien. Le sink porte 100 (il detient encore ce Ghost). Si en revanche la
    # valeur avait ete convertie *hors* Ghost (sortie du lignage), elle serait
    # hors d'atteinte. On verifie ici le plafond par solde non converti :
    # l'origine, a 0 de Ghost, n'apparait pas.
    assert all(seed.address != _addr(0) for seed in seeds)
    # Un transfert au-dela de `now` n'est pas rejoue : le soupcon reste a
    # l'origine (deja converti du point de vue du gel = non deplace ici).
    now_before = _T0  # avant le transfert
    seeds_before = retroactive_seeds(
        transfers, origin_address=_addr(0), origin_amount=100, now=now_before
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


def test_ceil_div() -> None:
    """`ceil_div` = Math.ceilDiv du design #8 (OpenZeppelin)."""
    assert ceil_div(0, 5) == 0
    assert ceil_div(1, 5) == 1
    assert ceil_div(5, 5) == 1
    assert ceil_div(6, 5) == 2
    assert ceil_div(10, 3) == 4
    for num, den in ((7, 2), (100, 7), (1, 1)):
        assert ceil_div(num, den) == -(-num // den)
