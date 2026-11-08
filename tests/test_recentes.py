import json
import os
from datetime import datetime
from pathlib import Path

from roteiro_ia import recentes
from roteiro_ia.config import Settings


def _s(tmp_path):
    return Settings(system_dir=str(tmp_path / "SIS"), work_drive=str(tmp_path / "Y"),
                    protected_roots=[str(tmp_path / "R")])


def _projeto(tmp_path, nome, mtime=None):
    """Cria <Y>/EDIÇÃO <ano>/<nome>/ANALISE/projeto.json como o pipeline grava."""
    src = tmp_path / "R" / nome
    src.mkdir(parents=True, exist_ok=True)
    an = tmp_path / "Y" / f"EDIÇÃO {nome[:4]}" / nome / "ANALISE"
    an.mkdir(parents=True)
    f = an / "projeto.json"
    f.write_text(json.dumps({"source_dir": str(src), "work_drive": str(tmp_path / "Y")}),
                 encoding="utf-8")
    if mtime:
        os.utime(f, (mtime.timestamp(), mtime.timestamp()))
    return src


def test_ultimo_aberto_primeiro_sem_repetir(tmp_path):
    s = _s(tmp_path)
    a = _projeto(tmp_path, "2023-09-09 CASAMENTO A")
    b = _projeto(tmp_path, "2024-01-20 CASAMENTO B")
    y = str(tmp_path / "Y")
    recentes.registrar(s, a, y, datetime(2026, 11, 1, 10))
    recentes.registrar(s, b, y, datetime(2026, 11, 2, 10))
    recentes.registrar(s, a, y, datetime(2026, 11, 3, 10))
    itens = recentes.listar(s, [y])
    assert [r.nome for r in itens] == ["2023-09-09 CASAMENTO A", "2024-01-20 CASAMENTO B"]
    assert itens[0].aberto_em == datetime(2026, 11, 3, 10)
    assert itens[0].alterado_em is not None


def test_projeto_do_disco_aparece_mesmo_sem_ter_sido_aberto_aqui(tmp_path):
    # projetos criados antes desta lista (ex.: Nicole e Osny) são achados no disco de trabalho
    s = _s(tmp_path)
    y = str(tmp_path / "Y")
    velho = _projeto(tmp_path, "2022-05-01 VELHO", datetime(2025, 1, 1))
    novo = _projeto(tmp_path, "2023-09-09 NOVO", datetime(2026, 1, 1))
    aberto = _projeto(tmp_path, "2021-02-02 ABERTO", datetime(2020, 1, 1))
    recentes.registrar(s, aberto, y)
    assert [r.pasta for r in recentes.listar(s, [y, y])] == [aberto, novo, velho]


def test_projeto_apagado_some_da_lista(tmp_path):
    s = _s(tmp_path)
    y = str(tmp_path / "Y")
    recentes.registrar(s, tmp_path / "R" / "2023-09-09 SUMIU", y)
    recentes.registrar(s, Path("Z:/nao-e-evento"), y)
    assert recentes.listar(s, [y]) == []


def test_arquivo_corrompido_nao_quebra(tmp_path):
    s = _s(tmp_path)
    (tmp_path / "SIS").mkdir()
    (tmp_path / "SIS" / recentes.ARQUIVO).write_text("{lixo", encoding="utf-8")
    assert recentes.listar(s, [str(tmp_path / "Y")]) == []
    recentes.registrar(s, _projeto(tmp_path, "2023-09-09 X"), str(tmp_path / "Y"))
    assert len(recentes.listar(s, [])) == 1


def test_quando_texto():
    agora = datetime(2026, 11, 8, 18, 0)
    assert recentes.quando_texto(datetime(2026, 11, 8, 17, 20), agora) == "hoje 17:20"
    assert recentes.quando_texto(datetime(2026, 11, 7, 9, 5), agora) == "ontem 09:05"
    assert recentes.quando_texto(datetime(2026, 10, 1, 9, 5), agora) == "01/10/2026 09:05"
    assert recentes.quando_texto(None, agora) == "sem data"
