"""Teste real (opcional) com Demucs e CLAP: `uv run pytest -m modelos`.

Baixa os modelos na primeira execução (htdemucs ~80 MB; CLAP ~600 MB) e usa a GPU se houver.
Fica fora da suíte padrão (addopts: not modelos)."""
import numpy as np
import pytest
import soundfile as sf

from roteiro_ia.music_index import (CLIMAS, INSTRUMENTOS, TIPO_VOZ, ClapTagger, DemucsSeparator,
                                    LibrosaTracker, analyze_track)

pytestmark = pytest.mark.modelos
SR = 44100


def test_demucs_e_clap_reais(tmp_path):
    t = np.arange(SR * 30) / SR
    beat = (np.sin(2 * np.pi * 2 * t) > 0.95) * np.sin(2 * np.pi * 80 * t)
    acorde = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 261.63, 329.63)) / 3
    y = (0.3 * acorde + 0.4 * beat).astype(np.float32)
    p = tmp_path / "sintetica.wav"
    sf.write(str(p), y, SR)
    sep, tag = DemucsSeparator(), ClapTagger()
    info = analyze_track(p, tracker=LibrosaTracker(), separator=sep, tagger=tag)
    assert info.analise_parcial is False
    assert len(info.climas) == 3 and set(info.climas) <= set(CLIMAS.values())
    assert len(info.instrumentos) == 3 and set(info.instrumentos) <= set(INSTRUMENTOS.values())
    assert info.tipo_voz in TIPO_VOZ.values()
    assert info.tonalidade
    print(f"\ndispositivos: demucs={sep.device} clap={tag.device}; {info.model_dump_json()}")
