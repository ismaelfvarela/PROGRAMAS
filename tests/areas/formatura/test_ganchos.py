"""Ganchos comuns usados pela Formatura: o Casamento fica idêntico."""
from __future__ import annotations

from pathlib import Path

from roteiro_ia.areas import area_por_id
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini import style
from roteiro_ia.gemini.analysis import (TEXTOS_CASAMENTO, TextosAnalise, build_pack_prompt,
                                        build_prompt)
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.script.generate import Roteiro, generate_roteiro

from ._amostra import amostra

SNAPSHOT = Path(__file__).parent / "dados" / "prompt_casamento.txt"


def test_prompt_casamento_identico_ao_de_antes():
    m, segs, sp = amostra()
    atual = build_prompt(m, segs, sp) + "\n=====\n" + build_pack_prompt([(m, segs, sp, (0.0, 20.0))])
    assert atual == SNAPSHOT.read_text(encoding="utf-8")
    assert build_prompt(m, segs, sp, textos=TEXTOS_CASAMENTO) == build_prompt(m, segs, sp)


def test_prompt_com_textos_proprios():
    m, segs, sp = amostra()
    t = TextosAnalise(papel="PAPEL X.", evento="da mesma formatura",
                      momentos=["oficina", "extra"], problemas="falhas Y")
    pr = build_prompt(m, segs, sp, textos=t)
    assert pr.startswith("PAPEL X.")
    assert "oficina, extra" in pr and "falhas Y" in pr and "casamento" not in pr
    pk = build_pack_prompt([(m, segs, sp, None)], textos=t)
    assert pk.startswith("PAPEL X.")
    assert "da mesma formatura" in pk and "casamento" not in pk


class _Cliente:
    def __init__(self):
        self.prompts = []

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.prompts.append(prompt)
        return Roteiro(arco="a", pecas=[], alertas=[])


def test_generate_usa_contexto_proprio(tmp_path):
    s = Settings(system_dir=str(tmp_path / "sys"), protected_roots=[])
    db, idx = ProjectDB(tmp_path / "p.db", s), MusicIndex(tmp_path / "t.db", s)
    vistos = []

    def ctx(db_, idx_, style_, n, der, compact=False):
        vistos.append((n, der, compact))
        return "CONTEXTO PROPRIO"
    c = _Cliente()
    try:
        generate_roteiro(db, c, idx, None, "m", 1, set(), contexto=ctx)
    finally:
        db.close()
        idx.close()
    assert c.prompts[0] == "CONTEXTO PROPRIO"
    assert vistos == [(1, set(), False)]


def _notas(url):
    return style.VideoStyleNotes(url=url, tipo="outro", duracao_s=1, ritmo_corte_s=1, abertura="",
                                 gancho="", uso_falas="", trilha="", cor="", observacoes="")


def test_area_registrada_tem_cache_proprio(tmp_path):
    s = Settings(system_dir=str(tmp_path / "sys"), protected_roots=[])
    style.registrar_area("teste", "PV", "PA")
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    p = Path(s.system_dir) / "estilo_cache" / "abcdefghijk.json"
    p.parent.mkdir(parents=True)
    p.write_text(_notas(url).model_dump_json(), encoding="utf-8")
    assert style.video_em_cache(s, url)
    assert not style.video_em_cache(s, url, area="teste")
    q = Path(s.system_dir) / "estilo_cache" / "teste" / "abcdefghijk.json"
    q.parent.mkdir(parents=True)
    q.write_text(_notas(url).model_dump_json(), encoding="utf-8")
    assert style.video_em_cache(s, url, area="teste")


class _ClienteEstilo:
    def __init__(self):
        self.prompts = []

    def pick_default_models(self):
        return ("m", "m")

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.prompts.append(prompt)
        if schema is style.VideoStyleNotes:
            return _notas("x")
        return style.StyleProfile(fontes=[], duracao_media_episodio_s=1, ritmo_corte_medio_s=1,
                                  padroes_abertura=[], padroes_gancho=[], uso_falas="", trilhas="",
                                  cor="", estrutura_teaser_trailer="", resumo="r")


def test_estudo_da_area_registrada_usa_prompts_dela(tmp_path):
    from roteiro_ia.config import set_urls_estilo
    s = Settings(system_dir=str(tmp_path / "sys"), protected_roots=[])
    style.registrar_area("teste2", "PROMPT VIDEO PROPRIO", "PROMPT AGG PROPRIO ")
    set_urls_estilo(s, "teste2", ["https://youtu.be/abcdefghijk"])
    c = _ClienteEstilo()
    style.build_style_profile(c, s, area="teste2")
    assert c.prompts[0] == "PROMPT VIDEO PROPRIO"
    assert c.prompts[1].startswith("PROMPT AGG PROPRIO ")
    assert style.video_em_cache(s, "https://youtu.be/abcdefghijk", area="teste2")


def test_area_pipeline_padrao():
    assert area_por_id("casamento").pipeline is None
