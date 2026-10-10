"""Test de fumee du module detection : le package s'importe et tourne seul."""


def test_import_detection() -> None:
    import detection

    assert detection is not None
