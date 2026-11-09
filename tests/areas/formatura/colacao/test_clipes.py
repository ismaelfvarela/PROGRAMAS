from roteiro_ia.areas.formatura.ajustes import AjustesFormatura, carregar_ajustes, salvar_ajustes
from roteiro_ia.areas.formatura.cadastro import Curso, Formatura
from roteiro_ia.areas.formatura.colacao.clipes import contexto_abertura_encerramento, nomes_clipes
from roteiro_ia.areas.formatura.colacao.partes import ParteNomeada
from roteiro_ia.areas.formatura.projeto import ProjetoFormatura
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.music_index import MusicIndex


def test_ajustes_ida_e_volta(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    assert carregar_ajustes(s).logo_produtora is None
    salvar_ajustes(s, AjustesFormatura(logo_produtora="C:\\logo.png"))
    assert carregar_ajustes(s).logo_produtora == "C:\\logo.png"
    (tmp_path / "s" / "FORMATURAS" / "_ajustes.json").write_text("{", encoding="utf-8")
    assert carregar_ajustes(s).logo_produtora is None


def test_ajustes_nao_aparece_como_formatura(tmp_path):
    from roteiro_ia.areas.formatura.cadastro import listar
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    salvar_ajustes(s, AjustesFormatura(logo_produtora="x"))
    assert listar(s) == []


def test_nomes_clipes():
    assert nomes_clipes(12) == ("00 - Abertura", "13 - Encerramento")


def test_contexto(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    db, idx = ProjectDB(tmp_path / "p.db", s), MusicIndex(tmp_path / "t.db", s)
    ficha = Formatura(id="x", instituicao="Escola X", ano=2026, semestre=2,
                      cursos=[Curso(nome="Eletrônica", turmas=["T106"])])
    pf = ProjetoFormatura(tipo="colacao", formatura_id="x", local="Teatro Municipal", cidade="Joinville",
                          turmas_colacao=[("Eletrônica", "T106")])
    partes = [ParteNomeada(codigo="abertura", nome="Abertura do Mestre", inicio_s=0),
              ParteNomeada(codigo="paraninfos", nome="Paraninfos", inicio_s=3725)]
    try:
        txt = contexto_abertura_encerramento(pf, ficha, partes, "2026-12-10")(db, idx, None, None,
                                                                              {"trailer", "teaser"})
    finally:
        db.close()
        idx.close()
    for trecho in ('tipo "trailer"', 'tipo "teaser"', "180 s", "5 s", "decoração", "bastidores",
                   "grande final", "alunos", "paraninfos", "animado", "logo", "últimos 4 s",
                   "Escola X", "Eletrônica — T106", "Teatro Municipal", "Joinville", "10/12/2026",
                   "[1:02:05] Paraninfos", "chicote", 'origem "popular"'):
        assert trecho in txt, trecho
    assert "GANCHO" not in txt


def test_dialogo_grava_logo(qtbot, tmp_path):
    from roteiro_ia.areas.formatura.ui_cadastro import DialogoCadastro
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    d = DialogoCadastro(s)
    qtbot.addWidget(d)
    assert d.edit_logo.text() == ""
    d.definir_logo("C:\\Fokuss\\logo.png")
    assert carregar_ajustes(s).logo_produtora == "C:\\Fokuss\\logo.png"
    d2 = DialogoCadastro(s)
    qtbot.addWidget(d2)
    assert d2.edit_logo.text() == "C:\\Fokuss\\logo.png"
