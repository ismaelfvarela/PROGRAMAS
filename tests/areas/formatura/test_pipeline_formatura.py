from pathlib import Path

import pytest

from roteiro_ia.areas.formatura import pipeline as pf_pipeline
from roteiro_ia.areas.formatura.analise import TEXTOS_POR_TIPO
from roteiro_ia.areas.formatura.cadastro import Curso, Formatura, salvar
from roteiro_ia.areas.formatura.pipeline import PipelineFormatura
from roteiro_ia.areas.formatura.projeto import (ProjetoFormatura, RequestFormatura,
                                                carregar_projeto, salvar_projeto)
from roteiro_ia.config import Settings
from roteiro_ia.models import FolderAssignment, Role, TrackInfo
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.pipeline import STAGES, PipelineError
from roteiro_ia.script.generate import MusicSuggestion, Piece, Roteiro, SceneRef


def _s(tmp_path):
    return Settings(protected_roots=[str(tmp_path / "R")], music_root=str(tmp_path / "M"),
                    work_drive=str(tmp_path / "Y"), e_root=str(tmp_path / "E"),
                    g_root=str(tmp_path / "G"), system_dir=str(tmp_path / "SIS"),
                    gemini_model_analysis="flash", gemini_model_script="pro")


class _Gemini:
    def pick_default_models(self):
        return "flash", "pro"


def _pipe(tmp_path, tipo="oficina", nome="2026-03-10 OFICINA ESCOLA X T106", **kw):
    s = _s(tmp_path)
    ficha = salvar(s, Formatura(instituicao="Escola X", ano=2026, semestre=2,
                                cursos=[Curso(nome="Eletrônica", turmas=["T106", "T107"])]))
    src = tmp_path / "R" / nome
    (src / "CAM A").mkdir(parents=True, exist_ok=True)
    pf = ProjetoFormatura(tipo=tipo, formatura_id=ficha.id, curso="Eletrônica", turma="T106", **kw)
    req = RequestFormatura(source_dir=src, work_drive=str(tmp_path / "Y"),
                           assignments=[FolderAssignment(folder="CAM A", role=Role.camera)],
                           n_episodios=1, derivados=set(), gemini_mode="gratis",
                           area="formatura", formatura=pf)
    pipe = PipelineFormatura(req, s, _Gemini(), None, None,
                             settings_path=tmp_path / "SIS" / "config.json")
    return pipe, s, pf


def _sem_etapas(pipe):
    calls = []
    for n in STAGES:
        pipe.impl[n] = (lambda n=n: calls.append(n))
    return calls


def test_run_grava_formatura_json(tmp_path):
    pipe, _s_, pf = _pipe(tmp_path)
    calls = _sem_etapas(pipe)
    try:
        assert pipe.run() == "concluido"
    finally:
        pipe.close()
    assert calls == STAGES
    assert carregar_projeto(Path(pipe.p.analysis_dir)) == pf
    assert (Path(pipe.p.analysis_dir) / "projeto.json").is_file()


def test_colacao_sem_pgm_recusada(tmp_path):
    pipe, _, _ = _pipe(tmp_path, tipo="colacao", nome="2026-12-10 COLACAO ESCOLA X",
                       funcoes={"CAM A": "camera_iso"})
    calls = _sem_etapas(pipe)
    with pytest.raises(PipelineError, match=r"Marque a pasta da mesa de corte"):
        pipe.run()
    pipe.close()
    assert calls == []


def test_sem_dados_le_o_arquivo_ou_recusa(tmp_path):
    pipe, s, pf = _pipe(tmp_path)
    ad = Path(pipe.p.analysis_dir)
    ad.mkdir(parents=True, exist_ok=True)
    salvar_projeto(ad, pf, s)
    pipe.req.formatura = None
    assert pipe.projeto() == pf
    (ad / "formatura.json").unlink()
    with pytest.raises(PipelineError, match="formatura.json"):
        pipe.projeto()
    pipe.close()


def test_analise_usa_textos_do_tipo(tmp_path, monkeypatch):
    pipe, _, _ = _pipe(tmp_path)
    visto = {}
    monkeypatch.setattr(pf_pipeline, "analyze_event", lambda *a, **k: visto.update(k))
    pipe._st_analise()
    pipe.close()
    assert visto["textos"] is TEXTOS_POR_TIPO["oficina"]


def _roteiro(path):
    ref = SceneRef(rel_path="CAM A\\C1.MP4", start_s=0, end_s=5, descricao="d", fala=None, motivo=None)
    ms = MusicSuggestion(origem="biblioteca", path=path, titulo="a", bpm=120, clima="alegre",
                         motivo="m", padrao_corte="2-4", exige_licenca=False)
    return Roteiro(arco="a", alertas=[], pecas=[Piece(
        tipo="episodio", numero=1, titulo="Oficina", tema="t", abertura=ref, desenvolvimento=[],
        gancho=None, gancho_resolve_em=None, curva_emocao=[5], duracao_estimada_s=240,
        misturas=[], trilhas=[ms], termos_musicbed=[])])


def _indice(tmp_path, s, *paths):
    idx = MusicIndex(Path(s.system_dir) / "trilhas.db", s)
    for p in paths:
        idx.upsert(TrackInfo(path=p, bpm=120, beats_s=[], downbeats_s=[], energy=[],
                             duration_s=200, has_vocals=True, perfil="intensa", mtime=1.0))
    return idx


def test_roteiro_usa_contexto_e_grava_musica(tmp_path, monkeypatch):
    pipe, s, _ = _pipe(tmp_path)
    m = str(tmp_path / "M" / "a.mp3")
    pipe._idx = _indice(tmp_path, s, m)
    visto = {}

    def gen(db, c, idx, style, model, n, der, pedido_ajuste=None, contexto=None):
        visto.update(n=n, der=der, contexto=contexto, trilhas=[t.path for t in idx.all()])
        return _roteiro(m)
    monkeypatch.setattr(pf_pipeline, "generate_roteiro", gen)
    pipe._st_roteiro()
    ad = Path(pipe.p.analysis_dir)
    pipe.close()
    assert visto["n"] == 1 and visto["der"] == set() and callable(visto["contexto"])
    assert visto["trilhas"] == [m]
    assert carregar_projeto(ad).musica == m


def test_roteiro_exclui_musicas_ja_usadas(tmp_path, monkeypatch):
    pipe, s, _ = _pipe(tmp_path)
    m = str(tmp_path / "M" / "a.mp3")
    pipe._idx = _indice(tmp_path, s, m)
    monkeypatch.setattr(pf_pipeline, "musicas_usadas", lambda *a, **k: {m})
    visto = {}

    def gen(db, c, idx, *a, **k):
        visto["trilhas"] = idx.all()
        return Roteiro(arco="a", pecas=[], alertas=[])
    monkeypatch.setattr(pf_pipeline, "generate_roteiro", gen)
    pipe._st_roteiro()
    ad = Path(pipe.p.analysis_dir)
    pipe.close()
    assert visto["trilhas"] == []
    assert carregar_projeto(ad).musica is None


def test_ideia_da_original(tmp_path, monkeypatch):
    orig, s, _ = _pipe(tmp_path)
    orig.db.add_roteiro('{"arco": "ideia antiga"}')
    orig.close()
    pipe, _, _ = _pipe(tmp_path, nome="2026-03-11 OFICINA ESCOLA X T107",
                       duplicado_de=str(orig.source))
    visto = {}
    monkeypatch.setattr(pf_pipeline, "contexto_clipe",
                        lambda pf, ficha, ideia: visto.update(ideia=ideia, ficha=ficha) or (lambda *a, **k: ""))
    monkeypatch.setattr(pf_pipeline, "generate_roteiro",
                        lambda *a, **k: Roteiro(arco="a", pecas=[], alertas=[]))
    pipe._st_roteiro()
    pipe.close()
    assert visto["ideia"] == '{"arco": "ideia antiga"}'
    assert visto["ficha"].instituicao == "Escola X"


def test_continuar_mantem_a_musica_gravada(tmp_path, monkeypatch):
    pipe, s, pf = _pipe(tmp_path)
    m = str(tmp_path / "M" / "a.mp3")
    pipe._idx = _indice(tmp_path, s, m)
    monkeypatch.setattr(pf_pipeline, "generate_roteiro", lambda *a, **k: _roteiro(m))
    pipe._st_roteiro()
    pipe.close()
    # o editor reabre pelo formulário: o pedido vem sem a música
    again, _, _ = _pipe(tmp_path)
    _sem_etapas(again)
    again.run()
    ad = Path(again.p.analysis_dir)
    again.close()
    assert carregar_projeto(ad).musica == m
def test_area_usa_pipeline_da_formatura():
    from roteiro_ia.areas import area_por_id
    assert area_por_id("formatura").pipeline is PipelineFormatura


def test_ajuste_da_colacao_reaproveita_medidas(tmp_path, monkeypatch):
    from roteiro_ia.areas.formatura.colacao.defeitos import Amostras
    from roteiro_ia.areas.formatura.colacao.partes import ParteNomeada
    from roteiro_ia.models import MediaInfo, SyncResult
    import numpy as np
    pipe, s, _ = _pipe(tmp_path, tipo="colacao", nome="2026-12-10 COLACAO ESCOLA X",
                       funcoes={"PGM": "mesa_corte"}, turmas_colacao=[("Eletrônica", "T106")])
    mid = pipe.db.add_media(MediaInfo(rel_path="PGM\p.mp4", folder="PGM", role=Role.mesa,
                                      day_label="principal", kind="video", duration_s=60, fps_num=30,
                                      fps_den=1, width=320, height=180, rotation=0, audio_channels=2))
    proxy = tmp_path / "p480.mp4"
    proxy.write_bytes(b"x")
    pipe.db.set_proxy(mid, str(proxy), "gerado")
    pipe.db.set_sync(SyncResult(media_id=mid, day_label="principal", timeline_start_s=0,
                                confidence=9, method="audio"))
    medicoes, pedidos = [], []
    monkeypatch.setattr(pf_pipeline, "medir", lambda v: medicoes.append(v) or Amostras(
        np.full(8, 120.0), np.full(8, 20.0), np.full(8, 2.0)))
    monkeypatch.setattr(pf_pipeline, "silencios", lambda a, limite: [(10.0, 20.0)])

    def partes(c, model, linhas, turmas, fim, pedido=None):
        pedidos.append(pedido)
        return [ParteNomeada(codigo="abertura", nome="Abertura", inicio_s=0)], []
    monkeypatch.setattr(pf_pipeline, "detectar_partes", partes)
    pipe._plano_integra()
    pipe._pedido = "o hino começa em 0:00:30"
    plano = pipe._plano_integra()
    pipe.close()
    assert len(medicoes) == 1 and pedidos == [None, "o hino começa em 0:00:30"]
    assert plano.partes[0].cortes == [(10.5, 19.5)]
