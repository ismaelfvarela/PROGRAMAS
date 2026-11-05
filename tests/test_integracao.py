"""Integração: evento sintético do inventário ao XML, com Gemini e Whisper falsos."""
import json
import os
import re

import pytest

from fixtures.make_media import make_audio, make_video
from roteiro_ia.config import Settings
from roteiro_ia.gemini.analysis import FileAnalysis
from roteiro_ia.media import proxies as px
from roteiro_ia.models import FolderAssignment, Role, SceneAnalysis, Word
from roteiro_ia.music_index import LibrosaTracker
from roteiro_ia.pipeline import STAGES, Pipeline, ProjectRequest
from roteiro_ia.report.pdf import find_edge
from roteiro_ia.script.generate import MusicSuggestion, Piece, Roteiro, SceneRef

pytestmark = pytest.mark.integracao

EVENTO = "2023-01-01 TESTE"


class FakeWhisper:
    def transcribe(self, path):
        return [Word(text="sim", start_s=0.5, end_s=1.0), Word(text="aceito", start_s=1.0, end_s=1.5)]


class FakeGemini:
    def __init__(self, track_path):
        self.track_path = track_path
        self.schemas = []

    def pick_default_models(self):
        return "fake-flash", "fake-pro"

    def upload(self, path):
        return f"file:{path}"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.schemas.append(schema.__name__)
        if schema is FileAnalysis:
            ids = [int(x) for x in re.findall(r"segment_id=(\d+)", prompt)]
            return FileAnalysis(segmentos=[SceneAnalysis(
                segment_id=i, momento="votos", descricao="noivos no altar", pessoas=["noiva"],
                emocao_intensidade=8, emocao_tipo="ternura", qualidade=7, problemas=[],
                melhores_trechos=[], falas_chave=[], potencial_gancho=True, motivo_gancho="olhar",
                sugestao_lembranca=False) for i in ids])
        if schema is Roteiro:
            def ref(rel, a, b):
                return SceneRef(rel_path=rel, start_s=a, end_s=b, descricao="cena", fala=None,
                                motivo=None)
            ms = MusicSuggestion(origem="biblioteca", path=self.track_path, titulo="trilha", bpm=None,
                                 clima="calmo", motivo="m", padrao_corte="1-3", exige_licenca=False)
            pc = Piece(tipo="episodio", numero=1, titulo="O sim", tema="votos",
                       abertura=ref("A\\C0001.MP4", 0, 2),
                       desenvolvimento=[ref("B\\C0001.MP4", 1, 3), ref("A\\C0002.MP4", 0, 2)],
                       gancho=None, gancho_resolve_em=None, curva_emocao=[4, 7, 9],
                       duracao_estimada_s=6, misturas=[], trilhas=[ms], termos_musicbed=["romantic"])
            return Roteiro(arco="um dia", pecas=[pc], alertas=[])
        raise AssertionError(f"schema inesperado: {schema}")


def _listing(root):
    out = []
    for dp, dns, fns in os.walk(root):
        for n in sorted(dns + fns):
            full = os.path.join(dp, n)
            st = os.stat(full)
            out.append((os.path.relpath(full, root), st.st_size, st.st_mtime_ns))
    return sorted(out)


def test_evento_completo(tmp_path, monkeypatch):
    try:
        find_edge()
    except RuntimeError:
        pytest.skip("Microsoft Edge não instalado")
    monkeypatch.setattr(px, "_FORCE_CPU", True)
    src = tmp_path / "R" / EVENTO
    make_video(src / "A" / "C0001.MP4", 6, size="320x180")
    make_video(src / "A" / "C0002.MP4", 6, size="320x180", tone_hz=660)
    make_video(src / "B" / "C0001.MP4", 6, size="320x180", tone_hz=550)
    make_audio(src / "E - H4" / "ZOOM0001.WAV", 8, noise_seed=3)
    track = make_audio(tmp_path / "M" / "trilha.wav", 10, noise_seed=7)
    s = Settings(protected_roots=[str(tmp_path / "R"), str(tmp_path / "M")],
                 music_root=str(tmp_path / "M"), work_drive=str(tmp_path / "Y"),
                 e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"),
                 system_dir=str(tmp_path / "SIS"), copy_music_to_work=True)
    before = _listing(src)
    req = ProjectRequest(source_dir=src, work_drive=str(tmp_path / "Y"),
                         assignments=[FolderAssignment(folder="A", role=Role.camera),
                                      FolderAssignment(folder="B", role=Role.camera),
                                      FolderAssignment(folder="E - H4", role=Role.audio_ambiente)],
                         n_episodios=1, derivados=set(), gemini_mode="gratis")
    events = []
    g = FakeGemini(os.path.abspath(track))
    with Pipeline(req, s, g, FakeWhisper(), lambda *e: events.append(e),
                  settings_path=tmp_path / "SIS" / "config.json",
                  music_tracker=LibrosaTracker()) as pipe:
        p, cost = pipe.prepare()
        assert cost == 0.0 and len(pipe.db.list_media()) == 4
        assert pipe.run() == "concluido"
        assert all(pipe.db.stage_status(n) == "feito" for n in STAGES)
        assert pipe.db.list_segments() and pipe.db.latest_roteiro()
    assert "FileAnalysis" in g.schemas and "Roteiro" in g.schemas
    assert p.pdf_path.read_bytes().startswith(b"%PDF")
    xml = p.analysis_dir / f"{EVENTO} - PREMIERE.xml"
    assert xml.is_file() and "C0001.MP4" in xml.read_text(encoding="utf-8")
    job = json.loads((p.analysis_dir / "job.json").read_text(encoding="utf-8"))
    assert job["xml"] == str(xml) and len(job["proxies"]) == 3
    assert (p.music_dir / "trilha.wav").is_file()
    assert _listing(src) == before  # nada criado nem alterado na origem
