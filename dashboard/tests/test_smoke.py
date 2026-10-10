"""Test de fumee du module dashboard : le package s'importe et tourne seul."""


def test_import_dashboard() -> None:
    import dashboard

    assert dashboard is not None
