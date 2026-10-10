"""Point d'entree du module detection : `python -m detection`.

Affiche l'etat des surveillants de `detection/detector.py`.
"""

from __future__ import annotations


def main() -> None:
    """Point d'entree executable."""
    print(
        "detection : surveillants a regles disponibles — mint "
        "(RuleBasedMonitor.check_mint, #11) et transferts « volume eleve ET "
        "dispersion effondree » (RuleBasedMonitor.check_transfer, #12) ; "
        "parametres PROVISOIRES dans detection/params.py."
    )


if __name__ == "__main__":
    main()
