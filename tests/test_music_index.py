import pytest
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


# ---------------------------------------------------------------- voz (Demucs plugável)

class FakeSeparator:
    """"Voz" = tudo acima de 600 Hz (as trilhas de teste têm a voz num tom agudo)."""

    def __init__(self):
        self.calls = []

    def vocals(self, audio, sr):
        self.calls.append(len(audio) / sr)
        spec = np.fft.rfft(audio)
        f = np.fft.rfftfreq(len(audio), 1 / sr)
        spec[f < 600] = 0
        return np.fft.irfft(spec, n=len(audio)).astype(np.float32)


def _musica_com_voz(seconds, voz_de=None, voz_ate=None, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    y = 0.2 * np.sin(2 * np.pi * 220 * t)
    if voz_de is not None:
        fim = seconds if voz_ate is None else voz_ate
        mask = (t >= voz_de) & (t < fim)
        y = y + 0.5 * np.sin(2 * np.pi * 1000 * t) * mask
    return y.astype(np.float32)


def test_trechos_musica_longa():
    from roteiro_ia.music_index import trechos

    energia = [0.1] * 300
    energia[200:220] = [0.9] * 20
    assert trechos(300.0, energia) == [("inicio", 0.0, 60.0), ("meio", 140.0, 160.0),
                                       ("climax", 200.0, 220.0)]


def test_trechos_climax_fora_do_inicio():
    from roteiro_ia.music_index import trechos

    energia = [0.9] * 30 + [0.1] * 270
    nome, a, b = trechos(300.0, energia)[2]
    assert nome == "climax" and a >= 60.0 and b - a == 20.0


def test_trechos_musica_curta_inteira():
    from roteiro_ia.music_index import trechos

    assert trechos(95.0, [0.1] * 95) == [("inteira", 0.0, 95.0)]


def test_voz_entra_aos_12s():
    from roteiro_ia.music_index import analisar_voz, trechos

    y = _musica_com_voz(40, voz_de=12)
    prop, inicio, intro = analisar_voz(y, SR, FakeSeparator(), trechos(40.0, [0.1] * 40))
    assert inicio == pytest.approx(12, abs=1)
    assert intro == pytest.approx(12, abs=1)
    assert prop == pytest.approx(28 / 40, abs=0.05)


def test_voz_so_no_meio_intro_e_o_inicio_inteiro():
    from roteiro_ia.music_index import analisar_voz, trechos

    y = _musica_com_voz(300, voz_de=130, voz_ate=170)
    sep = FakeSeparator()
    prop, inicio, intro = analisar_voz(y, SR, sep, trechos(300.0, [0.1] * 300))
    assert inicio is None and intro == 60.0
    assert prop > 0
    assert sorted(sep.calls) == [20.0, 20.0, 60.0]  # só os trechos, não a música inteira


def test_analyze_track_com_separador(tmp_path):
    p = tmp_path / "voz.wav"
    sf.write(str(p), _musica_com_voz(40, voz_de=12), SR)
    t = analyze_track(p, tracker=LibrosaTracker(), separator=FakeSeparator())
    assert t.has_vocals is True
    assert t.voz_inicio_s == pytest.approx(12, abs=1)
    assert t.intro_instrumental_s == pytest.approx(12, abs=1)
    assert t.voz_proporcao == pytest.approx(0.7, abs=0.05)
    assert t.versao_analise == 2


def test_analyze_track_sem_voz(tmp_path):
    p = tmp_path / "inst.wav"
    sf.write(str(p), _musica_com_voz(30), SR)
    t = analyze_track(p, tracker=LibrosaTracker(), separator=FakeSeparator())
    assert t.has_vocals is False
    assert t.voz_proporcao == 0.0
    assert t.voz_inicio_s is None
    assert t.intro_instrumental_s == pytest.approx(30, abs=0.5)
    assert t.tipo_voz == "sem voz"


def test_sem_demucs_usa_heuristica_e_marca_parcial(tmp_path, caplog):
    p = tmp_path / "x.wav"
    sf.write(str(p), _musica_com_voz(20, voz_de=5), SR)
    with caplog.at_level("WARNING"):
        t = analyze_track(p, tracker=LibrosaTracker())  # conftest: modelos indisponíveis
    assert t.analise_parcial is True
    assert t.voz_inicio_s is None and t.voz_proporcao == 0.0


def test_separador_que_falha_vira_parcial(tmp_path):
    class Quebrado:
        def vocals(self, audio, sr):
            raise RuntimeError("CUDA out of memory")

    p = tmp_path / "x.wav"
    sf.write(str(p), _musica_com_voz(20, voz_de=5), SR)
    t = analyze_track(p, tracker=LibrosaTracker(), separator=Quebrado())
    assert t.analise_parcial is True


def test_registro_antigo_carrega():
    antigo = ('{"path":"M:/a.mp3","bpm":90,"beats_s":[],"downbeats_s":[],"energy":[],'
              '"duration_s":100,"has_vocals":false,"perfil":"calma","mtime":1}')
    t = TrackInfo.model_validate_json(antigo)
    assert t.versao_analise == 1 and t.analise_parcial is False
    assert t.climas == [] and t.tonalidade == "" and t.voz_inicio_s is None


# ---------------------------------------------------------------- tonalidade e clima (CLAP plugável)

def _acorde(freqs, seconds=8, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    y = sum(np.sin(2 * np.pi * f * t) / (1 + 0.3 * i) for i, f in enumerate(freqs))
    return (0.2 * y).astype(np.float32)


def test_tonalidade_la_menor():
    from roteiro_ia.music_index import tonalidade

    assert tonalidade(_acorde([220.0, 261.63, 329.63]), SR) == ("Lá menor", "menor")


def test_tonalidade_do_maior():
    from roteiro_ia.music_index import tonalidade

    assert tonalidade(_acorde([261.63, 329.63, 392.0]), SR) == ("Dó maior", "maior")


def test_tonalidade_silencio_vazia():
    from roteiro_ia.music_index import tonalidade

    assert tonalidade(np.zeros(SR * 3, dtype=np.float32), SR) == ("", "")


class FakeTagger:
    PESOS = {"a epic song": 0.9, "a romantic song": 0.7, "a calm song": 0.5,
             "music with strings": 0.8, "music with piano": 0.95, "music with drums": 0.3,
             "music with instrumental": 0.99, "music with female vocals": 0.6,
             "music with male vocals": 0.2}

    def __init__(self):
        self.calls = []

    def scores(self, audio, sr, rotulos):
        self.calls.append((len(audio) / sr, list(rotulos)))
        return [self.PESOS.get(r, 0.1) for r in rotulos]


def test_classificar_top3_e_tipo_voz():
    from roteiro_ia.music_index import classificar

    tg = FakeTagger()
    climas, instrumentos, voz = classificar(np.zeros(SR), SR, tg, has_vocals=True)
    assert climas == ["épica", "romântica", "calma"]
    assert instrumentos == ["piano", "cordas", "bateria"]
    # "instrumental" tem o maior score, mas a voz foi detectada pelo Demucs: vale o tipo cantado
    assert voz == "feminina"
    assert "a romantic song" in tg.calls[0][1] and "music with acoustic guitar" in tg.calls[1][1]


def test_classificar_sem_voz():
    from roteiro_ia.music_index import classificar

    assert classificar(np.zeros(SR), SR, FakeTagger(), has_vocals=False)[2] == "sem voz"


def test_analyze_track_completa_com_fakes(tmp_path):
    p = tmp_path / "voz.wav"
    sf.write(str(p), _musica_com_voz(40, voz_de=12), SR)
    tg = FakeTagger()
    t = analyze_track(p, tracker=LibrosaTracker(), separator=FakeSeparator(), tagger=tg)
    assert t.analise_parcial is False
    assert t.climas == ["épica", "romântica", "calma"]
    assert t.instrumentos == ["piano", "cordas", "bateria"]
    assert t.tipo_voz == "feminina"
    assert t.tonalidade and t.modo in ("maior", "menor")
    assert tg.calls[0][0] == pytest.approx(40, abs=0.1)  # música curta: o CLAP ouve a inteira


def test_sem_clap_campos_vazios_e_parcial(tmp_path):
    p = tmp_path / "voz.wav"
    sf.write(str(p), _musica_com_voz(40, voz_de=12), SR)
    t = analyze_track(p, tracker=LibrosaTracker(), separator=FakeSeparator())
    assert t.analise_parcial is True
    assert t.climas == [] and t.instrumentos == []
    assert t.voz_inicio_s == pytest.approx(12, abs=1)  # a voz do Demucs continua valendo


# ---------------------------------------------------------------- reanálise

def _biblioteca(tmp_path, n=2):
    s = _settings(tmp_path)
    root = tmp_path / "musicas"
    root.mkdir()
    for i in range(n):
        sf.write(str(root / f"m{i}.wav"), _musica_com_voz(15, voz_de=5), SR)
    return s, MusicIndex(tmp_path / "sis" / "trilhas.db", s)


def test_reanalisa_versao_antiga(tmp_path):
    s, idx = _biblioteca(tmp_path, 1)
    update_index(s, idx, tracker=LibrosaTracker(), separator=FakeSeparator(), tagger=FakeTagger())
    t = idx.all()[0]
    idx.upsert(t.model_copy(update={"versao_analise": 1}))
    assert update_index(s, idx, tracker=LibrosaTracker(), separator=FakeSeparator(),
                        tagger=FakeTagger()) == 1
    assert idx.all()[0].versao_analise == 2


def test_reanalisa_parcial_quando_modelos_carregam(tmp_path):
    s, idx = _biblioteca(tmp_path)
    assert update_index(s, idx, tracker=LibrosaTracker()) == 2  # sem modelos → parciais
    assert all(t.analise_parcial for t in idx.all())
    assert update_index(s, idx, tracker=LibrosaTracker()) == 0  # continuam sem modelos
    assert update_index(s, idx, tracker=LibrosaTracker(), separator=FakeSeparator(),
                        tagger=FakeTagger()) == 2
    assert not any(t.analise_parcial for t in idx.all())
    assert update_index(s, idx, tracker=LibrosaTracker(), separator=FakeSeparator(),
                        tagger=FakeTagger()) == 0


def test_modelos_carregados_uma_vez_por_execucao(tmp_path, monkeypatch):
    from roteiro_ia import music_index

    s, idx = _biblioteca(tmp_path, 3)
    n = {"sep": 0, "tag": 0}

    def sep():
        n["sep"] += 1
        return FakeSeparator()

    def tag():
        n["tag"] += 1
        return FakeTagger()

    monkeypatch.setattr(music_index, "_default_separator", sep)
    monkeypatch.setattr(music_index, "_default_tagger", tag)
    assert update_index(s, idx, tracker=LibrosaTracker()) == 3
    assert n == {"sep": 1, "tag": 1}
    assert update_index(s, idx, tracker=LibrosaTracker()) == 0
    assert n == {"sep": 1, "tag": 1}  # tudo completo: nem carrega os modelos


def test_resumo_indice(tmp_path):
    from roteiro_ia.music_index import resumo_indice

    s, idx = _biblioteca(tmp_path)
    update_index(s, idx, tracker=LibrosaTracker())
    assert resumo_indice(idx) == (2, 0)
    t = idx.all()[0]
    idx.upsert(t.model_copy(update={"analise_parcial": False}))
    assert resumo_indice(idx) == (2, 1)


def test_sem_atualizar_versao_so_analisa_novas_e_alteradas(tmp_path):
    s, idx = _biblioteca(tmp_path, 2)
    update_index(s, idx, tracker=LibrosaTracker(), separator=FakeSeparator(), tagger=FakeTagger())
    a, b = idx.all()
    idx.upsert(a.model_copy(update={"versao_analise": 1}))          # antiga
    idx.upsert(b.model_copy(update={"analise_parcial": True}))      # parcial
    sf.write(str(tmp_path / "musicas" / "nova.wav"), _musica_com_voz(15), SR)
    n = update_index(s, idx, tracker=LibrosaTracker(), separator=FakeSeparator(),
                     tagger=FakeTagger(), atualizar_versao=False)
    assert n == 1  # só a nova
    por = {t.path: t for t in idx.all()}
    assert por[a.path].versao_analise == 1 and por[b.path].analise_parcial is True
    assert update_index(s, idx, tracker=LibrosaTracker(), separator=FakeSeparator(),
                        tagger=FakeTagger()) == 2  # a Trilhas (padrão True) atualiza as duas


def test_libera_gpu_no_fim(tmp_path, monkeypatch):
    from roteiro_ia import music_index

    chamadas = []
    monkeypatch.setattr(music_index, "_liberar_gpu", lambda: chamadas.append(1))
    s, idx = _biblioteca(tmp_path, 1)
    update_index(s, idx, tracker=LibrosaTracker())
    assert chamadas == [1]


def test_duracao_lida_sem_carregar_audio(tmp_path):
    from roteiro_ia import music_index as mi
    f = tmp_path / "t.wav"
    sf.write(str(f), np.zeros(SR * 3, dtype=np.float32), SR)
    assert mi._duracao_s(f) == pytest.approx(3.0, abs=0.05)
    assert mi._duracao_s(tmp_path / "nao_existe.wav") is None


def test_trilha_longa_demais_e_pulada_sem_carregar(tmp_path, monkeypatch, caplog):
    # coletânea de 11 h 54 min (M:\TRILHAS - EFEITOS SONOROS\1.mp3) esgotava a RAM e travava a máquina
    from roteiro_ia import music_index as mi
    s = _settings(tmp_path)
    root = tmp_path / "musicas"
    root.mkdir()
    longa = root / "1.mp3"
    longa.write_bytes(b"x")
    _click(root / "curta.wav", seconds=10)
    real = mi._duracao_s
    monkeypatch.setattr(mi, "_duracao_s", lambda p: 42831.7 if p.name == "1.mp3" else real(p))
    monkeypatch.setattr(mi, "_default_separator", lambda: None)
    monkeypatch.setattr(mi, "_default_tagger", lambda: None)
    carregou = []
    orig_load = mi._load_audio
    monkeypatch.setattr(mi, "_load_audio", lambda p, *a, **k: carregou.append(p.name) or orig_load(p, *a, **k))
    with pytest.raises(mi.TrilhaLongaDemais):
        analyze_track(longa, LibrosaTracker(), carregar_modelos=False)
    assert carregou == []
    idx = MusicIndex(tmp_path / "sis" / "trilhas.db", s)
    with caplog.at_level("WARNING"):
        n = update_index(s, idx, tracker=LibrosaTracker(), separator=None, tagger=None)
    assert n == 1
    assert [p.split("\\")[-1].split("/")[-1] for p in (t.path for t in idx.all())] == ["curta.wav"]
    assert "1.mp3" not in carregou
    assert any("longa" in r.getMessage() and "1.mp3" in r.getMessage() for r in caplog.records)
    idx.close()


def test_carga_de_modelos_nao_contamina_outra_thread(monkeypatch):
    # o CLAP (transformers) troca nn.Module.register_parameter no processo inteiro enquanto
    # carrega; um Demucs criado ao mesmo tempo em outra thread nascia "meta" (sem dados)
    import threading
    import time
    import torch
    import demucs.pretrained
    from transformers.integrations.accelerate import init_empty_weights
    from roteiro_ia import music_index as mi

    def clap_lento(revisao):
        with init_empty_weights():
            time.sleep(0.8)
            return torch.nn.Linear(2, 2)
    monkeypatch.setattr(mi, "_carregar_processador_clap", lambda: object())
    monkeypatch.setattr(mi, "_carregar_modelo_clap", clap_lento)
    monkeypatch.setattr(demucs.pretrained, "get_model", lambda name: torch.nn.Linear(2, 2))
    t = threading.Thread(target=lambda: mi.ClapTagger(device="cpu")._load())
    t.start()
    time.sleep(0.2)
    sep = mi.DemucsSeparator(device="cpu")
    modelo = sep._load()
    t.join()
    assert modelo.weight.device.type == "cpu"


def test_beat_this_recebe_o_audio_ja_carregado(tmp_path):
    # MP3 que na verdade é M4A (download do YouTube): o leitor do beat_this não abre,
    # o nosso (com ffmpeg) abre; o tracker usa o sinal, não o caminho
    from roteiro_ia import music_index as mi
    f = tmp_path / "t.wav"
    _click(f, seconds=8)
    visto = {}

    class Modelo:
        def __call__(self, signal, sr):
            visto["sr"], visto["n"] = sr, len(signal)
            return np.array([0.5, 1.0]), np.array([0.5])
    tr = mi.BeatThisTracker(device="cpu")
    tr._model = Modelo()
    info = analyze_track(f, tr, carregar_modelos=False)
    assert visto["sr"] == SR and visto["n"] == pytest.approx(8 * SR, abs=SR // 10)
    assert info.beats_s == [0.5, 1.0]


def test_update_index_com_root_varre_so_a_pasta(tmp_path):
    from pathlib import Path
    s = _settings(tmp_path)
    m = tmp_path / "musicas"
    (m / "A").mkdir(parents=True)
    (m / "B").mkdir()
    _click(m / "A" / "x.wav")
    _click(m / "B" / "y.wav")
    idx = MusicIndex(tmp_path / "t.db", s)
    assert update_index(s, idx, tracker=LibrosaTracker(), root=m / "A") == 1
    assert [Path(t.path).name for t in idx.all()] == ["x.wav"]


def test_update_index_com_root_nao_remove_trilhas_de_fora(tmp_path):
    from pathlib import Path
    s = _settings(tmp_path)
    m = tmp_path / "musicas"
    (m / "A").mkdir(parents=True)
    (m / "B").mkdir()
    _click(m / "A" / "x.wav")
    _click(m / "B" / "y.wav")
    idx = MusicIndex(tmp_path / "t.db", s)
    update_index(s, idx, tracker=LibrosaTracker())
    update_index(s, idx, tracker=LibrosaTracker(), root=m / "A")
    assert sorted(Path(t.path).name for t in idx.all()) == ["x.wav", "y.wav"]


def test_indice_filtrado_inclui_subpastas_e_ignora_resto(tmp_path):
    from pathlib import Path
    from roteiro_ia.music_index import IndiceFiltrado
    s = _settings(tmp_path)
    m = tmp_path / "musicas"
    idx = MusicIndex(tmp_path / "t.db", s)
    import os
    for rel in ("COM/a.wav", "COM/sub/b.wav", "OUTRA/c.wav", "COMPLETA/d.wav"):
        p = os.path.abspath(m / rel)
        idx.upsert(TrackInfo(path=p, bpm=120, beats_s=[0.5], downbeats_s=[0.5], energy=[0.1],
                             duration_s=10, has_vocals=False, perfil="calma", mtime=0))
    f = IndiceFiltrado(idx, m / "com")  # caixa diferente de propósito
    assert sorted(Path(t.path).name for t in f.all()) == ["a.wav", "b.wav"]
    assert f.get(os.path.abspath(m / "OUTRA" / "c.wav")) is not None  # delegação


def test_update_index_com_root_de_grafia_diferente_nao_remove_nem_reanalisa(tmp_path):
    from pathlib import Path
    s = _settings(tmp_path)
    m = tmp_path / "musicas"
    (m / "A").mkdir(parents=True)
    _click(m / "A" / "x.wav")
    idx = MusicIndex(tmp_path / "t.db", s)
    assert update_index(s, idx, tracker=LibrosaTracker(), root=m / "A") == 1
    antes = [t.path for t in idx.all()]
    # mesma pasta com a caixa trocada (no Windows o os.walk devolve a grafia do root)
    assert update_index(s, idx, tracker=LibrosaTracker(), root=m / "a") == 0
    assert [t.path for t in idx.all()] == antes
    assert Path(antes[0]).name == "x.wav"
