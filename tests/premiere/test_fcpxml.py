import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import AudioStats, MediaInfo, Role, SyncResult, TrackInfo
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.paths import EventPaths
from roteiro_ia.premiere.fcpxml import (AUDIO_TRACKS, build_sequence, build_xml, pathurl,
                                        timebase, write_xml)
from roteiro_ia.script.generate import MusicSuggestion, Piece, Roteiro, SceneRef

NTSC = 30000 / 1001
SRC = Path(r"R:\2023\EVENTO")
MUSIC = r"M:\TRILHAS\Calma\Piano.wav"


def _settings(tmp_path):
    return Settings(work_drive=str(tmp_path / "work"), e_root=str(tmp_path / "e"),
                    g_root=str(tmp_path / "g"), system_dir=str(tmp_path / "sys"),
                    music_root=str(tmp_path / "music"))


def _media(rel, role, kind="video", dur=60.0, fps=(30000, 1001), size=(1920, 1080), ch=2):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=role, day_label="principal",
                     kind=kind, duration_s=dur, fps_num=fps[0] if kind == "video" else 0,
                     fps_den=fps[1] if kind == "video" else 1,
                     width=size[0] if kind == "video" else 0,
                     height=size[1] if kind == "video" else 0, rotation=0, audio_channels=ch)


@pytest.fixture
def env(tmp_path):
    s = _settings(tmp_path)
    db = ProjectDB(tmp_path / "p.db", s)
    ids = {}
    ids["A"] = db.add_media(_media("A\\C0001.MP4", Role.camera))
    ids["B"] = db.add_media(_media("B\\C0100.MP4", Role.camera))
    ids["D"] = db.add_media(_media("D\\DJI_0001.MP4", Role.drone))
    ids["C"] = db.add_media(_media("C\\C0042.MP4", Role.camera, fps=(25, 1)))
    ids["MESA"] = db.add_media(_media("MESA\\MESA.WAV", Role.mesa, kind="audio", dur=600, ch=1))
    for k, t0 in (("A", 100.0), ("B", 110.0), ("MESA", 0.0)):
        db.set_sync(SyncResult(media_id=ids[k], day_label="principal", timeline_start_s=t0,
                               confidence=9.0, method="audio"))
    db.set_audio_stats(AudioStats(media_id=ids["MESA"], mean_db=-9, peak_db=-1,
                                  noise_floor_db=-40, noisy=True))
    db.set_audio_stats(AudioStats(media_id=ids["C"], mean_db=-24, peak_db=-6,
                                  noise_floor_db=-60, noisy=False))
    idx = MusicIndex(tmp_path / "t.db", s)
    idx.upsert(TrackInfo(path=MUSIC, bpm=70, beats_s=[], downbeats_s=[], energy=[],
                         duration_s=200.0, has_vocals=False, perfil="calma", mtime=1.0))
    yield s, db, idx, ids
    db.close()
    idx.close()


def _ref(rel, a, b, fala=None, lembranca=False, desc="cena"):
    return SceneRef(rel_path=rel, start_s=a, end_s=b, descricao=desc, fala=fala, motivo=None,
                    lembranca=lembranca)


def _piece(tipo="episodio", numero=1, trilhas=None):
    music = [MusicSuggestion(origem="popular", path=None, titulo="Perfect", bpm=63, clima="x",
                             motivo="x", padrao_corte="1-3", exige_licenca=True),
             MusicSuggestion(origem="biblioteca", path=MUSIC, titulo="Piano", bpm=70, clima="x",
                             motivo="x", padrao_corte="1-3", exige_licenca=False)]
    return Piece(tipo=tipo, numero=numero, titulo="T", tema="t",
                 abertura=_ref("A\\C0001.MP4", 15, 25),
                 desenvolvimento=[_ref("C\\C0042.MP4", 2, 6, fala="Eu te escolho",
                                       lembranca=True, desc="votos")],
                 gancho=_ref("D\\DJI_0001.MP4", 0, 5) if tipo == "episodio" else None,
                 gancho_resolve_em=None, curva_emocao=[1, 2], duracao_estimada_s=19,
                 misturas=[], trilhas=music if trilhas is None else trilhas, termos_musicbed=[])


def _roteiro():
    stories = _piece("stories", None)
    return Roteiro(arco="a", pecas=[_piece(numero=2), _piece("teaser", None), _piece(numero=1),
                                    stories], alertas=[])


def _tracks(seq, kind):
    return seq.findall(f"./media/{kind}/track")


def _seq(db, idx, piece=None):
    return build_sequence(piece or _piece(), db, idx, {}, SRC)


# ------------------------------------------------------------------ utilitários

def test_pathurl_acentos():
    p = Path(r"R:\2023\VÍDEOS 2023\STYLLUS´S\C0001.MP4")
    u = pathurl(p)
    assert u.startswith("file://localhost/R%3a/2023/V%C3%8DDEOS%202023/")
    assert "\\" not in u and " " not in u
    back = unquote(u[len("file://localhost/"):]).replace("/", "\\")
    assert back == str(p)


@pytest.mark.parametrize("num,den,exp", [(30000, 1001, (30, True)), (60000, 1001, (60, True)),
                                         (24000, 1001, (24, True)), (25, 1, (25, False)),
                                         (2997, 100, (30, True)), (30, 1, (30, False))])
def test_timebase_ntsc(num, den, exp):
    assert timebase(num, den) == exp


def test_audio_tracks():
    assert AUDIO_TRACKS == ["MESA L", "MESA R", "AMBIENTE L", "AMBIENTE R", "LAPELA NOIVO L",
                           "LAPELA NOIVO R", "LAPELA NOIVA L", "LAPELA NOIVA R", "MÚSICA L",
                           "MÚSICA R"]


# ------------------------------------------------------------------ sequências

def test_sequencias_por_peca(env):
    s, db, idx, ids = env
    r = Roteiro(arco="a", pecas=[_piece(numero=2), _piece("teaser", None), _piece(numero=1)],
                alertas=[])
    root = ET.fromstring(build_xml(r, db, idx, {}, SRC))
    names = [e.findtext("name") for e in root.iter("sequence")]
    assert sorted(names) == ["EP01", "EP02", "TEASER"]
    bins = {b.findtext("name"): b for b in root.find("project/children").findall("bin")}
    assert set(bins) == {"EPISÓDIOS", "DERIVADOS", "MATERIAL", "TRILHAS"}
    assert [q.findtext("name") for q in bins["EPISÓDIOS"].iter("sequence")] == ["EP01", "EP02"]
    assert [q.findtext("name") for q in bins["DERIVADOS"].iter("sequence")] == ["TEASER"]
    sub = {b.findtext("name"): b for b in bins["MATERIAL"].find("children").findall("bin")}
    assert set(sub) == {"A", "B", "C", "D", "MESA"}
    assert len(sub["A"].find("children").findall("clip")) == 1
    assert [c.findtext("name") for c in bins["TRILHAS"].iter("clip")] == ["Piano.wav"]


def test_v1_em_ordem_e_frames(env):
    s, db, idx, ids = env
    seq = _seq(db, idx)
    assert seq.findtext("rate/timebase") == "30" and seq.findtext("rate/ntsc") == "TRUE"
    v1 = _tracks(seq, "video")[0].findall("clipitem")
    assert [c.find("file").get("id") for c in v1] == [f"file-{ids[k]}" for k in "ACD"]
    a, c, d = v1
    assert (a.findtext("start"), a.findtext("end")) == ("0", str(round(10 * NTSC)))
    # mesma taxa da sequência: out = in + (end − start)
    assert (a.findtext("in"), a.findtext("out")) == (str(round(15 * NTSC)),
                                                     str(round(15 * NTSC) + round(10 * NTSC)))
    assert c.findtext("start") == a.findtext("end")
    assert c.findtext("rate/timebase") == "25" and c.findtext("rate/ntsc") == "FALSE"
    assert (c.findtext("in"), c.findtext("out")) == ("50", "150")
    assert c.findtext("end") == str(round(10 * NTSC) + round(4 * NTSC))
    assert int(seq.findtext("duration")) == int(d.findtext("end"))
    assert seq.findtext("media/video/format/samplecharacteristics/width") == "1920"
    assert seq.findtext("media/video/format/samplecharacteristics/height") == "1080"


def test_angulos_alternativos_desativados(env):
    s, db, idx, ids = env
    seq = _seq(db, idx)
    vt = _tracks(seq, "video")
    assert len(vt) == 2
    alts = vt[1].findall("clipitem")
    assert len(alts) == 1
    b = alts[0]
    assert b.find("file").get("id") == f"file-{ids['B']}"
    assert b.findtext("enabled") == "FALSE"
    # cena A 15–25 s → linha do tempo 115–125; B começa em 110 → B 5–15 s
    assert (b.findtext("in"), b.findtext("out")) == (str(round(5 * NTSC)), str(round(15 * NTSC)))
    assert (b.findtext("start"), b.findtext("end")) == ("0", str(round(10 * NTSC)))
    used = {c.find("file").get("id") for t in vt for c in t.findall("clipitem")}
    assert used == {f"file-{ids[k]}" for k in "ABCD"}  # drone sem sync não vira ângulo


def test_angulo_parcial_alinhado(env):
    s, db, idx, ids = env
    p = _piece()
    p.abertura = _ref("A\\C0001.MP4", 2, 20)  # 102–120; B começa em 110
    seq = _seq(db, idx, p)
    b = _tracks(seq, "video")[1].findall("clipitem")[0]
    assert (b.findtext("start"), b.findtext("end")) == (str(round(8 * NTSC)), str(round(18 * NTSC)))
    assert (b.findtext("in"), b.findtext("out")) == ("0", str(round(18 * NTSC) - round(8 * NTSC)))


def _level(ci):
    for p in ci.iter("parameter"):
        if p.findtext("parameterid") == "level":
            return float(p.findtext("value"))
    raise AssertionError("sem Audio Levels")


def test_ganho_mesa_aplicado(env):
    s, db, idx, ids = env
    seq = _seq(db, idx)
    at = _tracks(seq, "audio")
    assert len(at) == len(AUDIO_TRACKS)
    mesa = at[AUDIO_TRACKS.index("MESA L")].findall("clipitem")
    assert len(mesa) == 1
    ci = mesa[0]
    assert ci.find("file").get("id") == f"file-{ids['MESA']}"
    assert _level(ci) == pytest.approx(10 ** (6 / 20), rel=1e-4)
    assert ci.findtext("sourcetrack/mediatype") == "audio"
    eff = ci.find("filter/effect")
    assert eff.findtext("effectid") == "audiolevels"
    # mesa começa em 0 na linha do tempo → cena 115–125 s
    assert (ci.findtext("in"), ci.findtext("out")) == (str(round(115 * NTSC)),
                                                       str(round(115 * NTSC) + round(10 * NTSC)))


def test_audio_da_camera_quando_sem_mesa(env):
    s, db, idx, ids = env
    seq = _seq(db, idx)
    amb = _tracks(seq, "audio")[AUDIO_TRACKS.index("AMBIENTE L")].findall("clipitem")
    files = [c.find("file").get("id") for c in amb]
    assert f"file-{ids['C']}" in files  # C sem sync: áudio da própria câmera
    c = amb[files.index(f"file-{ids['C']}")]
    assert _level(c) == pytest.approx(10 ** (6 / 20), rel=1e-4)  # câmera −24 → alvo −18
    d = amb[files.index(f"file-{ids['D']}")]
    assert _level(d) == pytest.approx(1.0)  # sem AudioStats → 0 dB
    assert f"file-{ids['A']}" not in files  # A tem mesa sobreposta


def test_ganho_limitado_a_12db(env):
    s, db, idx, ids = env
    db.set_audio_stats(AudioStats(media_id=ids["MESA"], mean_db=-40, peak_db=-20,
                                  noise_floor_db=-60, noisy=False))
    ci = _tracks(_seq(db, idx), "audio")[0].findall("clipitem")[0]
    assert _level(ci) == pytest.approx(3.98109)


def test_musica(env):
    s, db, idx, ids = env
    seq = build_sequence(_piece(), db, idx, {MUSIC: r"Y:\EVENTO\TRILHAS\Piano.wav"}, SRC)
    mus = _tracks(seq, "audio")[AUDIO_TRACKS.index("MÚSICA L")].findall("clipitem")
    assert len(mus) == 1
    m = mus[0]
    assert m.findtext("start") == "0" and m.findtext("end") == seq.findtext("duration")
    assert m.find("file").get("id") == "music-1"
    assert m.findtext("file/pathurl") == pathurl(Path(r"Y:\EVENTO\TRILHAS\Piano.wav"))
    sem = build_sequence(_piece(trilhas=[]), db, idx, {}, SRC)
    assert not _tracks(sem, "audio")[AUDIO_TRACKS.index("MÚSICA L")].findall("clipitem")


def _markers(seq):
    return [(m.findtext("name"), int(m.findtext("in")), int(m.findtext("out")))
            for m in seq.findall("marker")]


def test_marcadores_gancho_e_ruido(env):
    s, db, idx, ids = env
    seq = _seq(db, idx)
    mk = _markers(seq)
    names = [n for n, _, _ in mk]
    hook_start = round(10 * NTSC) + round(4 * NTSC)
    assert ("ABERTURA", 0, 0) in mk
    assert ("GANCHO", hook_start, hook_start) in mk
    assert "RUÍDO" in names
    assert "FALA: Eu te escolho" in names
    assert "LEMBRANÇA: votos" in names


def test_stories_vertical(env):
    s, db, idx, ids = env
    seq = _seq(db, idx, _piece("stories", None))
    assert seq.findtext("name") == "STORIES"
    sc = seq.find("media/video/format/samplecharacteristics")
    assert (sc.findtext("width"), sc.findtext("height")) == ("1080", "1920")


def test_xml_bem_formado(env, tmp_path):
    s, db, idx, ids = env
    xml = build_xml(_roteiro(), db, idx, {}, SRC)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    root = ET.fromstring(xml)
    assert root.tag == "xmeml" and root.get("version") == "4"
    # cada <file> é definido uma vez (com pathurl) e depois só referenciado
    defs = [f.get("id") for f in root.iter("file") if f.find("pathurl") is not None]
    assert len(defs) == len(set(defs))
    assert set(defs) == {f.get("id") for f in root.iter("file")}
    first = {}
    for f in root.iter("file"):
        first.setdefault(f.get("id"), f)
    assert all(f.find("pathurl") is not None for f in first.values())
    assert first[f"file-{ids['A']}"].findtext("pathurl") == pathurl(SRC / "A" / "C0001.MP4")
    ids_all = [e.get("id") for e in root.iter() if e.get("id") and e.tag != "file"]
    assert len(ids_all) == len(set(ids_all))
    assert build_xml(_roteiro(), db, idx, {}, SRC) == xml  # determinístico
    p = EventPaths(event_name="2026-05-10 CASAMENTO X", event_date=datetime.date(2026, 5, 10),
                   year=2026, source_dir=tmp_path, work_dir=tmp_path / "w",
                   proxies_dir=tmp_path / "w" / "P", analysis_dir=tmp_path / "w" / "ANALISE",
                   music_dir=tmp_path / "w" / "T", backup_dir=tmp_path / "w" / "B",
                   pdf_path=tmp_path / "w" / "r.pdf", db_path=tmp_path / "w" / "p.db",
                   premiere_dir=tmp_path / "pr", prproj_path=tmp_path / "pr" / "x.prproj",
                   export_dir=tmp_path / "ex")
    out = write_xml(xml, p, s)
    assert out == tmp_path / "w" / "ANALISE" / "2026-05-10 CASAMENTO X - PREMIERE.xml"
    assert out.read_text(encoding="utf-8") == xml


# ------------------------------------------------------------------ rodada de correções 1

def _first_full_then_refs(root, fid):
    els = [f for f in root.iter("file") if f.get("id") == fid]
    assert len(els) >= 2
    assert els[0].find("pathurl") is not None
    assert all(len(list(f)) == 0 for f in els[1:])


def test_file_definido_na_primeira_ocorrencia_do_documento(env):
    s, db, idx, ids = env
    p = _piece()
    p.desenvolvimento = [_ref("B\C0100.MP4", 0, 5)]  # B: ângulo na abertura, depois principal
    seq = _seq(db, idx, p)
    _first_full_then_refs(seq, f"file-{ids['B']}")
    r = Roteiro(arco="a", pecas=[p], alertas=[])
    root = ET.fromstring(build_xml(r, db, idx, {}, SRC))
    for fid in {f.get("id") for f in root.iter("file")}:
        els = [f for f in root.iter("file") if f.get("id") == fid]
        assert els[0].find("pathurl") is not None, fid
        assert all(len(list(f)) == 0 for f in els[1:]), fid


def _links(ci):
    return [(l.findtext("linkclipref"), l.findtext("mediatype"), int(l.findtext("trackindex")),
             int(l.findtext("clipindex"))) for l in ci.findall("link")]


def test_estereo_em_pares_ligados(env):
    s, db, idx, ids = env
    seq = _seq(db, idx)
    at = _tracks(seq, "audio")
    assert len(at) == 10
    assert seq.findtext("media/audio/numOutputChannels") == "2"
    li, ri = AUDIO_TRACKS.index("AMBIENTE L"), AUDIO_TRACKS.index("AMBIENTE R")
    left, right = at[li].findall("clipitem"), at[ri].findall("clipitem")
    assert len(left) == len(right) == 2  # câmera C e drone D, estéreo
    for k, (l, r) in enumerate(zip(left, right), start=1):
        assert l.findtext("sourcetrack/trackindex") == "1"
        assert r.findtext("sourcetrack/trackindex") == "2"
        assert l.find("file").get("id") == r.find("file").get("id")
        assert (l.findtext("start"), l.findtext("end")) == (r.findtext("start"), r.findtext("end"))
        exp = [(l.get("id"), "audio", li + 1, k), (r.get("id"), "audio", ri + 1, k)]
        assert _links(l) == exp and _links(r) == exp
    # mesa mono: só a faixa L
    assert len(at[AUDIO_TRACKS.index("MESA L")].findall("clipitem")) == 1
    assert not at[AUDIO_TRACKS.index("MESA R")].findall("clipitem")
    assert not at[AUDIO_TRACKS.index("MESA L")].find("clipitem").findall("link")
    # música estéreo
    assert len(at[AUDIO_TRACKS.index("MÚSICA R")].findall("clipitem")) == 1
    assert at[AUDIO_TRACKS.index("MÚSICA R")].findtext("clipitem/sourcetrack/trackindex") == "2"


def test_masterclipid_aponta_para_clip_do_bin(env):
    s, db, idx, ids = env
    root = ET.fromstring(build_xml(_roteiro(), db, idx, {}, SRC))
    masters = {c.get("id"): c for c in root.iter("clip")}
    assert all(c.findtext("ismasterclip") == "TRUE" for c in masters.values())
    n = 0
    for seq in root.iter("sequence"):
        for ci in seq.iter("clipitem"):
            mc = ci.findtext("masterclipid")
            assert mc in masters
            fid = ci.find("file").get("id")
            assert masters[mc].find(".//file").get("id") == fid
            n += 1
    assert n > 0
    assert masters[f"masterclip-file-{ids['A']}"].findtext("name") == "C0001.MP4"


def test_out_derivado_da_duracao_na_mesma_taxa(env):
    s, db, idx, ids = env
    a, d = 0.4 / NTSC, 10.4 / NTSC
    assert round((a + d) * NTSC) - round(a * NTSC) != round(d * NTSC)  # caso que desalinharia
    p = _piece()
    p.abertura = _ref("A\C0001.MP4", a, a + d)
    seq = _seq(db, idx, p)
    for t in _tracks(seq, "video") + _tracks(seq, "audio"):
        for ci in t.findall("clipitem"):
            if ci.findtext("rate/timebase") == "30":
                assert (int(ci.findtext("out")) - int(ci.findtext("in"))
                        == int(ci.findtext("end")) - int(ci.findtext("start")))


def test_rotacao_troca_largura_altura(env):
    s, db, idx, ids = env
    m = _media("E\VERT.MP4", Role.pocket)
    m.rotation = 90
    mid = db.add_media(m)
    p = _piece("stories", None)
    p.abertura = _ref("E\VERT.MP4", 0, 5)
    seq = _seq(db, idx, p)
    f = next(f for f in seq.iter("file") if f.get("id") == f"file-{mid}")
    sc = f.find("media/video/samplecharacteristics")
    assert (sc.findtext("width"), sc.findtext("height")) == ("1080", "1920")


# ------------------------------------------------------------------ revisão final: cena só-de-áudio


def _piece_mesa(a, b):
    p = _piece(trilhas=[])
    p.abertura = _ref("MESA\\MESA.WAV", a, b, desc="votos na mesa")
    p.desenvolvimento, p.gancho = [], None
    return p


def test_cena_so_audio_usa_video_sincronizado_em_v1(env):
    s, db, idx, ids = env
    seq = _seq(db, idx, _piece_mesa(105, 115))  # A cobre 100–160 (10 s), B 110–170 (5 s)
    v = _tracks(seq, "video")
    v1 = v[0].findall("clipitem")
    assert [c.findtext("name") for c in v1] == ["C0001.MP4"]
    fps = NTSC
    assert int(v1[0].findtext("in")) == round(5 * fps)  # 105 − 100
    assert int(v1[0].findtext("start")) == 0 and int(v1[0].findtext("end")) == round(10 * fps)
    alt = [c.findtext("name") for t in v[1:] for c in t.findall("clipitem")]
    assert alt == ["C0100.MP4"]
    mesa_l = _tracks(seq, "audio")[AUDIO_TRACKS.index("MESA L")].findall("clipitem")
    assert [c.findtext("name") for c in mesa_l] == ["MESA.WAV"]
    assert int(mesa_l[0].findtext("in")) == round(105 * fps)
    amb = _tracks(seq, "audio")[AUDIO_TRACKS.index("AMBIENTE L")].findall("clipitem")
    assert amb == []
    assert "SEM IMAGEM" not in [m.findtext("name") for m in seq.findall("marker")]


def test_cena_so_audio_sem_video_marca_sem_imagem(env):
    s, db, idx, ids = env
    seq = _seq(db, idx, _piece_mesa(10, 20))  # nenhuma câmera cobre 10–20 s
    assert _tracks(seq, "video")[0].findall("clipitem") == []
    nomes = [m.findtext("name") for m in seq.findall("marker")]
    assert "SEM IMAGEM" in nomes
    mesa_l = _tracks(seq, "audio")[AUDIO_TRACKS.index("MESA L")].findall("clipitem")
    assert [c.findtext("name") for c in mesa_l] == ["MESA.WAV"]
    assert int(seq.findtext("duration")) == round(10 * NTSC)
