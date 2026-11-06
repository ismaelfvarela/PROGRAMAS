from datetime import datetime
from types import SimpleNamespace

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
        self.deleted = []

    def upload(self, path):
        self.uploads.append(path)
        return SimpleNamespace(name=f"files/{len(self.uploads)}", uri=f"file:{path}", mime_type="video/mp4")

    def delete_file(self, f):
        self.deleted.append(f.name)

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
    c = FakeClient([FileAnalysis(segmentos=[sa(seg[0]), sa(mseg[0])])])
    analyze_event(db, c, None, "m")
    # vídeo e áudio no mesmo pacote: só o vídeo é enviado; o áudio entra só como texto
    parts = c.calls[0][1]
    assert len(c.uploads) == 1 and len(c.calls) == 1
    assert parts[0] == r"ARQUIVO 1: A\C1.MP4" and parts[2] == r"ARQUIVO 2: M\m.wav" and len(parts) == 3
    assert "eu aceito" in c.calls[0][3]


def test_lotes_de_40(tmp_path):
    db = new_db(tmp_path)
    mid = db.add_media(mi("A\\C1.MP4", dur=1000))
    db.set_proxy(mid, "p.mp4", "gerado")
    ids = db.add_segments([Segment(media_id=mid, start_s=i, end_s=i + 1) for i in range(85)])
    c = FakeClient([FileAnalysis(segmentos=[sa(i) for i in ids[k:k + 40]]) for k in (0, 40, 80)])
    analyze_event(db, c, None, "m")
    assert len(c.calls) == 3 and len(c.uploads) == 1


# ------------------------------------------------------------------ revisão final


def mpause(daily=False):
    return QuotaPaused(datetime.now(), daily=daily)


def test_erro_qualquer_vira_falha_e_segue(tmp_path):
    from google.genai import errors
    db = new_db(tmp_path)
    a = db.add_media(mi(r"A\C1.MP4", dur=4000))  # longa: vai sozinha, separada de B
    b = db.add_media(mi(r"A\C2.MP4"))
    for mid in (a, b):
        db.set_proxy(mid, "p.mp4", "gerado")
    sa_ = db.add_segments([Segment(media_id=a, start_s=0, end_s=1900)])
    sb = db.add_segments([Segment(media_id=b, start_s=0, end_s=5)])
    c = FakeClient([errors.ClientError(400, {"error": {"code": 400, "message": "ruim"}}),
                    FileAnalysis(segmentos=[sa(sb[0])])])
    analyze_event(db, c, None, "m")
    f = db.list_falhas()
    assert [x.rel_path for x in f] == [r"A\C1.MP4"] and "ruim" in f[0].msg
    assert db.get_analysis(sb[0]) is not None and db.get_analysis(sa_[0]) is None


def test_erro_de_rede_vira_falha_e_segue(tmp_path):
    import httpx
    db = new_db(tmp_path)
    a = db.add_media(mi(r"A\C1.MP4", dur=4000))  # longa: vai sozinha, separada de B
    b = db.add_media(mi(r"B\C2.MP4"))
    for mid in (a, b):
        db.set_proxy(mid, "p.mp4", "gerado")
    db.add_segments([Segment(media_id=a, start_s=0, end_s=1900)])
    sb = db.add_segments([Segment(media_id=b, start_s=0, end_s=5)])
    c = FakeClient([httpx.ConnectError("sem rede"), FileAnalysis(segmentos=[sa(sb[0])])])
    analyze_event(db, c, None, "m")
    assert [x.rel_path for x in db.list_falhas()] == [r"A\C1.MP4"]
    assert db.get_analysis(sb[0]) is not None


def test_lote_envia_so_o_intervalo(tmp_path):
    db = new_db(tmp_path)
    mid = db.add_media(mi(r"A\C1.MP4", dur=1000))
    db.set_proxy(mid, "p.mp4", "gerado")
    # mais de PACOTE_MAX_SEGMENTOS (60) segmentos: a mídia vai sozinha, em lotes recortados
    ids = db.add_segments([Segment(media_id=mid, start_s=i * 10, end_s=i * 10 + 8) for i in range(65)])
    c = FakeClient([FileAnalysis(segmentos=[sa(i) for i in ids[k:k + 40]]) for k in (0, 40)])
    analyze_event(db, c, None, "m")
    assert len(c.calls) == 2
    p1, p2 = c.calls[0][1][0], c.calls[1][1][0]
    assert p1.file_data.file_uri == "file:p.mp4" and p1.file_data.mime_type == "video/mp4"
    assert (p1.video_metadata.start_offset, p1.video_metadata.end_offset) == ("0.00s", "398.00s")
    assert (p2.video_metadata.start_offset, p2.video_metadata.end_offset) == ("400.00s", "648.00s")
    assert "400.00s" in c.calls[1][3]


def test_apaga_arquivo_enviado_ao_terminar(env):
    db, mid, ids = env
    c = FakeClient([FileAnalysis(segmentos=[sa(ids[0]), sa(ids[1])])])
    analyze_event(db, c, None, "m")
    assert c.deleted == ["files/1"]
    c2 = FakeClient(exc=RuntimeError("x"))
    db2_ids = ids
    db.add_segments([Segment(media_id=mid, start_s=20, end_s=30)])
    analyze_event(db, c2, None, "m")
    assert c2.deleted == ["files/1"]  # apaga mesmo quando o lote falha


def test_tres_pausas_por_minuto_na_mesma_requisicao_viram_falha(env):
    db, mid, ids = env
    for _ in range(2):
        with pytest.raises(QuotaPaused):
            analyze_event(db, FakeClient(exc=mpause()), None, "m")
    assert db.list_falhas() == []
    c = FakeClient(exc=mpause())
    analyze_event(db, c, None, "m")  # 3ª: registra falha e segue, sem pausar
    f = db.list_falhas()
    assert len(f) == 1 and "cota por minuto" in f[0].msg
    # numa retomada da mesma etapa a requisição desistida não é refeita
    db.clear_falhas("analise")
    c4 = FakeClient(exc=mpause())
    analyze_event(db, c4, None, "m")
    assert c4.calls == [] and len(db.list_falhas()) == 1
    db.clear_quota_strikes()
    c5 = FakeClient([FileAnalysis(segmentos=[sa(ids[0]), sa(ids[1])])])
    analyze_event(db, c5, None, "m")
    assert db.get_analysis(ids[0]) is not None


def test_pausa_diaria_nao_conta_e_sucesso_zera(env):
    db, mid, ids = env
    for _ in range(4):
        with pytest.raises(QuotaPaused):
            analyze_event(db, FakeClient(exc=mpause(daily=True)), None, "m")
    with pytest.raises(QuotaPaused):
        analyze_event(db, FakeClient(exc=mpause()), None, "m")
    with pytest.raises(QuotaPaused):
        analyze_event(db, FakeClient(exc=mpause()), None, "m")
    analyze_event(db, FakeClient([FileAnalysis(segmentos=[sa(ids[0]), sa(ids[1])])]), None, "m")
    assert db.list_falhas() == [] and db.get_analysis(ids[1]) is not None


def test_prompt_video_pede_som_ambiente(env):
    db, mid, _ = env
    segs = db.list_segments(mid)
    pr = build_prompt(db.get_media(mid), segs, {})
    assert "som_ambiente" in pr and "som_ambiente_util" in pr


def test_prompt_so_audio_nao_pede_som_ambiente(tmp_path):
    db = new_db(tmp_path)
    mid = db.add_media(mi("M\G1.WAV", role=Role.mesa, kind="audio"))
    ids = db.add_segments([Segment(media_id=mid, start_s=0, end_s=10)])
    pr = build_prompt(db.get_media(mid), db.list_segments(mid), {})
    assert "som_ambiente" not in pr


def test_analise_antiga_sem_som_ambiente_valida():
    a = sa(1)
    antigo = a.model_dump()
    antigo.pop("som_ambiente", None)
    antigo.pop("som_ambiente_util", None)
    b = SceneAnalysis.model_validate(antigo)
    assert b.som_ambiente == "" and b.som_ambiente_util is False


# ------------------------------------------------------------------ pacotes (cota grátis)


def ids_do_prompt(prompt):
    import re
    return [int(x) for x in re.findall(r"segment_id=(\d+)", prompt)]


class EcoClient(FakeClient):
    """Responde com um item válido para cada segment_id do prompt."""

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.calls.append((model, parts, schema, prompt))
        if self.exc:
            raise self.exc
        return FileAnalysis(segmentos=[sa(i) for i in ids_do_prompt(prompt)])


def test_dez_midias_curtas_numa_chamada(tmp_path):
    from roteiro_ia.gemini.analysis import PACOTE_MAX_SEGMENTOS, PACOTE_MAX_VIDEO_S
    assert (PACOTE_MAX_VIDEO_S, PACOTE_MAX_SEGMENTOS) == (1800, 60)
    db = new_db(tmp_path)
    todos = []
    for k in range(10):
        mid = db.add_media(mi(rf"A\C{k}.MP4", dur=30))
        db.set_proxy(mid, f"p{k}.mp4", "gerado")
        todos += db.add_segments([Segment(media_id=mid, start_s=0, end_s=10),
                                  Segment(media_id=mid, start_s=10, end_s=20)])
    c = EcoClient()
    analyze_event(db, c, None, "m")
    assert len(c.calls) == 1 and len(c.uploads) == 10
    assert all(db.get_analysis(i) is not None for i in todos)
    parts, prompt = c.calls[0][1], c.calls[0][3]
    # texto "ARQUIVO n: rel" seguido do vídeo de cada mídia, na ordem do banco
    assert parts[0] == r"ARQUIVO 1: A\C0.MP4" and parts[1].file_data.file_uri == "file:p0.mp4"
    assert parts[18] == r"ARQUIVO 10: A\C9.MP4" and len(parts) == 20
    assert prompt.index("ARQUIVO 1:") < prompt.index(f"segment_id={todos[0]}") < prompt.index("ARQUIVO 2:")
    assert sorted(c.deleted) == sorted(f"files/{k}" for k in range(1, 11))
    assert db.list_falhas() == []


def test_pacote_respeita_limite_de_video_e_de_segmentos(tmp_path):
    db = new_db(tmp_path)
    for k in range(4):  # 4 × 700 s de vídeo → 2 pacotes (1400 s cada)
        mid = db.add_media(mi(rf"A\V{k}.MP4", dur=700))
        db.set_proxy(mid, "p.mp4", "gerado")
        db.add_segments([Segment(media_id=mid, start_s=0, end_s=700)])
    for k in range(3):  # áudios com 25 segmentos: não contam vídeo, mas contam segmentos
        mid = db.add_media(mi(rf"M\a{k}.wav", Role.mesa, "audio", 500))
        db.add_segments([Segment(media_id=mid, start_s=i, end_s=i + 1) for i in range(25)])
    c = EcoClient()
    analyze_event(db, c, None, "m")
    por_chamada = [len(ids_do_prompt(x[3])) for x in c.calls]
    assert por_chamada == [2, 2 + 50, 25]
    assert all(n <= 60 for n in por_chamada)


def test_midia_longa_vai_sozinha_em_lotes(tmp_path):
    db = new_db(tmp_path)
    curta = db.add_media(mi(r"A\C1.MP4", dur=30))
    longa = db.add_media(mi(r"A\LONGA.MP4", dur=4000))
    curta2 = db.add_media(mi(r"A\C2.MP4", dur=30))
    for mid in (curta, longa, curta2):
        db.set_proxy(mid, f"{mid}.mp4", "gerado")
    db.add_segments([Segment(media_id=curta, start_s=0, end_s=10)])
    db.add_segments([Segment(media_id=longa, start_s=i * 60, end_s=i * 60 + 59) for i in range(50)])
    db.add_segments([Segment(media_id=curta2, start_s=0, end_s=10)])
    c = EcoClient()
    analyze_event(db, c, None, "m")
    # longa: 2 lotes (40 + 10) com recorte; as duas curtas juntas num pacote
    assert len(c.calls) == 3
    longas = [x for x in c.calls if "LONGA" in x[3]]
    assert len(longas) == 2 and all(len(x[1]) == 1 and x[1][0].video_metadata for x in longas)
    pacote = next(x for x in c.calls if "LONGA" not in x[3])
    assert [p for p in pacote[1] if isinstance(p, str)] == [r"ARQUIVO 1: A\C1.MP4", r"ARQUIVO 2: A\C2.MP4"]
    assert db.list_falhas() == []


def test_pacote_valida_ids_misturados(tmp_path):
    db = new_db(tmp_path)
    a = db.add_media(mi(r"A\C1.MP4", dur=30))
    b = db.add_media(mi(r"A\C2.MP4", dur=30))
    for mid in (a, b):
        db.set_proxy(mid, "p.mp4", "gerado")
    ia = db.add_segments([Segment(media_id=a, start_s=0, end_s=10)])
    ib = db.add_segments([Segment(media_id=b, start_s=0, end_s=10)])
    # 1ª: falta o id de B; 2ª: repetido; 3ª: ids misturados mas completos (ordem trocada)
    c = FakeClient([FileAnalysis(segmentos=[sa(ia[0])]),
                    FileAnalysis(segmentos=[sa(ia[0]), sa(ia[0]), sa(ib[0])]),
                    FileAnalysis(segmentos=[sa(ib[0]), sa(ia[0])])])
    analyze_event(db, c, None, "m")
    assert len(c.calls) == 3
    assert db.get_analysis(ia[0]) and db.get_analysis(ib[0]) and db.list_falhas() == []


def test_falha_do_pacote_vira_falha_de_cada_midia(tmp_path):
    db = new_db(tmp_path)
    a = db.add_media(mi(r"A\C1.MP4", dur=30))
    b = db.add_media(mi(r"M\m.wav", Role.mesa, "audio", 30))
    db.set_proxy(a, "p.mp4", "gerado")
    db.add_segments([Segment(media_id=a, start_s=0, end_s=10)])
    db.add_segments([Segment(media_id=b, start_s=0, end_s=10)])
    c = FakeClient([FileAnalysis(segmentos=[])] * 3)
    analyze_event(db, c, None, "m")
    assert sorted(f.rel_path for f in db.list_falhas()) == [r"A\C1.MP4", r"M\m.wav"]
    assert c.deleted == ["files/1"]


def test_pacote_quota_propaga_e_apaga_uploads(tmp_path):
    db = new_db(tmp_path)
    for k in range(3):
        mid = db.add_media(mi(rf"A\C{k}.MP4", dur=30))
        db.set_proxy(mid, "p.mp4", "gerado")
        db.add_segments([Segment(media_id=mid, start_s=0, end_s=10)])
    c = FakeClient(exc=QuotaPaused(datetime.now(), daily=True))
    with pytest.raises(QuotaPaused):
        analyze_event(db, c, None, "m")
    assert len(c.calls) == 1 and sorted(c.deleted) == ["files/1", "files/2", "files/3"]
