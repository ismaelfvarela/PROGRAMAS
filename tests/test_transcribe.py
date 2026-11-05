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
