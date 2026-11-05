from roteiro_ia.config import Settings, load_settings, save_settings


def test_settings_roundtrip(tmp_path):
    s = Settings(style_urls=["https://youtu.be/x"])
    save_settings(s, tmp_path / "c.json")
    assert load_settings(tmp_path / "c.json") == s


def test_load_ausente_usa_padroes(tmp_path):
    assert load_settings(tmp_path / "nao_existe.json") == Settings()


def test_save_settings_bloqueia_caminho_protegido(tmp_path):
    import pytest
    from roteiro_ia.safety import ProtectedPathError
    s = Settings(protected_roots=[str(tmp_path / "R")])
    with pytest.raises(ProtectedPathError):
        save_settings(s, tmp_path / "R" / "c.json")
    assert not (tmp_path / "R").exists()
