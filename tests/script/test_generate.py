import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import MediaInfo, Quote, Role, SceneAnalysis, Segment, SyncResult, TrackInfo
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.script.generate import (REGRAS_FOKUSS, MusicSuggestion, Piece, Roteiro, SceneRef,
                                        build_catalog, generate_roteiro, music_shortlist,
                                        validate_refs)


def mi(rel, dur=100.0, day="principal"):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=Role.camera, day_label=day,
                     kind="video", duration_s=dur, fps_num=30, fps_den=1, width=1920, height=1080,
                     rotation=0, audio_channels=2)


def sa(sid, momento="votos", fala=None, gancho=False):
    return SceneAnalysis(segment_id=sid, momento=momento, descricao=f"desc {momento}",
                         pessoas=["noiva"], emocao_intensidade=8, emocao_tipo="choro", qualidade=7,
                         problemas=[], melhores_trechos=[],
                         falas_chave=[Quote(text=fala, start_s=1, end_s=2)] if fala else [],
                         potencial_gancho=gancho, sugestao_lembranca=False)


def tr(path, bpm=80.0, perfil="calma", vocals=False):
    return TrackInfo(path=path, bpm=bpm, beats_s=[], downbeats_s=[], energy=[], duration_s=200.0,
                     has_vocals=vocals, perfil=perfil, mtime=1.0)


def ref(rel="A\\C0001.MP4", a=0.0, b=5.0):
    return SceneRef(rel_path=rel, start_s=a, end_s=b, descricao="cena", fala=None, motivo=None)


def piece(tipo="episodio", numero=1, abertura=None, dev=None, gancho="default", trilhas=None):
    return Piece(tipo=tipo, numero=numero, titulo="T", tema="tema", abertura=abertura or ref(),
                 desenvolvimento=dev if dev is not None else [ref(a=5, b=10)],
                 gancho=ref(a=10, b=15) if gancho == "default" else gancho,
                 gancho_resolve_em=None, curva_emocao=[5, 7, 9], duracao_estimada_s=360,
                 misturas=[], trilhas=trilhas or [], termos_musicbed=["romantic"])


def rot(*pecas):
    return Roteiro(arco="arco", pecas=list(pecas), alertas=[])


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.uploads = []

    def upload(self, path):
        self.uploads.append(path)
        return "file"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.calls.append((model, parts, schema, prompt))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return Roteiro.model_validate_json(r.model_dump_json())


@pytest.fixture
def env(tmp_path):
    s = Settings(system_dir=str(tmp_path / "sys"), protected_roots=[])
    db = ProjectDB(tmp_path / "p.db", s)
    a = db.add_media(mi("A\\C0001.MP4", dur=60.0))
    b = db.add_media(mi("B\\C0001.MP4", dur=20.0))
    ids = db.add_segments([Segment(media_id=a, start_s=0, end_s=30),
                           Segment(media_id=b, start_s=0, end_s=20)])
    db.set_analysis(sa(ids[0], "votos", fala="eu aceito"))
    db.set_analysis(sa(ids[1], "festa", gancho=True))
    db.set_sync(SyncResult(media_id=a, day_label="principal", timeline_start_s=500, confidence=9,
                           method="audio"))
    db.set_sync(SyncResult(media_id=b, day_label="principal", timeline_start_s=100, confidence=9,
                           method="audio"))
    idx = MusicIndex(tmp_path / "t.db", s)
    idx.upsert(tr("M:\\Trilhas\\lenta.mp3"))
    idx.upsert(tr("M:\\Trilhas\\rapida.mp3", bpm=128, perfil="intensa", vocals=True))
    yield db, idx
    db.close()
    idx.close()


def test_validate_ref_inexistente(env):
    db, idx = env
    r = rot(piece(dev=[ref(), ref("Z\\NAO.MP4")], gancho=None))
    probs = validate_refs(r, db, idx)
    assert len(probs) == 1 and "Z\\NAO.MP4" in probs[0]


def test_validate_intervalo_fora_da_duracao(env):
    db, idx = env
    r = rot(piece(dev=[ref("B\\C0001.MP4", 10, 25)], gancho=None))
    probs = validate_refs(r, db, idx)
    assert len(probs) == 1 and "B\\C0001.MP4" in probs[0]
    assert validate_refs(rot(piece(dev=[ref("B\\C0001.MP4", 10, 20.4)], gancho=None)), db, idx) == []
    assert validate_refs(rot(piece(dev=[ref("A\\C0001.MP4", 8, 8)], gancho=None)), db, idx)


def test_ref_usa_caminho_relativo(env):
    db, idx = env
    # 25 s cabe em A (60 s) mas não em B (20 s): cada caminho resolve para a sua mídia
    assert validate_refs(rot(piece(dev=[ref("A\\C0001.MP4", 20, 25)], gancho=None)), db, idx) == []
    assert validate_refs(rot(piece(dev=[ref("B\\C0001.MP4", 20, 25)], gancho=None)), db, idx)
    # barra normal e maiúsculas/minúsculas são aceitas e normalizadas para a grafia do banco
    r = rot(piece(dev=[ref("b/c0001.mp4", 1, 2)], gancho=None))
    assert validate_refs(r, db, idx) == []
    assert r.pecas[0].desenvolvimento[0].rel_path == "B\\C0001.MP4"


def test_validate_trilha_e_numeracao(env):
    db, idx = env
    ok = MusicSuggestion(origem="biblioteca", path="M:\\Trilhas\\lenta.mp3", titulo="lenta",
                         bpm=80, clima="calmo", motivo="m", padrao_corte="1-3", exige_licenca=False)
    bad = ok.model_copy(update={"path": "M:\\Trilhas\\nao_existe.mp3"})
    r = rot(piece(numero=1, trilhas=[ok, bad]), piece(numero=3, gancho=None))
    probs = validate_refs(r, db, idx)
    assert any("nao_existe" in p for p in probs)
    assert any("numerad" in p for p in probs)
    r2 = rot(piece(numero=1, gancho=None), piece(numero=2, gancho=None))
    assert any("gancho" in p.lower() for p in validate_refs(r2, db, idx))


def test_popular_marca_exige_licenca(env):
    db, idx = env
    pop = MusicSuggestion(origem="popular", path=None, titulo="Hit", bpm=None, clima="alegre",
                          motivo="m", padrao_corte="2-4", exige_licenca=False)
    r = rot(piece(trilhas=[pop], gancho=None))
    assert validate_refs(r, db, idx) == []
    assert r.pecas[0].trilhas[0].exige_licenca is True


def test_build_catalog(env):
    db, idx = env
    cat = build_catalog(db)
    lines = cat.strip().splitlines()
    assert len(lines) == 2
    # B começa antes na linha do tempo (100 s) que A (500 s)
    assert lines[0].startswith("B\\C0001.MP4 | 0.0–20.0")
    assert "festa" in lines[0] and "gancho: sim" in lines[0]
    assert lines[1].startswith("A\\C0001.MP4 | 0.0–30.0") and '"eu aceito"' in lines[1]
    assert "emoção 8 choro" in lines[1] and "qualidade 7" in lines[1] and "gancho: não" in lines[1]


def test_music_shortlist_variada(tmp_path):
    s = Settings(system_dir=str(tmp_path / "sys"), protected_roots=[])
    idx = MusicIndex(tmp_path / "t.db", s)
    for i in range(10):
        idx.upsert(tr(f"M:\\c{i:02d}.mp3", bpm=70, perfil="calma"))
    idx.upsert(tr("M:\\x.mp3", bpm=130, perfil="intensa"))
    idx.upsert(tr("M:\\y.mp3", bpm=100, perfil="crescente"))
    out = music_shortlist(idx, n=3)
    assert len(out.strip().splitlines()) == 3
    assert "M:\\x.mp3" in out and "M:\\y.mp3" in out and "M:\\c00.mp3" in out
    assert music_shortlist(idx, n=3) == out
    assert "BPM" in out and "calma" in out and "instrumental" in out
    idx.close()


def test_gera_e_grava(env):
    db, idx = env
    good = rot(piece(numero=1, gancho=None))
    c = FakeClient([good])
    r = generate_roteiro(db, c, idx, None, "m", 3, {"trailer", "teaser"})
    assert len(c.calls) == 1 and c.uploads == [] and c.calls[0][1] == []
    assert c.calls[0][2] is Roteiro
    pr = c.calls[0][3]
    assert REGRAS_FOKUSS in pr and "A\\C0001.MP4 | 0.0–30.0" in pr and "M:\\Trilhas\\lenta.mp3" in pr
    assert "3 episódios" in pr and "trailer" in pr and "teaser" in pr
    assert Roteiro.model_validate_json(db.latest_roteiro()) == r


def test_corrige_e_remove_refs_ruins(env):
    db, idx = env
    bad = rot(piece(numero=1, dev=[ref(a=5, b=10), ref("Z\\RUIM.MP4", 0, 3)], gancho=None))
    c = FakeClient([bad])
    r = generate_roteiro(db, c, idx, None, "m", None, set())
    assert len(c.calls) == 3
    assert "Z\\RUIM.MP4" in c.calls[1][3] and '"arco"' in c.calls[1][3]
    assert [x.rel_path for x in r.pecas[0].desenvolvimento] == ["A\\C0001.MP4"]
    assert any("Z\\RUIM.MP4" in a for a in r.alertas)
    assert Roteiro.model_validate_json(db.latest_roteiro()) == r


def test_corrige_na_segunda_rodada(env):
    db, idx = env
    bad = rot(piece(numero=1, dev=[ref("Z\\RUIM.MP4", 0, 3)], gancho=None))
    good = rot(piece(numero=1, gancho=None))
    c = FakeClient([bad, good])
    r = generate_roteiro(db, c, idx, None, "m", None, set())
    assert len(c.calls) == 2 and r.alertas == []


def test_remove_abertura_e_peca_invalidas(env):
    db, idx = env
    bad_open = piece(numero=1, abertura=ref("Z\\X.MP4"), dev=[ref(a=1, b=2), ref(a=3, b=4)],
                     gancho=None)
    lost = piece(tipo="trailer", numero=None, abertura=ref("Z\\Y.MP4"), dev=[ref("Z\\W.MP4")],
                 gancho=None)
    c = FakeClient([rot(bad_open, lost)])
    r = generate_roteiro(db, c, idx, None, "m", None, {"trailer"})
    assert len(r.pecas) == 1
    p = r.pecas[0]
    assert (p.abertura.start_s, p.abertura.end_s) == (1, 2)
    assert [(x.start_s, x.end_s) for x in p.desenvolvimento] == [(3, 4)]
    assert any("trailer" in a.lower() for a in r.alertas)


def test_ajuste_reaproveita_sem_reanalisar(env):
    db, idx = env
    prev = rot(piece(numero=1, gancho=None))
    prev.arco = "ARCO ANTERIOR"
    db.add_roteiro(prev.model_dump_json())
    novo = rot(piece(numero=1, gancho=None))
    c = FakeClient([novo])
    generate_roteiro(db, c, idx, None, "m", None, set(), pedido_ajuste="encurtar o episódio 1")
    pr = c.calls[0][3]
    assert "ARCO ANTERIOR" in pr and "encurtar o episódio 1" in pr
    assert c.uploads == [] and c.calls[0][1] == []


# ------------------------------------------------------------------ revisão final


def _audio(rel, dur=100.0):
    return mi(rel, dur).model_copy(update={"kind": "audio", "role": Role.mesa, "width": 0,
                                           "height": 0})


def test_catalogo_marca_so_audio_e_regra(env):
    db, idx = env
    m = db.add_media(_audio(r"E - H4\ZOOM0001.WAV"))
    sid = db.add_segments([Segment(media_id=m, start_s=0, end_s=10)])
    db.set_analysis(sa(sid[0], "votos", fala="sim"))
    linha = next(l for l in build_catalog(db).splitlines() if l.startswith(r"E - H4\ZOOM0001.WAV"))
    assert "[só áudio]" in linha
    assert "[só áudio]" in REGRAS_FOKUSS and "fala" in REGRAS_FOKUSS


def test_validate_cena_so_audio(env):
    db, idx = env
    db.add_media(_audio(r"E - H4\ZOOM0001.WAV"))
    r = rot(piece(numero=1, dev=[ref(r"E - H4\ZOOM0001.WAV", 0, 5)], gancho=None))
    probs = validate_refs(r, db, idx)
    assert any("use como fala sobre uma cena de vídeo" in p for p in probs)


def test_dias_em_ordem_cronologica(tmp_path):
    from datetime import datetime
    s = Settings(system_dir=str(tmp_path / "sys"), protected_roots=[])
    db = ProjectDB(tmp_path / "p.db", s)
    for rel, day, quando in ((r"A\Z.MP4", "zz casamento", datetime(2023, 9, 9, 15)),
                             (r"B\P.MP4", "aa pre-wedding", datetime(2023, 8, 1, 10)),
                             (r"C\S.MP4", "mm sem data", None),
                             (r"D\L.MP4", "bb lua de mel", datetime(2023, 9, 20, 10))):
        m = db.add_media(mi(rel, day=day).model_copy(update={"created_at": quando}))
        sid = db.add_segments([Segment(media_id=m, start_s=0, end_s=5)])
        db.set_analysis(sa(sid[0]))
    dias = [l.split(" | dia ")[1].split(" | ")[0] for l in build_catalog(db).splitlines()]
    assert dias == ["aa pre-wedding", "zz casamento", "bb lua de mel", "mm sem data"]
    c = FakeClient([rot(piece(numero=1, abertura=ref(r"A\Z.MP4", 0, 1), dev=[], gancho=None))])
    generate_roteiro(db, c, MusicIndex(tmp_path / "t.db", s), None, "m", None, set())
    assert "dias em ordem cronológica" in c.calls[0][3]


class TokenClient(FakeClient):
    def __init__(self, responses, tokens):
        super().__init__(responses)
        self.tokens = tokens
        self.contados = []

    def count_tokens(self, model, text):
        self.contados.append(text)
        return self.tokens


def test_prompt_grande_compacta_catalogo(env):
    db, idx = env
    a = db.media_by_rel("A\\C0001.MP4").id
    fraco, longo = db.add_segments([Segment(media_id=a, start_s=30, end_s=40),
                                    Segment(media_id=a, start_s=40, end_s=50)])
    db.set_analysis(sa(fraco, "extra").model_copy(update={"emocao_intensidade": 1, "qualidade": 2}))
    db.set_analysis(sa(longo, "pista").model_copy(update={"descricao": "x" * 500}))
    good = rot(piece(numero=1, gancho=None))
    c = TokenClient([good], tokens=400_000)
    r = generate_roteiro(db, c, idx, None, "m", None, set())
    pr = c.calls[0][3]
    assert "30.0–40.0" not in pr  # emoção ≤ 2 e qualidade ≤ 3, sem fala e sem gancho: fora
    assert "x" * 120 in pr and "x" * 121 not in pr
    assert any("compact" in al.lower() for al in r.alertas)
    c2 = TokenClient([good], tokens=1000)
    r2 = generate_roteiro(db, c2, idx, None, "m", None, set())
    assert "30.0–40.0" in c2.calls[0][3] and not any("compact" in al.lower() for al in r2.alertas)


def test_gancho_removido_zera_resolve_em(env):
    db, idx = env
    p = piece(numero=1, gancho=ref("Z\\RUIM.MP4", 0, 1))
    p.gancho_resolve_em = "abertura do episódio 2"
    c = FakeClient([rot(p, piece(numero=2, gancho=None))])
    r = generate_roteiro(db, c, idx, None, "m", None, set())
    assert r.pecas[0].gancho is None and r.pecas[0].gancho_resolve_em is None


def test_correcao_no_ajuste_inclui_pedido(env):
    db, idx = env
    db.add_roteiro(rot(piece(numero=1, gancho=None)).model_dump_json())
    bad = rot(piece(numero=1, dev=[ref("Z\\RUIM.MP4", 0, 3)], gancho=None))
    good = rot(piece(numero=1, gancho=None))
    c = FakeClient([bad, good])
    generate_roteiro(db, c, idx, None, "m", None, set(), pedido_ajuste="mais votos no ep 1")
    assert len(c.calls) == 2 and "mais votos no ep 1" in c.calls[1][3]


def _som(env, util, texto="risos | aplausos"):
    db, idx = env
    seg = db.list_segments()[1]  # B: emoção 8 -> deixa fraco para testar compactação
    a = db.get_analysis(seg.id)
    db.set_analysis(a.model_copy(update={"som_ambiente": texto, "som_ambiente_util": util,
                                         "emocao_intensidade": 1, "qualidade": 2,
                                         "potencial_gancho": False}))
    return db


def test_catalogo_mostra_som_e_estrela(env):
    db = _som(env, True)
    linha = [l for l in build_catalog(db).splitlines() if l.startswith("B\\")][0]
    assert "som: risos / aplausos ★" in linha



def test_catalogo_som_sem_estrela(env):
    db = _som(env, False)
    linha = [l for l in build_catalog(db).splitlines() if l.startswith("B\\")][0]
    assert "som: risos / aplausos" in linha and "★" not in linha


def test_compactacao_mantem_segmento_com_som_util(env):
    db = _som(env, True)
    assert any(l.startswith("B\\") for l in build_catalog(db, compact=True).splitlines())
    db = _som(env, False)
    assert not any(l.startswith("B\\") for l in build_catalog(db, compact=True).splitlines())


def test_regra_som_camera_e_campo_padrao():
    assert "usar_som_camera" in REGRAS_FOKUSS
    assert ref().usar_som_camera is False


def test_validate_normaliza_som_camera_sem_audio(env):
    db, idx = env
    sem = db.add_media(mi("C\\C0001.MP4", dur=20.0).model_copy(update={"audio_channels": 0}))
    r = rot(piece(abertura=ref("A\\C0001.MP4", 0, 5).model_copy(update={"usar_som_camera": True}),
                  dev=[ref("C\\C0001.MP4", 0, 5).model_copy(update={"usar_som_camera": True})],
                  gancho=None))
    validate_refs(r, db, idx)
    assert r.pecas[0].abertura.usar_som_camera is True
    assert r.pecas[0].desenvolvimento[0].usar_som_camera is False
    assert any("C\\C0001.MP4" in a and "som da câmera" in a for a in r.alertas)
