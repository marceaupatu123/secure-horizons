"""Test de fumee du module llm : le package s'importe et tourne seul."""


def test_import_llm() -> None:
    import llm

    assert llm is not None
