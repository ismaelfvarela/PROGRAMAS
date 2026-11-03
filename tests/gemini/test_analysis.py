from datetime import datetime

import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini.analysis import FileAnalysis, analyze_event, build_prompt, segment_speech
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.models import (Highlight, MediaInfo, Quote, Role, SceneAnalysis, Segment, SyncResult,
                               Transcript, Word)


def mi(rel, role=Role.camera, kind="video", dur=100.0, day="principal"):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=role, day_label=day, kind=kind,
                     duration_s=dur, fps_num=30, fps_den=1, width=1920, height=1080, rotation=0,
                     audio_channels=2)


def sa(sid, hl=None, qs=None):
    return SceneAnalysis(segment_id=sid, momento="beijo", descricao="d", pessoas=["A"],
                         emocao_intensidade=8, emocao_tipo="choro", qualidade=7, problemas=[],
                         melhores_trechos=hl or [], falas_chave=qs or [], potencial_gancho=False,
                         sugestao_lembranca=False)


class FakeClient:
    def __init__(self, responses=None, exc=None):
        self.responses = list(responses or [])
        self.exc = exc
        self.calls = []
        self.uploads = []

    def upload(self, path):
        self.uploads.append(path)
        return f"file:{path}"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.calls.append((model, parts, schema, prompt))
        if self.exc:
            raise self.exc
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def new_db(tmp_path):
    s = Settings(system_dir=str(tmp_path / "sys"), protected_roots=[])
    return ProjectDB(tmp_path / "p.db", s)


@pytest.fixture
def env(tmp_path):
    db = new_db(tmp_path)
    mid = db.add_media(mi("A\\C1.MP4"))
    db.set_proxy(mid, str(tmp_path / "prx.mp4"), "gerado")
    ids = db.add_segments([Segment(media_id=mid, start_s=0, end_s=10),
                           Segment(media_id=mid, start_s=10, end_s=20)])
    db.set_transcript(Transcript(media_id=mid, source_role=Role.camera,
                                 words=[Word(text="sim", start_s=1, end_s=2),
                                        Word(text="aceito", start_s=12, end_s=13)]))
    return db, mid, ids


def test_prompt_contem_falas_e_ids(env):
    db, mid, ids = env
    segs = db.list_segments(mid)
    sp = {s.id: segment_speech(db, db.get_media(mid), s) for s in segs}
    pr = build_prompt(db.get_media(mid), segs, sp)
    assert f"segment_id={ids[0]}" in pr and f"segment_id={ids[1]}" in pr
    assert "sim" in pr and "aceito" in pr and "extra" in pr and "RELATIVOS AO ARQUIVO" in pr


def test_analise_grava_por_segmento(env):
    db, mid, ids = env
    c = FakeClient([FileAnalysis(segmentos=[sa(ids[0]), sa(ids[1])])])
    analyze_event(db, c, None, "m")
    assert db.get_analysis(ids[0]) and db.get_analysis(ids[1])
    assert len(c.uploads) == 1 and len(c.calls) == 1


def test_pula_ja_analisados(env):
    db, mid, ids = env
    db.set_analysis(sa(ids[0]))
    c = FakeClient([FileAnalysis(segmentos=[sa(ids[1])])])
    analyze_event(db, c, None, "m")
    assert f"segment_id={ids[0]} " not in c.calls[0][3]
    c2 = FakeClient()
    analyze_event(db, c2, None, "m")
    assert c2.uploads == [] and c2.calls == []


def test_tempos_recortados_ao_segmento(env):
    db, mid, ids = env
    a = sa(ids[0], hl=[Highlight(start_s=-5, end_s=4, reason="x"),
                       Highlight(start_s=15, end_s=18, reason="fora")],
           qs=[Quote(text="q", start_s=8, end_s=30)])
    c = FakeClient([FileAnalysis(segmentos=[a, sa(ids[1])])])
    analyze_event(db, c, None, "m")
    r = db.get_analysis(ids[0])
    assert [(h.start_s, h.end_s) for h in r.melhores_trechos] == [(0, 4)]
    assert [(q.start_s, q.end_s) for q in r.falas_chave] == [(8, 10)]


def test_quota_propaga(env):
    db, mid, ids = env
    c = FakeClient(exc=QuotaPaused(datetime.now()))
    with pytest.raises(QuotaPaused):
        analyze_event(db, c, None, "m")


def test_id_invalido_reenvia(env):
    db, mid, ids = env
    bad = FileAnalysis(segmentos=[sa(ids[0]), sa(999)])
    c = FakeClient([bad, ValueError("json"), FileAnalysis(segmentos=[sa(ids[0]), sa(ids[1])])])
    analyze_event(db, c, None, "m")
    assert len(c.calls) == 3 and db.get_analysis(ids[1])
    assert db.list_falhas() == []


def test_falha_apos_3_tentativas(env):
    db, mid, ids = env
    bad = FileAnalysis(segmentos=[sa(ids[0])])
    c = FakeClient([bad, bad, bad])
    analyze_event(db, c, None, "m")
    f = db.list_falhas()
    assert len(f) == 1 and f[0].etapa == "analise" and f[0].rel_path == "A\\C1.MP4"
    assert db.get_analysis(ids[0]) is None


def test_video_sem_proxy_falha(tmp_path):
    db = new_db(tmp_path)
    mid = db.add_media(mi("A\\C1.MP4"))
    db.add_segments([Segment(media_id=mid, start_s=0, end_s=5)])
    c = FakeClient()
    analyze_event(db, c, None, "m")
    assert "sem proxy" in db.list_falhas()[0].msg and c.uploads == []


def test_fala_da_fonte_melhor_e_audio_sem_upload(tmp_path):
    db = new_db(tmp_path)
    cam = db.add_media(mi("A\\C1.MP4", dur=50))
    mesa = db.add_media(mi("M\\m.wav", Role.mesa, "audio", 500))
    db.set_proxy(cam, "p.mp4", "gerado")
    db.set_sync(SyncResult(media_id=cam, day_label="principal", timeline_start_s=100,
                           confidence=9, method="audio"))
    db.set_sync(SyncResult(media_id=mesa, day_label="principal", timeline_start_s=0,
                           confidence=9, method="audio"))
    db.set_transcript(Transcript(media_id=mesa, source_role=Role.mesa,
                                 words=[Word(text="eu", start_s=112, end_s=113),
                                        Word(text="aceito", start_s=114, end_s=115)]))
    seg = db.add_segments([Segment(media_id=cam, start_s=10, end_s=20)])
    mseg = db.add_segments([Segment(media_id=mesa, start_s=0, end_s=5)])
    assert segment_speech(db, db.get_media(cam), db.list_segments(cam)[0]) == "eu aceito"
    c = FakeClient([FileAnalysis(segmentos=[sa(seg[0])]), FileAnalysis(segmentos=[sa(mseg[0])])])
    analyze_event(db, c, None, "m")
    assert len(c.uploads) == 1 and c.calls[1][1] == []


def test_lotes_de_40(tmp_path):
    db = new_db(tmp_path)
    mid = db.add_media(mi("A\\C1.MP4", dur=1000))
    db.set_proxy(mid, "p.mp4", "gerado")
    ids = db.add_segments([Segment(media_id=mid, start_s=i, end_s=i + 1) for i in range(85)])
    c = FakeClient([FileAnalysis(segmentos=[sa(i) for i in ids[k:k + 40]]) for k in (0, 40, 80)])
    analyze_event(db, c, None, "m")
    assert len(c.calls) == 3 and len(c.uploads) == 1
