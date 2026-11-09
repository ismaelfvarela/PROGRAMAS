import re
from pathlib import Path

import pytest

from roteiro_ia.areas.formatura.cadastro import (Curso, Formatura, avisos, carregar, duplicar,
                                                 listar, nome_exibicao, salvar)


def _f(**kw):
    base = dict(instituicao="Escola X", ano=2026, semestre=2,
                cursos=[Curso(nome="Técnico em Eletrônica", turmas=["T106", "T107"])])
    base.update(kw)
    return Formatura(**base)


def test_salvar_e_listar(settings_tmp):
    f = salvar(settings_tmp, _f())
    assert re.fullmatch(r"escola-x-2026-2-[0-9a-f]{4}", f.id)
    assert (Path(settings_tmp.system_dir) / "FORMATURAS" / f"{f.id}.json").is_file()
    salvar(settings_tmp, _f(instituicao="Alfa", ano=2027, semestre=1))
    salvar(settings_tmp, _f(instituicao="Beta", ano=2026, semestre=2))
    assert [x.instituicao for x in listar(settings_tmp)] == ["Alfa", "Beta", "Escola X"]
    assert carregar(settings_tmp, f.id) == f
    assert carregar(settings_tmp, "nao-existe") is None
    assert nome_exibicao(f) == "ESCOLA X — 2026/2"


def test_salvar_de_novo_mantem_id(settings_tmp):
    f = salvar(settings_tmp, _f())
    g = salvar(settings_tmp, f.model_copy(update={"instituicao": "Escola X Nova"}))
    assert g.id == f.id and len(listar(settings_tmp)) == 1


def test_id_sem_acentos(settings_tmp):
    f = salvar(settings_tmp, _f(instituicao="Colégio São João"))
    assert f.id.startswith("colegio-sao-joao-2026-2-")


@pytest.mark.parametrize("kw,msg", [
    ({"instituicao": "  "}, "Informe a instituição."),
    ({"cursos": []}, "Cadastre pelo menos um curso."),
    ({"cursos": [Curso(nome="A", turmas=[])]}, "O curso A está sem turma."),
    ({"cursos": [Curso(nome="A", turmas=["T1", " t1 "])]}, "Turma repetida no curso A: t1."),
    ({"cursos": [Curso(nome=" ", turmas=["T1"])]}, "Há um curso sem nome."),
])
def test_validacao(settings_tmp, kw, msg):
    with pytest.raises(ValueError, match=re.escape(msg)):
        salvar(settings_tmp, _f(**kw))
    assert listar(settings_tmp) == []


def test_duplicar_e_avisos(tmp_path):
    f = _f(id="x", logo_escola=str(tmp_path / "sumiu.png"), pasta_grafismos=str(tmp_path))
    d = duplicar(f)
    assert (d.id, d.ano, d.semestre, d.instituicao) == ("", 2027, 1, "Escola X")
    assert (duplicar(_f(semestre=1)).ano, duplicar(_f(semestre=1)).semestre) == (2026, 2)
    assert avisos(f) == [f"Logo da escola não encontrado: {tmp_path / 'sumiu.png'}"]
    assert avisos(_f(pasta_grafismos=str(tmp_path / "nada"))) == [
        f"Pasta de grafismos não encontrada: {tmp_path / 'nada'}"]


def test_arquivo_ilegivel_e_pulado(settings_tmp):
    salvar(settings_tmp, _f())
    (Path(settings_tmp.system_dir) / "FORMATURAS" / "ruim.json").write_text("{", encoding="utf-8")
    assert [x.instituicao for x in listar(settings_tmp)] == ["Escola X"]
    assert carregar(settings_tmp, "ruim") is None


def test_listar_sem_pasta(settings_tmp):
    assert listar(settings_tmp) == []
