import os
import uuid

import pytest


def test_listar_discos_nao_consulta_volumes(monkeypatch):
    from PySide6.QtCore import QStorageInfo
    from roteiro_ia.ui import formulario

    def lento():
        raise AssertionError("mountedVolumes trava com disco de rede desconectado")
    if os.name == "nt":
        monkeypatch.setattr(QStorageInfo, "mountedVolumes", staticmethod(lento))
    discos = formulario.listar_discos()
    atual = os.path.splitdrive(os.getcwd())[0].upper()
    assert discos and all(len(d) == 2 and d[1] == ":" for d in discos)
    if os.name == "nt" and len(atual) == 2:
        assert atual in discos


@pytest.mark.skipif(os.name != "nt", reason="mutex nomeado do Windows")
def test_trava_segunda_instancia_nao_e_primeira():
    from roteiro_ia.ui.instancia import Trava
    nome = f"RoteiroIA-teste-{uuid.uuid4().hex}"
    a = Trava(nome)
    b = Trava(nome)
    try:
        assert a.primeira and not b.primeira
    finally:
        b.liberar()
        a.liberar()
    c = Trava(nome)  # liberadas: a próxima abertura volta a ser a primeira
    assert c.primeira
    c.liberar()


def test_segunda_instancia_pede_para_mostrar(qtbot):
    # o segundo clique é outro processo: o aviso sai de um subprocesso de verdade
    import subprocess
    import sys
    from roteiro_ia.ui.instancia import Servidor
    nome = f"RoteiroIA-teste-{uuid.uuid4().hex}"
    srv = Servidor(nome)
    with qtbot.waitSignal(srv.mostrar, timeout=10000):
        p = subprocess.Popen([sys.executable, "-c",
                              "import sys; from roteiro_ia.ui.instancia import avisar_primeira; "
                              f"sys.exit(0 if avisar_primeira({nome!r}, espera_s=8) else 3)"])
    assert p.wait(15) == 0
    srv.fechar()


def test_aviso_sem_instancia_aberta_desiste(qtbot):
    from roteiro_ia.ui.instancia import avisar_primeira
    assert not avisar_primeira(f"RoteiroIA-teste-{uuid.uuid4().hex}", espera_s=0.5)
