import json
from pathlib import Path

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import MediaInfo, Role
from roteiro_ia.paths import build_event_paths
from roteiro_ia.premiere.job import write_job

EVENTO = "2023-01-01 TESTE"


def env(tmp_path):
    s = Settings(protected_roots=[str(tmp_path / "R")], work_drive=str(tmp_path / "Y"),
                 e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"),
                 system_dir=str(tmp_path / "SIS"), music_root=str(tmp_path / "M"))
    src = tmp_path / "R" / EVENTO
    src.mkdir(parents=True)
    return s, build_event_paths(src, s)


def mi(rel):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=Role.camera,
                     day_label="principal", kind="video", duration_s=10, fps_num=30, fps_den=1,
                     width=1, height=1, rotation=0, audio_channels=2)


def test_job_json_utf8(tmp_path):
    s, p = env(tmp_path)
    assert "VÍDEOS" in str(p.prproj_path) and "EDIÇÃO" in str(p.work_dir)
    xml = p.analysis_dir / f"{EVENTO} - PREMIERE.xml"
    with ProjectDB(p.db_path, s) as db:
        a = db.add_media(mi("A\\C0001.MP4"))
        b = db.add_media(mi("B\\C0002.MP4"))
        db.add_media(mi("B\\C0003.MP4"))  # sem proxy
        px = p.proxies_dir / "A" / "C0001_Proxy.mp4"
        px.parent.mkdir(parents=True)
        px.write_bytes(b"x")
        db.set_proxy(a, str(px), "gerado")
        db.set_proxy(b, str(p.proxies_dir / "B" / "sumiu.mp4"), "gerado")  # arquivo não existe
        out = write_job(p, s, xml, db)
    assert out == p.analysis_dir / "job.json"
    job = json.loads(out.read_text(encoding="utf-8"))
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and json.loads(raw.decode("utf-8")) == job
    assert job["evento"] == EVENTO
    assert job["xml"] == str(xml)
    assert job["prproj"] == str(p.prproj_path) and "VÍDEOS" in job["prproj"]
    assert job["backup_dir"] == str(p.backup_dir) and "EDIÇÃO" in job["backup_dir"]
    assert job["export_dir"] == str(p.export_dir)
    assert job["proxies"] == [{"original": str(p.source_dir / "A" / "C0001.MP4"), "proxy": str(px)}]
    copia = Path(s.system_dir) / "ultimo_job.json"
    assert json.loads(copia.read_text(encoding="utf-8")) == job


def test_job_prproj_nao_sobrescreve(tmp_path):
    s, p = env(tmp_path)
    p.prproj_path.parent.mkdir(parents=True)
    p.prproj_path.write_bytes(b"projeto existente")
    with ProjectDB(p.db_path, s) as db:
        out = write_job(p, s, p.analysis_dir / "x.xml", db)
    job = json.loads(out.read_text(encoding="utf-8"))
    assert job["prproj"] == str(p.premiere_dir / f"{EVENTO}_v2.prproj")
    assert p.prproj_path.read_bytes() == b"projeto existente"


def test_job_abre_banco_sozinho(tmp_path):
    s, p = env(tmp_path)
    with ProjectDB(p.db_path, s) as db:
        db.add_media(mi("A\\C0001.MP4"))
    out = write_job(p, s, p.analysis_dir / "x.xml")
    assert json.loads(out.read_text(encoding="utf-8"))["proxies"] == []
