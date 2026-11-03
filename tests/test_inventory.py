import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.inventory import list_subfolders, scan, suggest_role
from roteiro_ia.media.probe import _rotation, media_info_from_probe
from roteiro_ia.models import FolderAssignment, Role
from fixtures.make_media import make_audio, make_video


@pytest.mark.parametrize("nome,esperado", [
    ("A", Role.camera), ("D", Role.camera),
    ("E - H4", Role.audio_ambiente),
    ("H - DESPEDIDA DE SOLTEIRO", Role.outro_dia),
    ("TRILHAS", Role.ignorar), ("Proxies", Role.ignorar),
    ("MESA", Role.mesa), ("LAPELA NOIVO", Role.lapela_noivo),
    ("LAPELA NOIVA", Role.lapela_noiva), ("DRONE", Role.drone),
    ("OSMO", Role.pocket), ("XYZ", Role.camera),
])
def test_suggest_role(nome, esperado):
    assert suggest_role(nome) == esperado


@pytest.fixture
def db(tmp_path):
    with ProjectDB(tmp_path / "p.db", Settings()) as d:
        yield d


def _asg(*pairs):
    return [FolderAssignment(folder=f, role=r) for f, r in pairs]


def test_list_subfolders(tmp_path):
    (tmp_path / "B").mkdir(); (tmp_path / "A").mkdir(); (tmp_path / "x.txt").write_text("x")
    assert list_subfolders(tmp_path) == ["A", "B"]


def test_scan_ignora_caches(tmp_path, db):
    src = tmp_path / "src"
    (src / "A" / "Proxies").mkdir(parents=True)
    (src / "A" / "x.pek").write_bytes(b"1")
    (src / "A" / "y.cfa").write_bytes(b"1")
    (src / "A" / "w.LRF").write_bytes(b"1")
    (src / "A" / "Adobe Premiere Pro Audio Previews").mkdir()
    make_video(src / "A" / "Proxies" / "z.mp4", 1, size="320x180")
    make_video(src / "A" / "Adobe Premiere Pro Audio Previews" / "q.mp4", 1, size="320x180")
    make_video(src / "A" / "C0001.MP4", 1, size="320x180")
    n = scan(src, _asg(("A", Role.camera)), db)
    assert n == 1
    assert [m.rel_path for m in db.list_media()] == ["A\\C0001.MP4"]
    assert db.list_falhas() == []


def test_scan_fps_fracionario(tmp_path, db):
    src = tmp_path / "src"
    make_video(src / "A" / "a.mp4", 1, size="320x180")
    scan(src, _asg(("A", Role.camera)), db)
    m = db.list_media()[0]
    assert (m.fps_num, m.fps_den) == (30000, 1001)
    assert m.kind == "video" and m.audio_channels == 2 and m.day_label == "principal"
    assert m.duration_s == pytest.approx(1, abs=0.2)


def test_scan_vertical(tmp_path, db):
    src = tmp_path / "src"
    make_video(src / "A" / "v.mp4", 1, size="1080x1920", fps="25")
    scan(src, _asg(("A", Role.camera)), db)
    m = db.list_media()[0]
    assert (m.width, m.height, m.rotation) == (1080, 1920, 0)


def test_scan_audio_e_outro_dia_e_ignorar(tmp_path, db):
    src = tmp_path / "src"
    make_audio(src / "E - H4" / "r.wav", 1, noise_seed=1)
    make_video(src / "H - DESPEDIDA" / "d.mp4", 1, size="320x180")
    make_audio(src / "H - DESPEDIDA" / "d.wav", 1, noise_seed=2)
    make_video(src / "TRILHAS" / "t.mp4", 1, size="320x180")
    make_video(src / "OUTRA" / "o.mp4", 1, size="320x180")  # sem atribuição
    asg = _asg(("E - H4", Role.audio_ambiente), ("TRILHAS", Role.ignorar)) + [
        FolderAssignment(folder="H - DESPEDIDA", role=Role.outro_dia, day_label="H - DESPEDIDA")]
    assert scan(src, asg, db) == 3
    by = {m.rel_path: m for m in db.list_media()}
    a = by["E - H4\\r.wav"]
    assert (a.kind, a.fps_num, a.fps_den, a.width, a.height) == ("audio", 0, 1, 0, 0)
    assert a.role == Role.audio_ambiente and a.audio_channels == 1
    assert by["H - DESPEDIDA\\d.mp4"].role == Role.camera
    assert by["H - DESPEDIDA\\d.mp4"].day_label == "H - DESPEDIDA"
    assert by["H - DESPEDIDA\\d.wav"].role == Role.audio_ambiente


def test_scan_arquivo_corrompido_vira_falha(tmp_path, db):
    src = tmp_path / "src"
    make_video(src / "A" / "ok.mp4", 1, size="320x180")
    (src / "A" / "ruim.mp4").write_bytes(b"isto nao e um video")
    prog = []
    n = scan(src, _asg(("A", Role.camera)), db, on_progress=lambda i, t: prog.append((i, t)))
    assert n == 1
    f = db.list_falhas()
    assert len(f) == 1 and f[0].etapa == "inventario" and f[0].rel_path == "A\\ruim.mp4"
    assert prog[-1] == (2, 2)


def test_rotation_parsing():
    assert _rotation({"side_data_list": [{"rotation": -90}]}) == 270
    assert _rotation({"side_data_list": [{"rotation": 90}]}) == 90
    assert _rotation({"tags": {"rotate": "180"}}) == 180
    assert _rotation({}) == 0


def test_media_info_cover_art_e_tempo(tmp_path):
    fake = {"format": {"duration": "2.5", "tags": {"creation_time": "2026-03-01T10:00:00.000000Z",
                                                   "timecode": "01:02:03:04"}},
            "streams": [{"codec_type": "audio", "channels": 2},
                        {"codec_type": "video", "disposition": {"attached_pic": 1},
                         "width": 500, "height": 500, "r_frame_rate": "90000/1"}]}
    import roteiro_ia.media.probe as p
    orig = p.probe
    p.probe = lambda _p: fake
    try:
        m = media_info_from_probe(tmp_path / "A" / "s.mp3", tmp_path,
                                  FolderAssignment(folder="A", role=Role.camera))
    finally:
        p.probe = orig
    assert m.kind == "audio" and m.width == 0 and m.fps_num == 0
    assert m.created_at.tzinfo is not None and m.timecode == "01:02:03:04"


def test_scan_sem_ffprobe_levanta_erro_unico(tmp_path, db, monkeypatch):
    from roteiro_ia import inventory

    def boom():
        raise RuntimeError("Não encontrei o 'ffprobe'.")
    monkeypatch.setattr(inventory, "ffprobe_bin", boom)
    src = tmp_path / "src"
    (src / "A").mkdir(parents=True)
    (src / "A" / "x.mp4").write_bytes(b"1")
    with pytest.raises(RuntimeError, match="ffprobe"):
        scan(src, _asg(("A", Role.camera)), db)
    assert db.list_falhas() == []
