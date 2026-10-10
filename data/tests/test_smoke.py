"""Test de fumee du module data : le package et le generateur s'importent seuls."""


def test_import_data() -> None:
    import data
    import data.generate

    assert data is not None
    assert callable(data.generate.main)
