"""Integração: oficina de dois dias do inventário ao XML, com Gemini e Whisper falsos."""
import os
import re

import pytest

from fixtures.make_media import make_audio, make_video
from roteiro_ia.areas.formatura.cadastro import Curso, Formatura, salvar
from roteiro_ia.areas.formatura.pipeline import PipelineFormatura
from roteiro_ia.areas.formatura.projeto import ProjetoFormatura, RequestFormatura, carregar_projeto
from roteiro_ia.config import Settings
from roteiro_ia.gemini.analysis import FileAnalysis
from roteiro_ia.media import proxies as px
from roteiro_ia.models import FolderAssignment, Role, SceneAnalysis, Word
from roteiro_ia.music_index import LibrosaTracker
from roteiro_ia.pipeline import STAGES
from roteiro_ia.report.pdf import find_edge
from roteiro_ia.script.generate import MusicSuggestion, Piece, Roteiro, SceneRef

pytestmark = pytest.mark.integracao
EVENTO = "2026-03-10 OFICINA ESCOLA X T106"
CAM1 = "2026-03-10\\CAM A\\C0001.MP4"
CAM2 = "2026-03-12\\CAM A\\C0001.MP4"


class FakeWhisper:
    def transcribe(self, path):
        return [Word(text="eu", start_s=0.5, end_s=1.0), Word(text="soldei", start_s=1.0, end_s=1.5)]


class FakeGemini:
    def __init__(self, track):
        self.track = track
        self.prompts = []

    def pick_default_models(self):
        return "fake-flash", "fake-pro"

    def upload(self, path):
        return f"file:{path}"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.prompts.append((schema.__name__, prompt))
        if schema is FileAnalysis:
            ids = [int(x) for x in re.findall(r"segment_id=(\d+)", prompt)]
            return FileAnalysis(segmentos=[SceneAnalysis(
                segment_id=i, momento="alunos trabalhando", descricao="solda na bancada",
                pessoas=["aluno"], emocao_intensidade=6, emocao_tipo="foco", qualidade=8,
                problemas=[], melhores_trechos=[], falas_chave=[], potencial_gancho=False,
                sugestao_lembranca=False) for i in ids])
        if schema is Roteiro:
            def ref(rel, a, b):
                return SceneRef(rel_path=rel, start_s=a, end_s=b, descricao="cena", fala=None, motivo=None)
            ms = MusicSuggestion(origem="biblioteca", path=self.track, titulo="pop", bpm=None,
                                 clima="alegre", motivo="m", padrao_corte="2-4", exige_licenca=False)
            pc = Piece(tipo="episodio", numero=1, titulo="Oficina — Eletrônica T106", tema="oficina",
                       abertura=ref(CAM1, 0, 2), desenvolvimento=[ref(CAM2, 1, 3)], gancho=None,
                       gancho_resolve_em=None, curva_emocao=[5, 8], duracao_estimada_s=5,
                       misturas=[], trilhas=[ms], termos_musicbed=[])
            return Roteiro(arco="a oficina", pecas=[pc], alertas=[])
        raise AssertionError(f"schema inesperado: {schema}")


def test_oficina_completa(tmp_path, monkeypatch):
    try:
        find_edge()
    except RuntimeError:
        pytest.skip("Microsoft Edge não instalado")
    monkeypatch.setattr(px, "_FORCE_CPU", True)
    src = tmp_path / "R" / EVENTO
    make_video(src / "2026-03-10" / "CAM A" / "C0001.MP4", 6, size="320x180")
    make_audio(src / "2026-03-10" / "H4" / "ZOOM0001.WAV", 8, noise_seed=3)
    make_video(src / "2026-03-12" / "CAM A" / "C0001.MP4", 6, size="320x180", tone_hz=660)
    track = os.path.abspath(make_audio(tmp_path / "M" / "pop.wav", 10, noise_seed=7))
    s = Settings(protected_roots=[str(tmp_path / "R"), str(tmp_path / "M")],
                 music_root=str(tmp_path / "M"), work_drive=str(tmp_path / "Y"),
                 e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"),
                 system_dir=str(tmp_path / "SIS"))
    ficha = salvar(s, Formatura(instituicao="Escola X", ano=2026, semestre=2,
                                cursos=[Curso(nome="Eletrônica", turmas=["T106"])]))
    pf = ProjetoFormatura(tipo="oficina", formatura_id=ficha.id, curso="Eletrônica", turma="T106",
                          duracao_min=4)
    req = RequestFormatura(
        source_dir=src, work_drive=str(tmp_path / "Y"),
        assignments=[FolderAssignment(folder="2026-03-10\\CAM A", role=Role.camera, day_label="2026-03-10"),
                     FolderAssignment(folder="2026-03-10\\H4", role=Role.audio_ambiente, day_label="2026-03-10"),
                     FolderAssignment(folder="2026-03-12\\CAM A", role=Role.camera, day_label="2026-03-12")],
        n_episodios=1, derivados=set(), gemini_mode="gratis", area="formatura", formatura=pf)
    g = FakeGemini(track)
    with PipelineFormatura(req, s, g, FakeWhisper(), None,
                           settings_path=tmp_path / "SIS" / "config.json",
                           music_tracker=LibrosaTracker()) as pipe:
        p, _ = pipe.prepare()
        assert len(pipe.db.list_media()) == 3
        assert pipe.run() == "concluido"
        assert all(pipe.db.stage_status(n) == "feito" for n in STAGES)
    analise = [pr for nome, pr in g.prompts if nome == "FileAnalysis"]
    roteiro = [pr for nome, pr in g.prompts if nome == "Roteiro"]
    assert analise and all("formatura" in pr and "casamento" not in pr for pr in analise)
    assert roteiro and "Escola X" in roteiro[0] and "T106" in roteiro[0] and "240 s" in roteiro[0]
    assert p.pdf_path.read_bytes().startswith(b"%PDF")
    xml = p.analysis_dir / f"{EVENTO} - PREMIERE.xml"
    assert xml.is_file() and "C0001.MP4" in xml.read_text(encoding="utf-8")
    assert carregar_projeto(p.analysis_dir).musica == track
