import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from roteiro_ia.areas.formatura.colacao.entrega import nome_arquivo, write_job_integra
from roteiro_ia.areas.formatura.colacao.plano import ParteIntegra, PlanoIntegra, Troca
from roteiro_ia.areas.formatura.colacao.xml_integra import build_xml_integra
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import MediaInfo, Role, SyncResult
from roteiro_ia.paths import build_event_paths

PANEL = Path(__file__).resolve().parents[4] / "premiere_panel"


def _mi(rel, role, dur, kind="video"):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=role, day_label="principal",
                     kind=kind, duration_s=dur, fps_num=30000, fps_den=1001, width=1920,
                     height=1080, rotation=0, audio_channels=2)


@pytest.fixture
def db(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    d = ProjectDB(tmp_path / "p.db", s)
    for rel, role, dur, t0 in (("PGM\\p1.mp4", Role.mesa, 100, 0), ("PGM\\p2.mp4", Role.mesa, 100, 100),
                               ("CAM A\\a.mp4", Role.camera, 200, 0), ("CAM B\\b.mp4", Role.camera, 200, 0),
                               ("H4\\z.wav", Role.audio_ambiente, 200, 0),
                               ("FRIAS\\f.mp4", Role.drone, 30, None)):
        mid = d.add_media(_mi(rel, role, dur, "audio" if rel.endswith(".wav") else "video"))
        if t0 is not None:
            d.set_sync(SyncResult(media_id=mid, day_label="principal", timeline_start_s=t0,
                                  confidence=9, method="audio"))
    yield d
    d.close()


PLANO = PlanoIntegra(partes=[
    ParteIntegra(numero=1, codigo="abertura", nome="Abertura do Mestre", inicio_s=0, fim_s=90,
                 trechos=[(0, 40.5), (49.5, 90)], cortes=[(40.5, 49.5)],
                 trocas=[Troca(inicio_s=10, fim_s=12, motivo="chicote", fonte="iso:CAM B\\b.mp4"),
                         Troca(inicio_s=20, fim_s=22, motivo="escuro", fonte="fria:FRIAS\\f.mp4@0.000-2.000"),
                         Troca(inicio_s=30, fim_s=31, motivo="desfocado", fonte="sem")]),
    ParteIntegra(numero=2, codigo="hino", nome="Hino Nacional", inicio_s=90, fim_s=150,
                 trechos=[(90, 150)], cortes=[], trocas=[]),
])


def _seqs(xml):
    root = ET.fromstring(xml.split("\n", 2)[2])
    return {s.findtext("name"): s for s in root.iter("sequence")}


def _v1(seq):
    t = seq.find("media/video/track")
    return [(c.findtext("name"), int(c.findtext("start")), int(c.findtext("end")))
            for c in t.findall("clipitem")]


def test_sequencias_com_nomes_de_entrega(db, tmp_path):
    seqs = _seqs(build_xml_integra(PLANO, db, tmp_path))
    assert list(seqs) == ["01 - Abertura do Mestre", "02 - Hino Nacional"]


def test_v1_com_trocas_e_pgm(db, tmp_path):
    seq = _seqs(build_xml_integra(PLANO, db, tmp_path))["01 - Abertura do Mestre"]
    nomes = [n for n, *_ in _v1(seq)]
    assert nomes[:3] == ["p1.mp4", "b.mp4", "p1.mp4"]
    assert "f.mp4" in nomes
    dur = int(seq.findtext("duration"))
    assert abs(dur - round(81 * 30000 / 1001)) <= 2  # 90 s menos o corte de 9 s


def test_parte_atravessa_dois_arquivos_pgm(db, tmp_path):
    seq = _seqs(build_xml_integra(PLANO, db, tmp_path))["02 - Hino Nacional"]
    assert [n for n, *_ in _v1(seq)] == ["p1.mp4", "p2.mp4"]
    mesa_l = [c.findtext("name") for c in seq.find("media/audio").findall("track")[0].findall("clipitem")]
    assert mesa_l == ["p1.mp4", "p2.mp4"]


def test_marcadores(db, tmp_path):
    seq = _seqs(build_xml_integra(PLANO, db, tmp_path))["01 - Abertura do Mestre"]
    nomes = [m.findtext("name") for m in seq.findall("marker")]
    assert "TROCA: chicote → CAM B" in nomes
    assert "IMAGEM FRIA: escuro" in nomes
    assert "SEM COBERTURA: desfocado" in nomes
    assert "CORTE: 9 s sem fala" in nomes


def test_gravador_como_reserva_desligada(db, tmp_path):
    seq = _seqs(build_xml_integra(PLANO, db, tmp_path))["02 - Hino Nacional"]
    amb = [c for t in seq.find("media/audio").findall("track") for c in t.findall("clipitem")
           if c.findtext("name") == "z.wav"]
    assert amb and all(c.findtext("enabled") == "FALSE" for c in amb)


def test_job_com_entregas(tmp_path, db):
    s = Settings(protected_roots=[str(tmp_path / "R")], work_drive=str(tmp_path / "Y"),
                 e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"), system_dir=str(tmp_path / "S"))
    src = tmp_path / "R" / "2026-12-10 COLACAO ESCOLA X"
    src.mkdir(parents=True)
    p = build_event_paths(src, s, s.work_drive)
    Path(p.analysis_dir).mkdir(parents=True)
    xml = Path(p.analysis_dir) / "x.xml"
    xml.write_text("<x/>", encoding="utf-8")
    out = write_job_integra(p, s, xml, db, PLANO)
    job = json.loads(out.read_text(encoding="utf-8"))
    assert [e["sequencia"] for e in job["entregas"]] == ["01 - Abertura do Mestre", "02 - Hino Nacional"]
    assert job["entregas"][1]["arquivo"] == str(Path(p.export_dir) / "02 - Hino Nacional.mp4")
    assert json.loads((Path(s.system_dir) / "ultimo_job.json").read_text(encoding="utf-8"))["entregas"]
    assert nome_arquivo('Colação - Eletrônica: T1/2?') == "Colação - Eletrônica T1 2"


def test_painel_exporta_entregas():
    jsx = (PANEL / "host" / "montar.jsx").read_text(encoding="ascii")
    assert "function exportarEntregas" in jsx
    for termo in ("encodeSequence", "startBatch", "preset_exportacao", "openDialog"):
        assert termo in jsx
    assert 'id="btnExportar"' in (PANEL / "index.html").read_text(encoding="utf-8")
    js = (PANEL / "main.js").read_text(encoding="utf-8")
    assert "exportarEntregas(" in js and "btnExportar" in js


def test_corte_no_comeco_da_parte_tem_marcador(db, tmp_path):
    plano = PlanoIntegra(partes=[ParteIntegra(
        numero=1, codigo="hino", nome="Hino Nacional", inicio_s=90, fim_s=150,
        trechos=[(96, 150)], cortes=[(90, 96)], trocas=[])])
    seq = _seqs(build_xml_integra(plano, db, tmp_path))["01 - Hino Nacional"]
    mk = [(m.findtext("name"), m.findtext("in")) for m in seq.findall("marker")]
    assert mk == [("CORTE: 6 s sem fala", "0")]


def _peca(tipo, rel="PGM\p1.mp4"):
    from roteiro_ia.script.generate import Piece, SceneRef
    ref = SceneRef(rel_path=rel, start_s=1, end_s=4, descricao="d", fala=None, motivo=None)
    return Piece(tipo=tipo, numero=None, titulo=tipo, tema="t", abertura=ref, desenvolvimento=[],
                 gancho=None, gancho_resolve_em=None, curva_emocao=[5], duracao_estimada_s=3,
                 misturas=[], trilhas=[], termos_musicbed=[])


class _Idx:
    def get(self, path):
        return None


def test_clipes_antes_e_depois_das_partes_com_logo(db, tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png")
    xml = build_xml_integra(PLANO, db, tmp_path, abertura=_peca("trailer"),
                            encerramento=_peca("teaser"), idx=_Idx(), musicas={}, logo=str(logo))
    seqs = _seqs(xml)
    assert list(seqs) == ["00 - Abertura", "01 - Abertura do Mestre", "02 - Hino Nacional",
                          "03 - Encerramento"]
    enc = seqs["03 - Encerramento"]
    v1 = _v1(enc)
    assert v1[-1][0] == "logo.png" and v1[-1][1] == v1[-2][2]
    assert int(enc.findtext("duration")) == v1[-1][2]
    assert "LOGO DA PRODUTORA" in [m.findtext("name") for m in enc.findall("marker")]
    assert "logo.png" in xml.split("<bin>")[-1] or "GRAFISMOS" in xml


def test_encerramento_sem_logo_marca(db, tmp_path):
    xml = build_xml_integra(PLANO, db, tmp_path, encerramento=_peca("teaser"), idx=_Idx(),
                            musicas={}, logo=str(tmp_path / "sumiu.png"))
    enc = _seqs(xml)["03 - Encerramento"]
    assert [n for n, *_ in _v1(enc)] == ["p1.mp4"]
    assert "LOGO DA PRODUTORA: escolha o arquivo em Formaturas…" in [
        m.findtext("name") for m in enc.findall("marker")]


def test_entregas_com_clipes(tmp_path, db):
    s = Settings(protected_roots=[str(tmp_path / "R")], work_drive=str(tmp_path / "Y"),
                 e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"), system_dir=str(tmp_path / "S"))
    src = tmp_path / "R" / "2026-12-10 COLACAO ESCOLA X"
    src.mkdir(parents=True)
    p = build_event_paths(src, s, s.work_drive)
    Path(p.analysis_dir).mkdir(parents=True)
    xml = Path(p.analysis_dir) / "x.xml"
    xml.write_text("<x/>", encoding="utf-8")
    out = write_job_integra(p, s, xml, db, PLANO, clipes=("00 - Abertura", "03 - Encerramento"))
    job = json.loads(out.read_text(encoding="utf-8"))
    assert [e["sequencia"] for e in job["entregas"]] == [
        "00 - Abertura", "01 - Abertura do Mestre", "02 - Hino Nacional", "03 - Encerramento"]
