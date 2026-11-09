import pytest

from roteiro_ia.areas.formatura.funcoes import (ROLE_DA_FUNCAO, ROTULO_FUNCAO, FuncaoFormatura,
                                                funcoes_do_grupo, listar_pastas, sugerir_funcao)
from roteiro_ia.areas.formatura.momentos import (MOMENTOS_FORMATURA, MOMENTOS_POR_TIPO,
                                                 PROBLEMAS_TECNICOS)
from roteiro_ia.areas.formatura.tipos import INFO_TIPO, TIPOS_CLIPE, TipoTrabalho
from roteiro_ia.models import Role


@pytest.mark.parametrize("pasta,grupo,esperado", [
    ("CAM A", "clipe", "camera"), ("CAM 1", "colacao", "camera_iso"),
    ("PGM", "colacao", "mesa_corte"), ("CORTE", "colacao", "mesa_corte"),
    ("ATEM", "colacao", "mesa_corte"), ("H4", "clipe", "gravador"), ("H1", "colacao", "gravador"),
    ("MIC LAPELA", "clipe", "gravador"), ("ZOOM H6", "clipe", "gravador"),
    ("FRIAS", "colacao", "extras"), ("2026-03-10\\DECORAÇÃO", "colacao", "extras"),
    ("bastidores", "clipe", "extras"), ("DRONE", "clipe", "drone"), ("Proxies", "clipe", "ignorar"),
    ("Adobe Premiere Pro Auto-Save", "colacao", "ignorar"),
    ("2026-03-10\\CAM B", "clipe", "camera"), ("CHAMADA", "clipe", "camera"),
    ("PGM", "clipe", "camera"),  # mesa de corte não existe nos clipes
])
def test_sugerir_funcao(pasta, grupo, esperado):
    assert sugerir_funcao(pasta, grupo) == esperado


def test_funcoes_por_grupo_e_roles():
    clipe = funcoes_do_grupo("clipe")
    assert FuncaoFormatura.mesa_corte not in clipe and FuncaoFormatura.camera_iso not in clipe
    assert FuncaoFormatura.camera not in funcoes_do_grupo("colacao")
    assert ROLE_DA_FUNCAO[FuncaoFormatura.mesa_corte] == Role.mesa
    assert ROLE_DA_FUNCAO[FuncaoFormatura.gravador] == Role.audio_ambiente
    assert ROLE_DA_FUNCAO[FuncaoFormatura.extras] == Role.drone
    assert ROLE_DA_FUNCAO[FuncaoFormatura.camera_iso] == Role.camera
    assert set(ROTULO_FUNCAO) == set(FuncaoFormatura) == set(ROLE_DA_FUNCAO)
    assert ROTULO_FUNCAO[FuncaoFormatura.mesa_corte] == "Mesa de corte (programa)"


def test_listar_pastas_com_dias(tmp_path):
    (tmp_path / "2026-03-10" / "CAM A").mkdir(parents=True)
    (tmp_path / "2026-03-10" / "H4").mkdir()
    (tmp_path / "2026-03-10" / "Proxies").mkdir()
    (tmp_path / "2026-03-12" / "CAM A").mkdir(parents=True)
    (tmp_path / "MISTO" / "SUB").mkdir(parents=True)
    (tmp_path / "MISTO" / "a.MP4").write_bytes(b"")
    (tmp_path / "DRONE").mkdir()
    (tmp_path / "Proxies").mkdir()
    assert listar_pastas(tmp_path) == [
        ("2026-03-10\\CAM A", "2026-03-10"), ("2026-03-10\\H4", "2026-03-10"),
        ("2026-03-12\\CAM A", "2026-03-12"), ("DRONE", "principal"), ("MISTO", "principal"),
        ("Proxies", "principal")]


def test_listar_pastas_um_nivel(tmp_path):
    for d in ("CAM A", "H4"):
        (tmp_path / d).mkdir()
    (tmp_path / "CAM A" / "C1.MP4").write_bytes(b"")
    assert listar_pastas(tmp_path) == [("CAM A", "principal"), ("H4", "principal")]


def test_tipos_e_momentos():
    assert TIPOS_CLIPE == [TipoTrabalho.oficina, TipoTrabalho.feira, TipoTrabalho.prova_toga,
                           TipoTrabalho.paraninfo]
    assert INFO_TIPO[TipoTrabalho.oficina].turma == "obrigatoria"
    assert INFO_TIPO[TipoTrabalho.oficina].duracao_min == 4
    assert INFO_TIPO[TipoTrabalho.feira].turma == "nenhuma"
    assert INFO_TIPO[TipoTrabalho.feira].duracao_min == 8
    assert INFO_TIPO[TipoTrabalho.colacao].grupo == "colacao"
    assert INFO_TIPO[TipoTrabalho.paraninfo].nome == "Escolha do paraninfo"
    assert set(MOMENTOS_POR_TIPO) == set(TipoTrabalho)
    assert all(v[-1] == "extra" for v in MOMENTOS_POR_TIPO.values())
    assert "depoimento" in MOMENTOS_POR_TIPO[TipoTrabalho.oficina]
    assert "chicote" in PROBLEMAS_TECNICOS
    assert len(MOMENTOS_FORMATURA) == 14
