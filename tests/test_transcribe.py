from pathlib import Path

import numpy as np
import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import MediaInfo, Role, SyncResult, Transcript, Word
from roteiro_ia.transcribe import plan_sources, transcribe_event, words_between


@pytest.fixture
def db(tmp_path):
    s = Settings(work_drive=str(tmp_path / "work"), system_dir=str(tmp_path / "sys"),
                 e_root=str(tmp_path / "e"), g_root=str(tmp_path / "g"),
                 music_root=str(tmp_path / "mus"))
    with ProjectDB(tmp_path / "p.db", s) as d:
        yield d


def _add(db, rel, role, dur, start=None, ch=2, day="principal", kind="video"):
    mid = db.add_media(MediaInfo(
        rel_path=rel, folder=rel.split("\\")[0], role=role, day_label=day, kind=kind,
        duration_s=dur, fps_num=30, fps_den=1, width=160, height=120, rotation=0,
        audio_channels=ch))
    if start is not None:
        db.set_sync(SyncResult(media_id=mid, day_label=day, timeline_start_s=start,
                               confidence=9.0, method="audio"))
    return mid


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, path):
        self.calls.append(path)
        return [Word(text="oi", start_s=0.0, end_s=0.5)]


def test_plan_prefere_mesa_sobre_camera(db):
    mesa = _add(db, "M\mesa.wav", Role.mesa, 100, 0, kind="audio")
    cam = _add(db, "C\a.MP4", Role.camera, 50, 10)
    assert plan_sources(db) == [mesa]
    assert cam not in plan_sources(db)


def test_plan_camera_sem_cobertura_entra(db):
    mesa = _add(db, "M\mesa.wav", Role.mesa, 100, 0, kind="audio")
    cam = _add(db, "C\a.MP4", Role.camera, 50, 500)
    nosync = _add(db, "C\b.MP4", Role.pocket, 20)
    mudo = _add(db, "C\c.MP4", Role.camera, 20, 500, ch=0)
    drone = _add(db, "D\d.MP4", Role.drone, 20, 500)
    assert plan_sources(db) == [mesa, cam, nosync]
    assert mudo not in plan_sources(db) and drone not in plan_sources(db)


def test_plan_cobertura_parcial_por_uniao(db):
    _add(db, "M\m1.wav", Role.mesa, 30, 0, kind="audio")
    _add(db, "L\l.wav", Role.lapela_noivo, 30, 30, kind="audio")
    cam = _add(db, "C\a.MP4", Role.camera, 60, 0)
    cam2 = _add(db, "C\b.MP4", Role.camera, 60, 20)
    plan = plan_sources(db)
    assert cam not in plan and cam2 in plan


def test_transcribe_event_pula_feitas(db, tmp_path):
    _add(db, "M\mesa.wav", Role.mesa, 10, 0, kind="audio")
    _add(db, "L\l.wav", Role.lapela_noiva, 10, 0, kind="audio")
    t = FakeTranscriber()
    transcribe_event(db, tmp_path, t)
    assert len(t.calls) == 2
    transcribe_event(db, tmp_path, t)
    assert len(t.calls) == 2


def test_transcribe_event_erro_e_vazio(db, tmp_path):
    a = _add(db, "M\\a.wav", Role.mesa, 10, 0, kind="audio")
    b = _add(db, "M\\b.wav", Role.lapela_noivo, 10, 0, kind="audio")

    class T:
        def transcribe(self, path):
            if str(path).endswith("a.wav"):
                raise RuntimeError("falhou")
            return []

    transcribe_event(db, tmp_path, T())
    assert db.get_transcript(a) is None
    assert db.get_transcript(b).words == []
    assert db.list_falhas()[0].etapa == "transcricao"


def test_words_between():
    t = Transcript(media_id=1, source_role=Role.mesa, words=[
        Word(text="a", start_s=0, end_s=1), Word(text="b", start_s=1, end_s=2),
        Word(text="c", start_s=2, end_s=3)])
    assert words_between(t, 1, 3) == "b c"
    assert words_between(t, 5, 6) == ""


# --- revisão final: CPU só para erros de CUDA


class _FakeWhisper:
    criados = []
    erros = {}  # device -> lista de exceções a levantar em transcribe

    def __init__(self, name, device, compute_type):
        self.device = device
        _FakeWhisper.criados.append(device)

    def transcribe(self, path, **kw):
        _FakeWhisper.entradas.append(path)
        fila = _FakeWhisper.erros.get(self.device, [])
        if fila:
            raise fila.pop(0)
        return iter([]), None


@pytest.fixture
def fake_whisper(monkeypatch):
    import sys
    import types
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = _FakeWhisper
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    _FakeWhisper.criados = []
    _FakeWhisper.erros = {}
    _FakeWhisper.entradas = []
    from roteiro_ia import transcribe as tr
    monkeypatch.setattr(tr, "_carregar_audio", lambda p: np.zeros(16000, dtype=np.float32))
    return _FakeWhisper


def test_erro_comum_nao_cai_para_cpu(fake_whisper, tmp_path):
    from roteiro_ia.transcribe import WhisperTranscriber
    fake_whisper.erros["cuda"] = [RuntimeError("arquivo corrompido: invalid data")]
    t = WhisperTranscriber()
    with pytest.raises(RuntimeError):
        t.transcribe(tmp_path / "a.wav")
    assert t.device == "cuda" and fake_whisper.criados == ["cuda"]
    assert t.transcribe(tmp_path / "b.wav") == []  # o próximo arquivo segue na GPU
    assert fake_whisper.criados == ["cuda"]


@pytest.mark.parametrize("msg", ["CUDA failed with error out of memory",
                                 "Could not load library cudnn_ops_infer64_8.dll",
                                 "cuBLAS failed", "CUDA_ERROR_LAUNCH_FAILED"])
def test_erro_de_cuda_cai_para_cpu(fake_whisper, tmp_path, msg):
    from roteiro_ia.transcribe import WhisperTranscriber
    fake_whisper.erros["cuda"] = [RuntimeError(msg)]
    t = WhisperTranscriber()
    assert t.transcribe(tmp_path / "a.wav") == []
    assert t.device == "cpu" and fake_whisper.criados == ["cuda", "cpu"]


def test_whisper_recebe_audio_decodificado_pelo_ffmpeg(fake_whisper, tmp_path):
    # faster-whisper 1.2.1 abre o arquivo com av.open(metadata_errors=...), removido no PyAV 19:
    # todas as transcrições falhavam. O áudio vai decodificado (16 kHz mono) pelo nosso ffmpeg.
    from roteiro_ia.transcribe import WhisperTranscriber
    WhisperTranscriber().transcribe(tmp_path / "a.wav")
    entrada = fake_whisper.entradas[0]
    assert isinstance(entrada, np.ndarray) and entrada.dtype == np.float32


def test_carregar_audio_16k_mono(tmp_path):
    import soundfile as sf
    from roteiro_ia.transcribe import _carregar_audio
    f = tmp_path / "s.wav"
    sf.write(str(f), np.zeros((44100 * 2, 2), dtype=np.float32), 44100)
    y = _carregar_audio(f)
    assert y.dtype == np.float32 and y.ndim == 1 and abs(len(y) - 32000) < 400


def test_dlls_cuda_do_torch_registradas_para_o_whisper():
    # o ctranslate2 (Whisper) procura cublas64_12.dll; ela vem no torch/lib, que só entra no
    # caminho de DLLs quando o torch é importado (a transcrição roda antes das trilhas)
    import os
    from roteiro_ia.transcribe import preparar_dlls_cuda
    pasta = preparar_dlls_cuda()
    if os.name == "nt":
        assert pasta is not None and (pasta / "cublas64_12.dll").is_file()
    assert preparar_dlls_cuda() == pasta  # idempotente


def test_transcricao_usa_proxy_do_y_e_volta_ao_original(db, tmp_path):
    # o original (R:) é lento; o proxy 480p no disco de trabalho tem o som (AAC 128k)
    cam = _add(db, "A/a.MP4", Role.camera, 10, 0)
    cam2 = _add(db, "A/b.MP4", Role.camera, 10, 20)
    h4 = _add(db, "E/h4.wav", Role.mesa, 10, 40, kind="audio")
    px = tmp_path / "Y" / "a_Proxy.mp4"
    px2 = tmp_path / "Y" / "b_Proxy.mp4"
    px.parent.mkdir()
    px.write_bytes(b"x")
    px2.write_bytes(b"x")
    db.set_proxy(cam, str(px), "gerado")
    db.set_proxy(cam2, str(px2), "lrf")

    class T:
        calls = []

        def transcribe(self, path):
            T.calls.append(Path(path))
            if Path(path) == px2:
                raise RuntimeError("proxy sem áudio")
            return []
    transcribe_event(db, tmp_path / "R", T())
    assert px in T.calls and tmp_path / "R" / "A/a.MP4" not in T.calls
    assert T.calls.index(px2) < T.calls.index(tmp_path / "R" / "A/b.MP4")  # volta ao original
    assert tmp_path / "R" / "E/h4.wav" in T.calls  # sem proxy: original
    assert not db.list_falhas()
    assert all(db.get_transcript(m) is not None for m in (cam, cam2, h4))
