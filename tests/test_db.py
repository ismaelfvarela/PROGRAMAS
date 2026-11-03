from datetime import datetime
from pathlib import Path

import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import (
    Highlight, MediaInfo, Quote, Role, SceneAnalysis, Segment,
)
from roteiro_ia.safety import ProtectedPathError


def _m(rel, folder="A", role=Role.camera):
    return MediaInfo(
        rel_path=rel, folder=folder, role=role, day_label="principal", kind="video",
        duration_s=10.0, fps_num=25, fps_den=1, width=1920, height=1080, rotation=0,
        audio_channels=2, created_at=datetime(2026, 1, 2, 3, 4, 5), timecode="01:00:00:00")


@pytest.fixture
def db(tmp_path):
    d = ProjectDB(tmp_path / "proj" / "p.db", Settings())
    yield d
    d.close()


def test_add_media_idempotente(db):
    a = db.add_media(_m("A\\C0001.MP4"))
    b = db.add_media(_m("A\\C0001.MP4"))
    assert a == b
    assert len(db.list_media()) == 1
    assert db.get_media(a).created_at == datetime(2026, 1, 2, 3, 4, 5)


def test_mesmo_nome_pastas_diferentes(db):
    a = db.add_media(_m("A\\C0001.MP4"))
    b = db.add_media(_m("B\\C0001.MP4", folder="B", role=Role.drone))
    assert a != b
    assert [m.rel_path for m in db.list_media(Role.drone)] == ["B\\C0001.MP4"]
    assert db.media_by_rel("B\\C0001.MP4").id == b


def test_stage_default_pendente(db):
    assert db.stage_status("x") == "pendente"
    db.set_stage("x", "pausado", "volta 10:00")
    assert db.stage_status("x") == "pausado"
    assert db.stage_detail("x") == "volta 10:00"


def test_roteiro_versoes(db):
    assert db.latest_roteiro() is None
    assert db.add_roteiro("{1}") == 1
    assert db.add_roteiro("{2}") == 2
    assert db.latest_roteiro() == "{2}"


def test_analysis_roundtrip(db):
    mid = db.add_media(_m("A\\1.MP4"))
    sid = db.add_segments([Segment(media_id=mid, start_s=0, end_s=5)])[0]
    assert db.add_segments([Segment(media_id=mid, start_s=0, end_s=5)]) == [sid]
    assert len(db.list_segments(mid)) == 1
    a = SceneAnalysis(
        segment_id=sid, momento="cerimonia", extra=None, descricao="d", pessoas=["noiva"],
        emocao_intensidade=8, emocao_tipo="choro", qualidade=7, problemas=[],
        melhores_trechos=[Highlight(start_s=1, end_s=2, reason="r")],
        falas_chave=[Quote(text="sim", start_s=1, end_s=2)], potencial_gancho=True,
        motivo_gancho="m", sugestao_lembranca=False)
    db.set_analysis(a)
    db.set_analysis(a)
    assert db.get_analysis(sid) == a
    assert db.get_analysis(999) is None


def test_proxy_e_falhas(db):
    mid = db.add_media(_m("A\\1.MP4"))
    assert db.proxy_for(mid) is None
    db.set_proxy(mid, "p.mp4", "lrf")
    db.set_proxy(mid, "q.mp4", "gerado")
    assert db.proxy_for(mid) == "q.mp4"
    db.add_falha("proxy", "A\\1.MP4", "erro")
    assert db.list_falhas()[0].msg == "erro"


def test_db_em_R_bloqueado():
    with pytest.raises(ProtectedPathError):
        ProjectDB(Path("R:\\projeto\\p.db"), Settings())
