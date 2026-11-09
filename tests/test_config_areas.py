from roteiro_ia.config import (
    Settings,
    config_area,
    load_settings,
    pasta_musicas_padrao,
    save_settings,
    set_urls_estilo,
    urls_estilo,
)


def test_config_antigo_carrega_sem_areas(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"style_urls": ["https://youtu.be/a"], "music_root": "M:\\\\"}', encoding="utf-8")
    s = load_settings(f)
    assert s.area_atual == "casamento" and s.areas == {}
    assert urls_estilo(s, "casamento") == ["https://youtu.be/a"]
    assert urls_estilo(s, "formatura") == []
    assert pasta_musicas_padrao(s, "formatura") == "M:\\"


def test_urls_por_area_sao_independentes():
    s = Settings(style_urls=["c"])
    set_urls_estilo(s, "formatura", ["f"])
    assert s.style_urls == ["c"] and urls_estilo(s, "formatura") == ["f"]
    set_urls_estilo(s, "casamento", ["c2"])
    assert s.style_urls == ["c2"] and urls_estilo(s, "formatura") == ["f"]


def test_pasta_padrao_da_area_e_salva(tmp_path):
    s = Settings(system_dir=str(tmp_path), protected_roots=[])
    config_area(s, "formatura").pasta_musicas = r"M:\COMERCIAIS"
    s.area_atual = "formatura"
    save_settings(s, tmp_path / "config.json")
    s2 = load_settings(tmp_path / "config.json")
    assert pasta_musicas_padrao(s2, "formatura") == r"M:\COMERCIAIS"
    assert s2.area_atual == "formatura"
