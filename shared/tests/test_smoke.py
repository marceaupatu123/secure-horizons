"""Test de fumee du module shared : le package s'importe et tourne seul."""


def test_import_shared() -> None:
    import shared

    assert shared is not None
