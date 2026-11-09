from datetime import datetime

import pytest

from roteiro_ia.areas.formatura.colacao.frias import BancoFrias, ItemFria, banco_frias
from roteiro_ia.areas.formatura.colacao.partes import (ParteDetectada, RespostaPartes,
                                                       detectar_partes, nome_parte,
                                                       transcricao_em_linhas)
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini.analysis import analyze_event
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.models import MediaInfo, Role, SceneAnalysis, Segment

TURMAS = [("Eletrônica", "T106"), ("Eletrônica", "T107")]


class _C:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.prompts = resp, exc, []

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        return self.resp


def _p(codigo, ini, curso=None, turma=None):
    return ParteDetectada(codigo=codigo, curso=curso, turma=turma, inicio_s=ini)


def test_linhas_da_transcricao():
    txt = transcricao_em_linhas([(0.5, "boa"), (3, "noite"), (20, "convidamos"), (3700, "hino")])
    assert txt.splitlines() == ["[0:00:00] boa noite", "[0:00:20] convidamos", "[1:01:40] hino"]


def test_nomes():
    assert nome_parte("hino", None, None) == "Hino Nacional"
    assert nome_parte("colacao", "Eletrônica", "T106") == "Colação - Eletrônica - T106"


def test_detectar_ordena_valida_e_nomeia():
    c = _C(RespostaPartes(partes=[
        _p("hino", 300), _p("abertura", 0), _p("colacao", 900, "Eletrônica", "T106"),
        _p("xyz", 950), _p("colacao", 1200, "Eletrônica", "T107"), _p("encerramento", 99999)]))
    partes, alertas = detectar_partes(c, "m", "[0:00:00] boa noite", TURMAS, 3600)
    assert [(p.nome, p.inicio_s) for p in partes] == [
        ("Abertura do Mestre de Cerimônias e Entrada dos Professores", 0),
        ("Hino Nacional", 300), ("Colação - Eletrônica - T106", 900),
        ("Colação - Eletrônica - T107", 1200)]
    assert alertas == []
    assert "Eletrônica — T106" in c.prompts[0] and "[0:00:00] boa noite" in c.prompts[0]


def test_turma_que_faltou_vira_alerta():
    c = _C(RespostaPartes(partes=[_p("abertura", 0), _p("colacao", 900, "Eletrônica", "T106")]))
    _, alertas = detectar_partes(c, "m", "x", TURMAS, 3600)
    assert alertas == ["Não achei a colação da turma Eletrônica — T107 na transcrição; confira."]


def test_gemini_falhou_uma_parte_so():
    partes, alertas = detectar_partes(_C(exc=RuntimeError("rede")), "m", "x", TURMAS, 3600)
    assert [(p.nome, p.inicio_s) for p in partes] == [("Cerimônia Completa", 0.0)]
    assert alertas and "rede" in alertas[0]


def test_cota_pausa():
    with pytest.raises(QuotaPaused):
        detectar_partes(_C(exc=QuotaPaused(datetime.now(), daily=True)), "m", "x", TURMAS, 3600)


def test_pedido_do_editor_no_prompt():
    c = _C(RespostaPartes(partes=[_p("abertura", 0)]))
    detectar_partes(c, "m", "x", TURMAS, 3600, pedido="o hino começa em 0:12:30")
    assert "o hino começa em 0:12:30" in c.prompts[0]


def _banco():
    return BancoFrias([
        ItemFria(midia_rel="FRIAS\\a.mp4", inicio_s=0, fim_s=4, momento="decoração", qualidade=9),
        ItemFria(midia_rel="FRIAS\\b.mp4", inicio_s=0, fim_s=3, momento="plateia e família", qualidade=8),
        ItemFria(midia_rel="FRIAS\\c.mp4", inicio_s=5, fim_s=9, momento="plateia e família", qualidade=6),
    ])


def test_frias_por_assunto_sem_repetir():
    b = _banco()
    assert b.escolher("hino", 2) == [("FRIAS\\a.mp4", 0, 2)]
    assert b.escolher("colacao", 2) == [("FRIAS\\b.mp4", 0, 2)]
    assert b.escolher("colacao", 2) == [("FRIAS\\c.mp4", 5, 7)]


def test_frias_junta_trechos():
    b = _banco()
    out = b.escolher("colacao", 5)
    assert out == [("FRIAS\\b.mp4", 0, 3), ("FRIAS\\c.mp4", 5, 7)]
    assert BancoFrias([]).escolher("hino", 2) == []


def _mi(rel, role):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=role, day_label="principal",
                     kind="video", duration_s=10, fps_num=30, fps_den=1, width=320, height=180,
                     rotation=0, audio_channels=2)


def test_banco_vem_da_analise(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    db = ProjectDB(tmp_path / "p.db", s)
    a = db.add_media(_mi("FRIAS\\a.mp4", Role.drone))
    b = db.add_media(_mi("PGM\\p.mp4", Role.mesa))
    sa, sb = db.add_segments([Segment(media_id=a, start_s=0, end_s=5), Segment(media_id=b, start_s=0, end_s=5)])
    for sid in (sa, sb):
        db.set_analysis(SceneAnalysis(segment_id=sid, momento="decoração", descricao="d", pessoas=[],
                                      emocao_intensidade=3, emocao_tipo="", qualidade=7, problemas=[],
                                      melhores_trechos=[], falas_chave=[], potencial_gancho=False,
                                      sugestao_lembranca=False))
    banco = banco_frias(db, {"FRIAS\\a.mp4"})
    db.close()
    assert [(i.midia_rel, i.momento, i.qualidade) for i in banco.itens] == [("FRIAS\\a.mp4", "decoração", 7)]


class _CA:
    def __init__(self):
        self.prompts = []

    def upload(self, path):
        return "f"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        import re
        from roteiro_ia.gemini.analysis import FileAnalysis
        self.prompts.append(prompt)
        ids = [int(x) for x in re.findall(r"segment_id=(\d+)", prompt)]
        return FileAnalysis(segmentos=[SceneAnalysis(
            segment_id=i, momento="decoração", descricao="d", pessoas=[], emocao_intensidade=3,
            emocao_tipo="", qualidade=7, problemas=[], melhores_trechos=[], falas_chave=[],
            potencial_gancho=False, sugestao_lembranca=False) for i in ids])


def test_analyze_event_incluir(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    db = ProjectDB(tmp_path / "p.db", s)
    for rel, role in (("FRIAS\\a.mp4", Role.drone), ("PGM\\p.mp4", Role.mesa)):
        mid = db.add_media(_mi(rel, role))
        db.set_proxy(mid, str(tmp_path / "x.mp4"), "gerado")
        db.add_segments([Segment(media_id=mid, start_s=0, end_s=5)])
    c = _CA()
    analyze_event(db, c, None, "m", incluir=lambda m: m.rel_path.startswith("FRIAS"))
    db.close()
    assert len(c.prompts) == 1 and "FRIAS\\a.mp4" in c.prompts[0] and "PGM" not in c.prompts[0]
