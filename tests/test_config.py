from roteiro_ia.config import Settings, load_settings, save_settings


def test_settings_roundtrip(tmp_path):
    s = Settings(style_urls=["https://youtu.be/x"])
    save_settings(s, tmp_path / "c.json")
    assert load_settings(tmp_path / "c.json") == s


def test_load_ausente_usa_padroes(tmp_path):
    assert load_settings(tmp_path / "nao_existe.json") == Settings()
