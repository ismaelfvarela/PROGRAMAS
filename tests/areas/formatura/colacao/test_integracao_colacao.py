"""Integração: colação sintética (mesa de corte, ISO e imagens frias) até o XML e o job."""
import json
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest

from roteiro_ia.areas.formatura.cadastro import Curso, Formatura, salvar
from roteiro_ia.areas.formatura.colacao.partes import ParteDetectada, RespostaPartes
from roteiro_ia.areas.formatura.pipeline import PipelineFormatura
from roteiro_ia.areas.formatura.projeto import ProjetoFormatura, RequestFormatura
from roteiro_ia.config import Settings
from roteiro_ia.gemini.analysis import FileAnalysis
from roteiro_ia.media import proxies as px
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.models import FolderAssignment, Role, SceneAnalysis, Word
from roteiro_ia.pipeline import STAGES
from roteiro_ia.report.pdf import find_edge
from roteiro_ia.script.generate import Piece, Roteiro, SceneRef
from roteiro_ia.areas.formatura.ajustes import AjustesFormatura, salvar_ajustes

pytestmark = pytest.mark.integracao
EVENTO = "2026-12-10 COLACAO ESCOLA X"
PGM = "PGM" + chr(92) + "p.mp4"
FRIAS = "FRIAS" + chr(92) + "f.mp4"


def _ff(*args):
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", *args], check=True)


def _audio(path):
    """Ruído 3 s, silêncio 6 s, ruído 3 s (o mesmo na mesa e na ISO, para sincronizar)."""
    _ff("-f", "lavfi", "-i", "anoisesrc=d=3:c=pink:a=0.4:seed=11",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=6",
        "-f", "lavfi", "-i", "anoisesrc=d=3:c=pink:a=0.4:seed=12",
        "-filter_complex", "[0]aformat=sample_rates=48000:channel_layouts=mono[a];"
        "[2]aformat=sample_rates=48000:channel_layouts=mono[c];[a][1][c]concat=n=3:v=0:a=1[o]",
        "-map", "[o]", str(path))


class FakeWhisper:
    def transcribe(self, path):
        return [Word(text="boa", start_s=0.5, end_s=1.0), Word(text="noite", start_s=1.0, end_s=1.5)]


class FakeGemini:
    def __init__(self):
        self.schemas = []

    def pick_default_models(self):
        return "flash", "pro"

    def upload(self, path):
        return f"file:{path}"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.schemas.append(schema.__name__)
        if schema is FileAnalysis:
            ids = [int(x) for x in re.findall(r"segment_id=(\d+)", prompt)]
            return FileAnalysis(segmentos=[SceneAnalysis(
                segment_id=i, momento="decoração", descricao="palco", pessoas=[],
                emocao_intensidade=3, emocao_tipo="", qualidade=8, problemas=[],
                melhores_trechos=[], falas_chave=[], potencial_gancho=False,
                sugestao_lembranca=False) for i in ids])
        if schema is RespostaPartes:
            return RespostaPartes(partes=[ParteDetectada(codigo="abertura", inicio_s=0),
                                          ParteDetectada(codigo="hino", inicio_s=6)])
        if schema is Roteiro:
            def ref(rel, a, b):
                return SceneRef(rel_path=rel, start_s=a, end_s=b, descricao="cena", fala=None, motivo=None)

            def peca(tipo):
                return Piece(tipo=tipo, numero=None, titulo=tipo, tema="t", abertura=ref(FRIAS, 0, 2),
                             desenvolvimento=[ref(PGM, 1, 3)], gancho=None, gancho_resolve_em=None,
                             curva_emocao=[6, 9], duracao_estimada_s=4, misturas=[], trilhas=[],
                             termos_musicbed=[])
            return Roteiro(arco="festa", pecas=[peca("trailer"), peca("teaser")], alertas=[])
        raise AssertionError(schema)


def test_colacao_completa(tmp_path, monkeypatch):
    try:
        find_edge()
    except RuntimeError:
        pytest.skip("Microsoft Edge não instalado")
    monkeypatch.setattr(px, "_FORCE_CPU", True)
    src = tmp_path / "R" / EVENTO
    aud = tmp_path / "aud.wav"
    _audio(aud)
    _ff("-filter_complex", "testsrc2=size=320x180:rate=30:duration=9[a];"
        "color=black:size=320x180:rate=30:duration=2[b];testsrc2=size=320x180:rate=30:duration=1[c];"
        "[a][b][c]concat=n=3:v=1[v]", "-i", str(aud), "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str((src / "PGM").mkdir(parents=True) or src / "PGM" / "p.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=12", "-i", str(aud),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str((src / "CAM A").mkdir(parents=True) or src / "CAM A" / "a.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=6",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str((src / "FRIAS").mkdir(parents=True) or src / "FRIAS" / "f.mp4"))
    s = Settings(protected_roots=[str(tmp_path / "R"), str(tmp_path / "M")],
                 music_root=str(tmp_path / "M"), work_drive=str(tmp_path / "Y"),
                 e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"),
                 system_dir=str(tmp_path / "SIS"))
    (tmp_path / "M").mkdir()
    ficha = salvar(s, Formatura(instituicao="Escola X", ano=2026, semestre=2,
                                cursos=[Curso(nome="Eletrônica", turmas=["T106"])]))
    pf = ProjetoFormatura(tipo="colacao", formatura_id=ficha.id, turmas_colacao=[("Eletrônica", "T106")],
                          funcoes={"PGM": "mesa_corte", "CAM A": "camera_iso", "FRIAS": "extras"})
    req = RequestFormatura(
        source_dir=src, work_drive=str(tmp_path / "Y"),
        assignments=[FolderAssignment(folder="PGM", role=Role.mesa),
                     FolderAssignment(folder="CAM A", role=Role.camera),
                     FolderAssignment(folder="FRIAS", role=Role.drone)],
        n_episodios=1, derivados=set(), gemini_mode="gratis", area="formatura", formatura=pf)
    logo = tmp_path / "logo.png"
    _ff("-f", "lavfi", "-i", "color=white:size=64x64:d=1", "-frames:v", "1", str(logo))
    salvar_ajustes(s, AjustesFormatura(logo_produtora=str(logo)))
    g = FakeGemini()
    with PipelineFormatura(req, s, g, FakeWhisper(), None,
                           settings_path=tmp_path / "SIS" / "config.json") as pipe:
        p, _ = pipe.prepare()
        assert pipe.run() == "concluido"
        assert all(pipe.db.stage_status(n) == "feito" for n in STAGES)
    assert g.schemas.count("RespostaPartes") == 1 and "FileAnalysis" in g.schemas
    plano = json.loads((p.analysis_dir / "integra.json").read_text(encoding="utf-8"))
    assert [x["nome"] for x in plano["partes"]] == [
        "Abertura do Mestre de Cerimônias e Entrada dos Professores", "Hino Nacional"]
    hino = plano["partes"][1]
    assert hino["cortes"] and any(t["fonte"].startswith("iso:") and t["motivo"] == "escuro"
                                  for t in hino["trocas"]), hino
    xml = (p.analysis_dir / f"{EVENTO} - PREMIERE.xml").read_text(encoding="utf-8")
    root = ET.fromstring(xml.split("\n", 2)[2])
    seqs = {sq.findtext("name"): sq for sq in root.iter("sequence")}
    assert list(seqs) == ["00 - Abertura",
                          "01 - Abertura do Mestre de Cerimônias e Entrada dos Professores",
                          "02 - Hino Nacional", "03 - Encerramento"]
    v1 = [c.findtext("name") for c in seqs["03 - Encerramento"].find("media/video/track").findall("clipitem")]
    assert v1[-1] == "logo.png" and g.schemas.count("Roteiro") == 1
    nomes = [m.findtext("name") for m in seqs["02 - Hino Nacional"].findall("marker")]
    assert "TROCA: escuro → CAM A" in nomes and any(n.startswith("CORTE:") for n in nomes)
    job = json.loads((p.analysis_dir / "job.json").read_text(encoding="utf-8"))
    assert [e["sequencia"][:2] for e in job["entregas"]] == ["00", "01", "02", "03"]
    assert job["entregas"][2]["arquivo"].endswith("02 - Hino Nacional.mp4")
    assert p.pdf_path.read_bytes().startswith(b"%PDF")
