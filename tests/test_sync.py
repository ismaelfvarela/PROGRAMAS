import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from fixtures.make_media import make_audio, make_video
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.models import MediaInfo, Role, SyncResult
from roteiro_ia.sync import sync_event, xcorr_offset

SR = 8000
T0 = datetime(2026, 10, 10, 16, 0, 0)


def _ff(*args):
    subprocess.run([ffmpeg_bin(), "-y", "-v", "error", *args], check=True)


def _cut(src: Path, dst: Path, start: float, dur: float) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ff("-ss", str(start), "-t", str(dur), "-i", str(src), "-c:a", "pcm_s16le", str(dst))
    return dst


def _video_with_audio(src_audio: Path, dst: Path, start: float, dur: float) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ff("-f", "lavfi", "-i", f"testsrc2=size=160x120:rate=30:duration={dur}",
        "-ss", str(start), "-t", str(dur), "-i", str(src_audio),
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(dst))
    return dst


def _info(rel, role, kind, dur, created, channels=1, day="principal"):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=role, day_label=day,
                     kind=kind, duration_s=dur, fps_num=30, fps_den=1, width=160, height=120,
                     rotation=0, audio_channels=channels, created_at=created)


@pytest.fixture
def db(tmp_path):
    s = Settings(work_drive=str(tmp_path / "work"), system_dir=str(tmp_path / "sys"),
                 e_root=str(tmp_path / "e"), g_root=str(tmp_path / "g"),
                 music_root=str(tmp_path / "mus"))
    with ProjectDB(tmp_path / "p.db", s) as d:
        yield d


# --- xcorr_offset

def test_xcorr_offset_conhecido():
    rng = np.random.default_rng(1)
    ref = rng.standard_normal(SR * 20).astype(np.float32)
    other = ref[int(2.5 * SR): int(2.5 * SR) + SR * 10].copy()
    other += 0.3 * rng.standard_normal(other.size).astype(np.float32)
    off, conf = xcorr_offset(ref, other, SR)
    assert off == pytest.approx(2.5, abs=0.02)
    assert conf > 3


def test_xcorr_offset_negativo():
    rng = np.random.default_rng(2)
    base = rng.standard_normal(SR * 20).astype(np.float32)
    ref = base[SR * 3:]
    other = base[: SR * 10]
    off, conf = xcorr_offset(ref, other, SR)
    assert off == pytest.approx(-3.0, abs=0.02)
    assert conf > 3


def test_xcorr_sem_relacao_baixa_confianca():
    rng = np.random.default_rng(3)
    a = rng.standard_normal(SR * 20).astype(np.float32)
    b = rng.standard_normal(SR * 10).astype(np.float32)
    _, conf = xcorr_offset(a, b, SR)
    assert conf < 3


def test_xcorr_silencio_ou_vazio():
    assert xcorr_offset(np.zeros(SR * 5, np.float32), np.zeros(SR, np.float32), SR)[1] == 0
    assert xcorr_offset(np.zeros(0, np.float32), np.ones(SR, np.float32), SR)[1] == 0


# --- sync_event

def test_sync_event_posiciona_camera(tmp_path, db):
    root = tmp_path / "src"
    ref = make_audio(root / "MESA" / "ZOOM0001.wav", 120, noise_seed=7)
    _video_with_audio(ref, root / "CAM A" / "C0001.MP4", 40, 30)
    rid = db.add_media(_info("MESA\\ZOOM0001.wav", Role.mesa, "audio", 120, T0))
    cid = db.add_media(_info("CAM A\\C0001.MP4", Role.camera, "video", 30,
                             T0 + timedelta(seconds=60), channels=2))
    sync_event(db, root)
    r, c = db.get_sync(rid), db.get_sync(cid)
    assert r.timeline_start_s == pytest.approx(0, abs=1e-6) and r.method == "audio"
    assert c.method == "audio"
    assert c.timeline_start_s == pytest.approx(40, abs=0.05)
    assert c.confidence >= 3
    assert c.day_label == "principal"


def test_drone_sem_audio_usa_hora(tmp_path, db):
    root = tmp_path / "src"
    make_audio(root / "MESA" / "ZOOM0001.wav", 60, noise_seed=8)
    make_video(root / "DRONE" / "DJI_0001.MP4", 5, size="160x120", channels=0)
    db.add_media(_info("MESA\\ZOOM0001.wav", Role.mesa, "audio", 60, T0))
    did = db.add_media(_info("DRONE\\DJI_0001.MP4", Role.drone, "video", 5,
                             T0 + timedelta(seconds=30), channels=0))
    sync_event(db, root)
    d = db.get_sync(did)
    assert d.method == "hora"
    assert d.timeline_start_s == pytest.approx(30, abs=1e-6)


def test_hora_errada_em_3h_ainda_sincroniza_por_audio(tmp_path, db):
    root = tmp_path / "src"
    ref = make_audio(root / "MESA" / "ZOOM0001.wav", 120, noise_seed=9)
    _video_with_audio(ref, root / "CAM B" / "C0001.MP4", 50, 30)
    db.add_media(_info("MESA\\ZOOM0001.wav", Role.mesa, "audio", 120, T0))
    cid = db.add_media(_info("CAM B\\C0001.MP4", Role.camera, "video", 30,
                             T0 + timedelta(hours=3, seconds=55), channels=2))
    sync_event(db, root)
    c = db.get_sync(cid)
    assert c.method == "audio"
    assert c.timeline_start_s == pytest.approx(50, abs=0.05)


def test_referencias_encadeadas(tmp_path, db):
    root = tmp_path / "src"
    full = make_audio(tmp_path / "full.wav", 120, noise_seed=10)
    _cut(full, root / "ZOOM" / "ZOOM0001.wav", 0, 60)
    _cut(full, root / "ZOOM" / "ZOOM0002.wav", 60, 60)
    _video_with_audio(full, root / "CAM A" / "C0001.MP4", 80, 30)
    db.add_media(_info("ZOOM\\ZOOM0001.wav", Role.mesa, "audio", 60, T0))
    z2 = db.add_media(_info("ZOOM\\ZOOM0002.wav", Role.mesa, "audio", 60,
                            T0 + timedelta(seconds=60)))
    cid = db.add_media(_info("CAM A\\C0001.MP4", Role.camera, "video", 30,
                             T0 + timedelta(seconds=95), channels=2))
    sync_event(db, root)
    assert db.get_sync(z2).timeline_start_s == pytest.approx(60, abs=0.05)
    c = db.get_sync(cid)
    assert c.method == "audio"
    assert c.timeline_start_s == pytest.approx(80, abs=0.05)


def test_sem_hora_e_sem_correlacao_sequencial_com_falha(tmp_path, db):
    root = tmp_path / "src"
    make_audio(root / "MESA" / "ZOOM0001.wav", 30, noise_seed=11)
    make_video(root / "DRONE" / "DJI_0001.MP4", 4, size="160x120", channels=0)
    make_video(root / "DRONE" / "DJI_0002.MP4", 3, size="160x120", channels=0)
    db.add_media(_info("MESA\\ZOOM0001.wav", Role.mesa, "audio", 30, T0))
    d1 = db.add_media(_info("DRONE\\DJI_0001.MP4", Role.drone, "video", 4, None, channels=0))
    d2 = db.add_media(_info("DRONE\\DJI_0002.MP4", Role.drone, "video", 3, None, channels=0))
    sync_event(db, root)
    s1, s2 = db.get_sync(d1), db.get_sync(d2)
    assert s1.confidence == 0 and s2.confidence == 0
    assert s1.timeline_start_s == pytest.approx(0) and s2.timeline_start_s == pytest.approx(4)
    falhas = [f for f in db.list_falhas() if f.etapa == "sync"]
    assert {f.rel_path for f in falhas} == {"DRONE\\DJI_0001.MP4", "DRONE\\DJI_0002.MP4"}


def test_normaliza_origem_e_dias_separados(tmp_path, db):
    root = tmp_path / "src"
    make_audio(root / "MESA" / "ZOOM0001.wav", 30, noise_seed=12)
    make_video(root / "DRONE" / "DJI_0001.MP4", 3, size="160x120", channels=0)
    make_video(root / "D2" / "DJI_0009.MP4", 3, size="160x120", channels=0)
    rid = db.add_media(_info("MESA\\ZOOM0001.wav", Role.mesa, "audio", 30, T0))
    did = db.add_media(_info("DRONE\\DJI_0001.MP4", Role.drone, "video", 3,
                             T0 - timedelta(seconds=100), channels=0))
    oid = db.add_media(_info("D2\\DJI_0009.MP4", Role.drone, "video", 3,
                             T0 + timedelta(days=1), channels=0, day="making_of"))
    sync_event(db, root)
    assert db.get_sync(did).timeline_start_s == pytest.approx(0)
    assert db.get_sync(rid).timeline_start_s == pytest.approx(100)
    o = db.get_sync(oid)
    assert o.day_label == "making_of" and o.timeline_start_s == pytest.approx(0)


def test_retoma_sem_refazer_e_falha_nao_derruba(tmp_path, db):
    root = tmp_path / "src"
    make_audio(root / "MESA" / "ZOOM0001.wav", 30, noise_seed=13)
    rid = db.add_media(_info("MESA\\ZOOM0001.wav", Role.mesa, "audio", 30, T0))
    db.set_sync(SyncResult(media_id=rid, day_label="principal", timeline_start_s=0,
                           confidence=99, method="audio"))
    # arquivo inexistente com áudio: não pode derrubar o dia
    bad = db.add_media(_info("CAM A\\SUMIU.MP4", Role.camera, "video", 20,
                             T0 + timedelta(seconds=5), channels=2))
    sync_event(db, root)
    assert db.get_sync(rid).confidence == 99
    b = db.get_sync(bad)
    assert b.method == "hora" and b.timeline_start_s == pytest.approx(5)
    assert any(f.etapa == "sync" and f.rel_path == "CAM A\\SUMIU.MP4" for f in db.list_falhas())
