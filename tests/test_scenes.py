import subprocess

import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.models import MediaInfo, Role
from roteiro_ia.scenes import detect_segments, split_long


@pytest.fixture
def db(tmp_path):
    s = Settings(work_drive=str(tmp_path / "work"), system_dir=str(tmp_path / "sys"),
                 e_root=str(tmp_path / "e"), g_root=str(tmp_path / "g"),
                 music_root=str(tmp_path / "mus"))
    with ProjectDB(tmp_path / "p.db", s) as d:
        yield d


def _add(db, rel, dur, kind="video", role=Role.camera):
    return db.add_media(MediaInfo(
        rel_path=rel, folder=rel.split("\\")[0], role=role, day_label="principal",
        kind=kind, duration_s=dur, fps_num=30, fps_den=1, width=320, height=180,
        rotation=0, audio_channels=0 if kind == "video" else 1))


def test_split_long():
    assert split_long([(0, 150)]) == [(0, 50), (50, 100), (100, 150)]


def test_junta_curtos():
    assert split_long([(0, 10), (10, 11), (11, 30)]) == [(0, 11), (11, 30)]


def test_primeiro_curto_junta_ao_proximo():
    assert split_long([(0, 1), (1, 20)]) == [(0, 20)]


def test_detect_em_video_com_corte(db, tmp_path):
    vid = tmp_path / "corte.mp4"
    subprocess.run([
        ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=3:r=30",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=3:r=30",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
        "-pix_fmt", "yuv420p", str(vid)], check=True, capture_output=True)
    mid = _add(db, r"A\corte.mp4", 6.0)
    db.set_proxy(mid, str(vid), "gerado")
    detect_segments(db, None)
    segs = db.list_segments(mid)
    assert len(segs) == 2
    assert segs[0].end_s == pytest.approx(3.0, abs=0.2)
    assert segs[1].start_s == pytest.approx(segs[0].end_s)
    assert segs[1].end_s == pytest.approx(6.0, abs=0.1)
    detect_segments(db, None)  # retomada: não duplica
    assert len(db.list_segments(mid)) == 2


def test_sem_proxy_registra_falha(db):
    _add(db, r"A\x.mp4", 30)
    detect_segments(db, None)
    assert db.list_segments() == []
    assert db.list_falhas()[0].etapa == "cenas"


def test_audio_em_blocos_de_60s(db):
    mid = _add(db, r"M\a.wav", 130, kind="audio", role=Role.mesa)
    detect_segments(db, None)
    assert [(s.start_s, s.end_s) for s in db.list_segments(mid)] == [(0, 60), (60, 120), (120, 130)]
