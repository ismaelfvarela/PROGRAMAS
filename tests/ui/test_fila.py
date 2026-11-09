"""Fila de projetos no mesmo PC: um projeto por vez; a pausa da cota deixa o próximo adiantar."""
import threading
from datetime import datetime, timedelta

import pytest

from roteiro_ia import controle
from roteiro_ia.controle import Interrompido
from roteiro_ia.ui.fila import FilaProjetos


class Falso:
    """Cliente da fila que só registra as chamadas."""

    def __init__(self, nome):
        self.nome, self.log, self.espera = nome, [], None

    def nome_fila(self):
        return self.nome

    def comecar(self):
        self.log.append("comecar")

    def suspender(self):
        self.log.append("suspender")

    def retomar_suspenso(self):
        self.log.append("retomar_suspenso")

    def mostrar_espera(self, texto):
        self.espera = texto


@pytest.fixture
def fab():
    return FilaProjetos(), Falso("2023-09-09 A"), Falso("2026-12-01 B")


def test_segundo_espera_e_comeca_quando_primeiro_termina(qtbot):
    f, a, b = FilaProjetos(), Falso("2023-09-09 A"), Falso("2026-12-01 B")
    f.pedir(a)
    f.pedir(b)
    assert a.log == ["comecar"] and b.espera == "Na fila — começa quando 2023-09-09 A terminar."
    assert b.log == []
    assert f.ativo() is a and f.na_fila() == [b]
    f.sair(a)
    assert b.log == ["comecar"] and b.espera is None
    assert f.ativo() is b and f.na_fila() == []


def test_cota_deixa_o_proximo_adiantar_e_primeiro_retoma_com_prioridade(fab):
    f, a, b = fab
    f.pedir(a)
    f.pedir(b)
    f.esperando_cota(a)
    assert b.log == ["comecar"]
    f.pedir(a)                                   # cota voltou
    assert b.log == ["comecar", "suspender"] and a.log[-1] == "comecar"
    f.sair(a)
    assert b.log[-1] == "retomar_suspenso"


def test_tirar_da_fila(fab):
    f, a, b = fab
    f.pedir(a)
    f.pedir(b)
    f.sair(b)
    assert f.na_fila() == [] and b.espera is None
    f.sair(a)
    assert b.log == []
    assert f.ativo() is None


def test_pedir_de_novo_mantem_o_lugar(fab):
    f, a, b = fab
    c = Falso("2027-01-01 C")
    f.pedir(a)
    f.pedir(b)
    f.pedir(c)
    f.esperando_cota(a)               # b adianta; c segue esperando por b
    assert b.log == ["comecar"] and c.espera == "Na fila — começa quando 2026-12-01 B terminar."
    f.pedir(a)
    assert c.espera == "Na fila — começa quando 2023-09-09 A terminar."
    assert f.na_fila() == [c]


def test_mudou_avisa_cada_mudanca(qtbot, fab):
    f, a, b = fab
    vezes = []
    f.mudou.connect(lambda: vezes.append(1))
    f.pedir(a)
    f.pedir(b)
    f.esperando_cota(a)
    f.sair(b)
    assert len(vezes) == 4


# ------------------------------------------------------------------ aba Projeto

class _Pipe:
    """run() passa por checkpoints até ser liberado. Com `cota`, a 1ª execução volta "pausado"."""

    def __init__(self, liberar, chamadas, cota=False):
        self.liberar, self.chamadas, self.cota = liberar, chamadas, cota
        self.resume_at = None

    def run(self, aprovado_custo=False, refazer_falhas=True):
        self.chamadas.append("run")
        if self.cota and len(self.chamadas) == 1:
            self.resume_at = (datetime.now() + timedelta(hours=2)).astimezone()
            return "pausado"
        try:
            while not self.liberar.is_set():
                controle.atual().checkpoint()
                self.liberar.wait(0.05)
        except Interrompido:
            return "parado"
        return "concluido"

    def close(self):
        pass


@pytest.fixture
def duas_abas(qtbot, settings_tmp, tmp_path, evento):
    from roteiro_ia.ui.projeto import ProjetoTab
    from roteiro_ia.ui.worker import Runner
    ev_b = tmp_path / "R" / "2026-12-01 CASAMENTO B"
    for sub in ("A", "TRILHAS"):
        (ev_b / sub).mkdir(parents=True)
    runner, fila = Runner(), FilaProjetos()
    abas = []
    for ev, cota in ((evento, True), (ev_b, False)):
        liberar, chamadas = threading.Event(), []
        tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", runner,
                         factory=lambda req, s, e, l=liberar, c=chamadas, k=cota: _Pipe(l, c, k),
                         fila=fila)
        qtbot.addWidget(tab)
        assert tab.set_event_folder(ev)
        abas.append((tab, liberar, chamadas))
    yield fila, abas
    for _tab, liberar, _c in abas:
        liberar.set()
    runner.wait_all(5000)


def test_aba_sem_fila_compartilhada_comeca_na_hora(qtbot, settings_tmp, tmp_path, evento):
    from roteiro_ia.ui.projeto import ProjetoTab
    from roteiro_ia.ui.worker import Runner
    liberar, chamadas = threading.Event(), []
    runner = Runner()
    tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", runner,
                     factory=lambda req, s, e: _Pipe(liberar, chamadas))
    qtbot.addWidget(tab)
    assert isinstance(tab.fila, FilaProjetos)
    assert tab.set_event_folder(evento)
    tab.btn_iniciar.click()
    qtbot.waitUntil(lambda: chamadas == ["run"], timeout=3000)
    assert tab.fila.ativo() is tab and not tab.status.btn_tirar_fila.isVisibleTo(tab)
    liberar.set()
    qtbot.waitUntil(lambda: tab.status.painel_final.isVisibleTo(tab), timeout=5000)
    assert tab.fila.ativo() is None
    runner.wait_all(5000)


def test_segunda_aba_espera_e_comeca_quando_a_primeira_termina(qtbot, duas_abas):
    fila, ((a, lib_a, cham_a), (b, lib_b, cham_b)) = duas_abas
    a._factory = lambda req, s, e: _Pipe(lib_a, cham_a)  # sem cota neste teste
    a.btn_iniciar.click()
    qtbot.waitUntil(lambda: cham_a == ["run"], timeout=3000)
    b.btn_iniciar.click()
    assert b.status.lbl_mensagem.text() == ("Na fila — começa quando 2023-09-09 CASAMENTO TESTE "
                                            "terminar.")
    assert b.status.btn_tirar_fila.isVisibleTo(b)
    assert b.status.btn_tirar_fila.text() == "Tirar da fila"
    assert not b.btn_iniciar.isEnabled() and fila.na_fila() == [b]
    assert a.nome_fila() == "2023-09-09 CASAMENTO TESTE"
    lib_a.set()
    qtbot.waitUntil(lambda: cham_b == ["run"], timeout=5000)
    assert not b.status.btn_tirar_fila.isVisibleTo(b) and fila.ativo() is b
    lib_b.set()
    qtbot.waitUntil(lambda: b.status.painel_final.isVisibleTo(b), timeout=5000)
    assert fila.ativo() is None


def test_tirar_da_fila_na_aba(qtbot, duas_abas):
    fila, ((a, lib_a, cham_a), (b, _lib_b, cham_b)) = duas_abas
    a._factory = lambda req, s, e: _Pipe(lib_a, cham_a)
    a.btn_iniciar.click()
    qtbot.waitUntil(lambda: cham_a == ["run"], timeout=3000)
    b.btn_iniciar.click()
    b.status.btn_tirar_fila.click()
    assert fila.na_fila() == [] and not b.rodando and b.btn_iniciar.isEnabled()
    assert not b.status.btn_tirar_fila.isVisibleTo(b)
    assert "Na fila" not in b.status.lbl_mensagem.text()
    lib_a.set()
    qtbot.waitUntil(lambda: a.status.painel_final.isVisibleTo(a), timeout=5000)
    assert cham_b == [] and fila.ativo() is None


def test_cota_adianta_a_segunda_e_a_primeira_retoma_com_prioridade(qtbot, duas_abas):
    fila, ((a, lib_a, cham_a), (b, lib_b, cham_b)) = duas_abas
    a.btn_iniciar.click()
    b.btn_iniciar.click()
    qtbot.waitUntil(lambda: a.em_pausa_cota(), timeout=3000)       # a espera a cota…
    qtbot.waitUntil(lambda: cham_b == ["run"], timeout=3000)      # …e b adianta
    qtbot.waitUntil(lambda: b.controles.estado == "rodando", timeout=3000)
    a.continuar_agora()                                           # a cota voltou
    qtbot.waitUntil(lambda: cham_a == ["run", "run"], timeout=3000)
    qtbot.waitUntil(lambda: b._worker.controle.estado == "pausado", timeout=3000)
    assert "2023-09-09 CASAMENTO TESTE" in b.status.lbl_mensagem.text()
    b.continuar()                                                 # a prioridade é de a
    assert b._worker.controle.estado == "pausado"
    lib_a.set()
    qtbot.waitUntil(lambda: a.status.painel_final.isVisibleTo(a), timeout=5000)
    qtbot.waitUntil(lambda: b._worker.controle.estado == "rodando", timeout=3000)
    lib_b.set()
    qtbot.waitUntil(lambda: b.status.painel_final.isVisibleTo(b), timeout=5000)
    assert fila.ativo() is None and cham_b == ["run"]


def test_formatura_iniciar_direto_recusa(qtbot, settings_tmp, tmp_path, evento):
    from roteiro_ia.ui.projeto import ProjetoTab
    from roteiro_ia.ui.worker import Runner
    chamadas, runner = [], Runner()
    tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", runner,
                     factory=lambda req, s, e: chamadas.append("factory"), area="formatura")
    qtbot.addWidget(tab)
    assert tab.set_event_folder(evento)
    tab.iniciar()  # ex.: via abrir_existente/continuar_existente
    assert not tab.rodando and tab._worker is None and chamadas == []
    assert tab.status.banner_erro.text() == "A Formatura chega na próxima etapa."
    runner.wait_all(5000)  # a leitura da pasta roda numa thread


class _PipeErro:
    """Espera ser liberado e então falha."""

    def __init__(self, liberar, chamadas):
        self.liberar, self.chamadas = liberar, chamadas

    def run(self, aprovado_custo=False, refazer_falhas=True):
        self.chamadas.append("run")
        self.liberar.wait(5)
        raise RuntimeError("falhou de propósito")

    def close(self):
        pass


def test_fila_avanca_quando_o_primeiro_termina_parado(qtbot, duas_abas):
    fila, ((a, lib_a, cham_a), (b, lib_b, cham_b)) = duas_abas
    a._factory = lambda req, s, e: _Pipe(lib_a, cham_a)
    a.btn_iniciar.click()
    qtbot.waitUntil(lambda: cham_a == ["run"], timeout=3000)
    b.btn_iniciar.click()
    assert fila.na_fila() == [b] and cham_b == []
    a.parar()
    qtbot.waitUntil(lambda: cham_b == ["run"], timeout=5000)
    assert fila.ativo() is b and not a.rodando
    lib_b.set()
    qtbot.waitUntil(lambda: b.status.painel_final.isVisibleTo(b), timeout=5000)
    assert fila.ativo() is None


def test_fila_avanca_quando_o_primeiro_termina_com_erro(qtbot, duas_abas):
    fila, ((a, lib_a, cham_a), (b, lib_b, cham_b)) = duas_abas
    a._factory = lambda req, s, e: _PipeErro(lib_a, cham_a)
    a.btn_iniciar.click()
    qtbot.waitUntil(lambda: cham_a == ["run"], timeout=3000)
    b.btn_iniciar.click()
    assert fila.na_fila() == [b] and cham_b == []
    lib_a.set()                                 # a falha -> b começa
    qtbot.waitUntil(lambda: cham_b == ["run"], timeout=5000)
    assert fila.ativo() is b and not a.rodando
    lib_b.set()
    qtbot.waitUntil(lambda: b.status.painel_final.isVisibleTo(b), timeout=5000)
    assert fila.ativo() is None
