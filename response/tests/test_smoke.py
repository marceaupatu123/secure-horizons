"""Test de fumee du module response : le package s'importe et tourne seul."""


def test_import_response() -> None:
    import response

    assert response is not None
