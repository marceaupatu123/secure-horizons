"""Test de fumee du module monitor : le package s'importe et tourne seul."""


def test_import_monitor() -> None:
    import monitor

    assert monitor is not None
