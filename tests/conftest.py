import pytest

from roteiro_ia import safety
from roteiro_ia.config import Settings


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def settings_unc(monkeypatch):
    s = Settings()
    monkeypatch.setattr(
        safety,
        "protected_paths",
        lambda _s: ["r:\\", "m:\\", r"\\192.168.168.2\fokuss\m - musicas"],
    )
    return s


@pytest.fixture(autouse=True)
def _sem_modelos_de_musica(request, monkeypatch):
    """Na suíte padrão nenhum modelo (Demucs/CLAP) é baixado nem carregado: os carregadores
    padrão devolvem None (análise parcial). Só os testes marcados `modelos` usam os reais."""
    if request.node.get_closest_marker("modelos"):
        return
    from roteiro_ia import music_index
    monkeypatch.setattr(music_index, "_default_separator", lambda: None, raising=False)
    monkeypatch.setattr(music_index, "_default_tagger", lambda: None, raising=False)
    for nome in ("_carregar_modelo_clap", "_carregar_processador_clap"):
        monkeypatch.setattr(music_index, nome, _modelo_bloqueado, raising=False)


def _modelo_bloqueado(*a, **k):
    raise RuntimeError("modelo real bloqueado na suíte padrão (use -m modelos)")
