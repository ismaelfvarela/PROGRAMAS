import json
import subprocess
from pathlib import Path

import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.inventory import scan
from roteiro_ia.media import proxies as px
from roteiro_ia.media.proxies import ffmpeg_proxy_cmd, lrf_compatible, make_proxies, proxy_path
from roteiro_ia.media.tools import ffprobe_bin
from roteiro_ia.models import FolderAssignment, MediaInfo, Role
from roteiro_ia.paths import build_event_paths
from fixtures.make_media import make_video


def _m(rel="A\\C0001.MP4", w=1920, h=1080, rot=0, ch=2, fn=30000, fd=1001, kind="video", dur=2.0):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=Role.camera, day_label="D1",
                     kind=kind, duration_s=dur, fps_num=fn, fps_den=fd, width=w, height=h,
                     rotation=rot, audio_channels=ch)


@pytest.fixture
def env(tmp_path):
    s = Settings(work_drive=str(tmp_path / "work"), e_root=str(tmp_path / "E"),
                 g_root=str(tmp_path / "G"), system_dir=str(tmp_path / "sys"),
                 music_root=str(tmp_path / "music"),
                 protected_roots=[str(tmp_path / "src")])
    src = tmp_path / "src" / "2026-05-10 Teste"
    src.mkdir(parents=True)
    p = build_event_paths(src, s)
    with ProjectDB(tmp_path / "p.db", s) as db:
        yield s, p, db, src


def _scan(src, db):
    scan(src, [FolderAssignment(folder="A", role=Role.camera)], db)


def test_proxy_path_por_subpasta(env):
    s, p, db, src = env
    a = proxy_path(_m("A\\C0001.MP4"), p)
    b = proxy_path(_m("B\\C0001.MP4"), p)
    assert a != b
    assert a == p.proxies_dir / "A" / "C0001_Proxy.mp4"


def test_cmd_mantem_fps_e_canais():
    c = ffmpeg_proxy_cmd(Path("a.mp4"), Path("b.mp4"), _m(ch=4))
    assert c[c.index("-r") + 1] == "30000/1001"
    assert c[c.index("-ac") + 1] == "4"
    assert "h264_nvenc" in c
    assert c[c.index("-vf") + 1] == "scale=-2:480"
    assert "libx264" in ffmpeg_proxy_cmd(Path("a"), Path("b"), _m(), gpu=False)


def test_cmd_vertical_lado_menor_480():
    c = ffmpeg_proxy_cmd(Path("a"), Path("b"), _m(w=1080, h=1920))
    assert c[c.index("-vf") + 1] == "scale=480:-2"


def test_cmd_rotacao_90_troca_orientacao():
    c = ffmpeg_proxy_cmd(Path("a"), Path("b"), _m(w=1920, h=1080, rot=90))
    assert c[c.index("-vf") + 1] == "scale=480:-2"
    c = ffmpeg_proxy_cmd(Path("a"), Path("b"), _m(w=1080, h=1920, rot=270))
    assert c[c.index("-vf") + 1] == "scale=-2:480"


def test_cmd_sem_audio_e_sem_fps():
    c = ffmpeg_proxy_cmd(Path("a"), Path("b"), _m(ch=0, fn=0, fd=0))
    assert "-an" in c and "-ac" not in c and "-r" not in c


def test_proxy_real_mesmo_fps(env, monkeypatch):
    s, p, db, src = env
    make_video(src / "A" / "C0001.MP4", 2, fps="60000/1001", size="1280x720", channels=2)
    _scan(src, db)
    m = db.list_media()[0]
    monkeypatch.setattr(px, "_FORCE_CPU", True)
    make_proxies(db, p, s, src)
    out = Path(db.proxy_for(m.id))
    assert out == proxy_path(m, p) and out.is_file()
    assert not list(out.parent.glob("*.part.mp4"))
    r = subprocess.run([ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=r_frame_rate,height", "-of", "json", str(out)],
                       capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    assert st["r_frame_rate"] == "60000/1001" and st["height"] == 480


def test_lrf_reaproveitado(env, monkeypatch):
    s, p, db, src = env
    make_video(src / "A" / "C0001.MP4", 2, size="640x360")
    make_video(src / "A" / "tmp.mp4", 2, size="320x180")
    (src / "A" / "tmp.mp4").rename(src / "A" / "C0001.LRF")
    _scan(src, db)
    m = db.list_media()[0]
    assert lrf_compatible(src / "A" / "C0001.LRF", m)
    monkeypatch.setattr(px, "_run", lambda *a, **k: pytest.fail("não deveria rodar o ffmpeg"))
    make_proxies(db, p, s, src)
    out = Path(db.proxy_for(m.id))
    assert out.is_file() and out.name == "C0001_Proxy.mp4"


def test_lrf_incompativel(env):
    s, p, db, src = env
    make_video(src / "A" / "C0001.MP4", 2, size="640x360")
    make_video(src / "A" / "tmp.mp4", 2, size="640x360", fps="25/1")
    (src / "A" / "tmp.mp4").rename(src / "A" / "C0001.LRF")
    _scan(src, db)
    assert not lrf_compatible(src / "A" / "C0001.LRF", db.list_media()[0])


def test_nao_escreve_na_origem(env, monkeypatch):
    s, p, db, src = env
    make_video(src / "A" / "C0001.MP4", 1, size="320x180")
    _scan(src, db)
    before = sorted(str(x) for x in src.rglob("*"))
    monkeypatch.setattr(px, "_FORCE_CPU", True)
    make_proxies(db, p, s, src)
    assert sorted(str(x) for x in src.rglob("*")) == before
    assert Path(db.proxy_for(db.list_media()[0].id)).is_relative_to(p.proxies_dir)


def test_fallback_falha_e_retomada(env, monkeypatch):
    s, p, db, src = env
    make_video(src / "A" / "C0001.MP4", 1, size="320x180")
    _scan(src, db)
    m = db.list_media()[0]
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "boom")
    monkeypatch.setattr(px.proc, "run", fake_run)
    make_proxies(db, p, s, src)
    assert len(calls) == 2 and "h264_nvenc" in calls[0] and "libx264" in calls[1]
    assert db.proxy_for(m.id) is None
    assert db.list_falhas()[0].etapa == "proxies"
    out = proxy_path(m, p)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"x")
    db.set_proxy(m.id, str(out), "gerado")
    calls.clear()
    make_proxies(db, p, s, src)
    assert calls == []


def test_audio_ignorado(env, monkeypatch):
    s, p, db, src = env
    db.add_media(_m("B\\a.wav", kind="audio", ch=1))
    monkeypatch.setattr(px, "_run", lambda *a, **k: pytest.fail("x"))
    make_proxies(db, p, s, src)


def test_disco_de_trabalho_cheio_pausa_sem_falha(env, monkeypatch):
    s, p, db, src = env
    db.add_media(_m(r"A\C0001.MP4"))
    db.add_media(_m(r"A\C0002.MP4"))
    chamadas = []
    monkeypatch.setattr(px, "_run", lambda cmd, timeout: chamadas.append(cmd) or (False, "x"))
    livre = iter([10.0, 1.5])
    monkeypatch.setattr(px, "_free_gb", lambda path: next(livre))
    with pytest.raises(OSError) as ei:
        make_proxies(db, p, s, src)
    assert "Disco de trabalho cheio" in str(ei.value)
    # o 1º arquivo foi tentado (e falhou no ffmpeg); o 2º não começou
    assert [f.rel_path for f in db.list_falhas()] == [r"A\C0001.MP4"]
