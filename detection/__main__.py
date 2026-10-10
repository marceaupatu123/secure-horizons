"""Point d'entree du module detection : `python -m detection`.

Affiche l'etat des surveillants de `detection/detector.py`.
"""

from __future__ import annotations


def main() -> None:
    """Point d'entree executable."""
    print(
        "detection : surveillant de mint a regles disponible "
        "(RuleBasedMonitor.check_mint) ; check_transfer a implementer (#12)."
    )


if __name__ == "__main__":
    main()
