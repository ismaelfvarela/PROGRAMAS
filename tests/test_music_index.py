import numpy as np
import soundfile as sf

from roteiro_ia.config import Settings
from roteiro_ia.models import TrackInfo
from roteiro_ia.music_index import (
    LibrosaTracker, MusicIndex, analyze_track, beat_positions, update_index,
)

SR = 22050


def _settings(tmp_path):
    return Settings(
        work_drive=str(tmp_path / "Y"), e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"),
        system_dir=str(tmp_path / "sis"), music_root=str(tmp_path / "musicas"),
        protected_roots=[str(tmp_path / "musicas")],
    )


def _click(path, bpm=120, seconds=20):
    y = np.zeros(int(SR * seconds), dtype=np.float32)
    period = 60 / bpm
    n = 0
    t = 0.0
    while t < seconds - 0.1:
        tone = np.sin(2 * np.pi * (1500 if n % 4 == 0 else 1000) * np.arange(int(0.03 * SR)) / SR)
        tone *= np.hanning(len(tone)) * (0.9 if n % 4 == 0 else 0.5)
        i = int(t * SR)
        y[i:i + len(tone)] += tone.astype(np.float32)
        t += period
        n += 1
    sf.write(str(path), y, SR)


def test_bpm_click_120(tmp_path):
    p = tmp_path / "click.wav"
    _click(p)
    t = analyze_track(p, tracker=LibrosaTracker())
    assert abs(t.bpm - 120) <= 2
    assert len(t.energy) == 20
    assert t.downbeats_s and len(t.downbeats_s) < len(t.beats_s)


def test_beat_positions_ciclo_1_a_4():
    beats = [i * 0.5 for i in range(12)]
    t = TrackInfo(path="x", bpm=120, beats_s=beats, downbeats_s=[1.0, 3.0, 5.0], energy=[0.1],
                  duration_s=6, has_vocals=False, perfil="calma", mtime=0)
    nums = [n for _, n in beat_positions(t)]
    assert nums == [3, 4, 1, 2, 3, 4, 1, 2, 3, 4, 1, 2]


def test_incremental_pula_inalteradas(tmp_path):
    s = _settings(tmp_path)
    root = tmp_path / "musicas"
    root.mkdir()
    _click(root / "a.wav", seconds=8)
    _click(root / "B.WAV", seconds=8)
    (root / "x.pek").write_text("cache")
    (root / "nota.txt").write_text("x")
    idx = MusicIndex(tmp_path / "sis" / "trilhas.db", s)
    assert update_index(s, idx, tracker=LibrosaTracker()) == 2
    assert update_index(s, idx, tracker=LibrosaTracker()) == 0
    assert len(idx.all()) == 2
    (root / "a.wav").unlink()
    update_index(s, idx, tracker=LibrosaTracker())
    assert len(idx.all()) == 1


def test_perfil_crescente(tmp_path):
    rng = np.random.default_rng(0)
    n = SR * 30
    y = (rng.standard_normal(n) * np.linspace(0.02, 0.3, n)).astype(np.float32)
    p = tmp_path / "ramp.wav"
    sf.write(str(p), y, SR)
    t = analyze_track(p, tracker=LibrosaTracker())
    assert t.perfil == "crescente"


def test_raiz_inexistente_levanta_e_preserva_indice(tmp_path):
    import pytest

    s = _settings(tmp_path)
    root = tmp_path / "musicas"
    root.mkdir()
    _click(root / "a.wav", seconds=8)
    idx = MusicIndex(tmp_path / "sis" / "trilhas.db", s)
    update_index(s, idx, tracker=LibrosaTracker())
    root_gone = s.model_copy(update={"music_root": str(tmp_path / "offline")})
    with pytest.raises(FileNotFoundError, match="pasta de músicas"):
        update_index(root_gone, idx, tracker=LibrosaTracker())
    assert len(idx.all()) == 1


def test_erro_no_walk_nao_apaga(tmp_path, monkeypatch):
    import os as _os

    s = _settings(tmp_path)
    root = tmp_path / "musicas"
    root.mkdir()
    _click(root / "a.wav", seconds=8)
    idx = MusicIndex(tmp_path / "sis" / "trilhas.db", s)
    update_index(s, idx, tracker=LibrosaTracker())
    real = _os.walk

    def bad_walk(top, onerror=None, **kw):
        if onerror:
            onerror(OSError("rede caiu"))
        return iter(())

    monkeypatch.setattr("roteiro_ia.music_index.os.walk", bad_walk)
    assert update_index(s, idx, tracker=LibrosaTracker()) == 0
    assert len(idx.all()) == 1
    monkeypatch.setattr("roteiro_ia.music_index.os.walk", real)


def test_zero_arquivos_com_indice_nao_apaga(tmp_path):
    s = _settings(tmp_path)
    root = tmp_path / "musicas"
    root.mkdir()
    _click(root / "a.wav", seconds=8)
    idx = MusicIndex(tmp_path / "sis" / "trilhas.db", s)
    update_index(s, idx, tracker=LibrosaTracker())
    (root / "a.wav").unlink()
    update_index(s, idx, tracker=LibrosaTracker())
    assert len(idx.all()) == 1


def test_vocals_usa_trecho_central(tmp_path):
    from roteiro_ia.music_index import VOCAL_EXCERPT_S, _has_vocals

    y = np.zeros(SR * 200, dtype=np.float32)
    seen = {}
    import librosa

    orig = librosa.effects.harmonic
    librosa.effects.harmonic = lambda x, **k: (seen.setdefault("n", len(x)), orig(x, **k))[1]
    try:
        _has_vocals(y)
    finally:
        librosa.effects.harmonic = orig
    assert seen["n"] <= VOCAL_EXCERPT_S * SR
