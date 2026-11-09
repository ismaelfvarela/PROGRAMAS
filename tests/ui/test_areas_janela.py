"""Janela com seletor de áreas: uma página por área, Trilhas/Configurações únicas, fila comum."""
import threading
from datetime import datetime, timedelta

import pytest

from roteiro_ia import controle
from roteiro_ia.config import load_settings
from roteiro_ia.controle import Interrompido


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


class _Cliente:
    """Cliente da fila que só espera (ex.: projeto de outra aba)."""

    def __init__(self, nome):
        self.nome = nome

    def nome_fila(self):
        return self.nome

    def comecar(self):
        pass

    def suspender(self):
        pass

    def retomar_suspenso(self):
        pass

    def mostrar_espera(self, texto):
        pass


@pytest.fixture
def janela(qtbot, settings_tmp, tmp_path):
    from roteiro_ia.ui.app import MainWindow
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json")
    qtbot.addWidget(w)
    yield w
    w.runner.wait_all(5000)


@pytest.fixture
def janela_longa(qtbot, settings_tmp, tmp_path, evento):
    from roteiro_ia.ui.app import MainWindow
    liberar, chamadas = threading.Event(), []
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json",
                   factory=lambda req, s, ev: _Pipe(liberar, chamadas))
    qtbot.addWidget(w)
    assert w.projeto.set_event_folder(evento)
    yield w, liberar, chamadas
    liberar.set()
    w.runner.wait_all(5000)


def test_abre_na_ultima_area_e_troca(qtbot, settings_tmp, tmp_path):
    from roteiro_ia.ui.app import MainWindow
    settings_tmp.area_atual = "formatura"
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json")
    qtbot.addWidget(w)
    assert w.stack.currentWidget() is w.areas["formatura"]
    assert w.botoes_area["formatura"].isChecked() and not w.botoes_area["casamento"].isChecked()
    w.mostrar_area("casamento")
    assert w.stack.currentWidget() is w.areas["casamento"]
    assert w.botoes_area["casamento"].isChecked() and not w.botoes_area["formatura"].isChecked()
    assert settings_tmp.area_atual == "casamento"
    assert load_settings(tmp_path / "SISTEMA" / "config.json").area_atual == "casamento"
    w.runner.wait_all(5000)


def test_botoes_das_areas_na_ordem(janela):
    assert list(janela.areas) == ["casamento", "formatura"]
    bs = janela.botoes_area
    assert [bs[i].text() for i in ("casamento", "formatura")] == ["Casamento", "Formatura"]
    assert all(b.objectName() == "area" and b.isCheckable() for b in bs.values())
    assert janela.stack.currentWidget() is janela.areas["casamento"]  # padrão
    bs["formatura"].click()
    assert janela.stack.currentWidget() is janela.areas["formatura"]
    assert janela.s.area_atual == "formatura"


def test_trilhas_e_config_sao_uma_so_instancia(janela):
    w = janela
    cas, form = w.areas["casamento"].tabs, w.areas["formatura"].tabs
    assert [cas.tabText(i) for i in range(cas.count())] == [
        "Projeto", "Trilhas", "Estilo", "Configurações"]
    w.mostrar_area("formatura")
    assert form.indexOf(w.trilhas) == 1
    assert form.indexOf(w.config) == 3
    assert cas.indexOf(w.trilhas) == -1 and cas.indexOf(w.config) == -1
    assert [form.tabText(i) for i in range(form.count())] == [
        "Projeto", "Trilhas", "Estilo", "Configurações"]
    w.mostrar_area("casamento")
    assert cas.indexOf(w.trilhas) == 1 and cas.indexOf(w.config) == 3
    assert form.indexOf(w.trilhas) == -1


def test_projeto_casamento_e_o_atributo_antigo(janela):
    w = janela
    assert w.projeto is w.areas["casamento"].projeto
    assert w.estilo is w.areas["casamento"].estilo
    assert w.tabs is w.areas["casamento"].tabs
    assert w.areas["formatura"].projeto.area == "formatura"
    assert w.areas["formatura"].estilo is not w.estilo
    assert w.areas["formatura"].projeto.fila is w.fila and w.projeto.fila is w.fila


def test_fechar_com_projeto_na_fila_pergunta(janela, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    perguntas = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: perguntas.append(a) or QMessageBox.No)
    janela.fila.pedir(_Cliente("2023-09-09 A"))
    janela.fila.pedir(_Cliente("2026-12-01 B"))
    assert janela.fila.na_fila()
    e = QCloseEvent()
    janela.closeEvent(e)
    assert perguntas and not e.isAccepted()


def test_fechar_com_projeto_de_outra_area_rodando_pergunta(janela, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    perguntas = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: perguntas.append(a) or QMessageBox.No)
    janela.areas["formatura"].projeto.rodando = True
    e = QCloseEvent()
    janela.closeEvent(e)
    assert perguntas and not e.isAccepted()


def test_marca_na_area_fora_de_vista_com_projeto_rodando(qtbot, janela_longa):
    w, liberar, chamadas = janela_longa
    bs = w.botoes_area
    w.projeto.btn_iniciar.click()
    qtbot.waitUntil(lambda: chamadas == ["run"], timeout=3000)
    assert bs["casamento"].text() == "Casamento"  # à vista: sem marca
    w.mostrar_area("formatura")
    assert bs["casamento"].text() == "Casamento •"
    assert bs["formatura"].text() == "Formatura"
    liberar.set()
    qtbot.waitUntil(lambda: w.projeto.status.painel_final.isVisibleTo(w.projeto), timeout=5000)
    qtbot.waitUntil(lambda: bs["casamento"].text() == "Casamento", timeout=3000)


def test_barra_geral_conta_cota_de_outra_area(janela):
    w = janela
    pj = w.areas["formatura"].projeto
    pj.timer_retomar.start(60_000)  # pausa da cota (sem rodar nada)
    pj.mudou.emit()
    assert w.barra.lbl.text() == "1 processo(s) ativo(s)" and w.barra.btn_continuar.isEnabled()
    pj.timer_retomar.stop()
    pj.mudou.emit()
    assert w.barra.lbl.text() == "Nenhum processo ativo"


@pytest.fixture
def duas_na_janela(qtbot, settings_tmp, tmp_path, evento):
    """Janela + uma segunda aba de Casamento na mesma fila (a 1ª espera a cota uma vez)."""
    from roteiro_ia.ui.app import MainWindow
    from roteiro_ia.ui.projeto import ProjetoTab
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json")
    qtbot.addWidget(w)
    ev_b = tmp_path / "R" / "2026-12-01 CASAMENTO B"
    for sub in ("A", "TRILHAS"):
        (ev_b / sub).mkdir(parents=True)
    lib_a, cham_a, lib_b, cham_b = threading.Event(), [], threading.Event(), []
    a = w.projeto
    a._factory = lambda req, s, e: _Pipe(lib_a, cham_a, cota=True)
    b = ProjetoTab(settings_tmp, tmp_path / "SISTEMA" / "config.json", w.runner,
                   factory=lambda req, s, e: _Pipe(lib_b, cham_b), fila=w.fila)
    qtbot.addWidget(b)
    assert a.set_event_folder(evento) and b.set_event_folder(ev_b)
    yield w, (a, lib_a, cham_a), (b, lib_b, cham_b)
    lib_a.set()
    lib_b.set()
    w.runner.wait_all(5000)


def test_continuar_tudo_nao_solta_projeto_suspenso_pela_fila(qtbot, duas_na_janela):
    w, (a, lib_a, cham_a), (b, lib_b, cham_b) = duas_na_janela
    a.btn_iniciar.click()
    b.btn_iniciar.click()
    qtbot.waitUntil(lambda: a.em_pausa_cota(), timeout=3000)
    qtbot.waitUntil(lambda: cham_b == ["run"] and b.controles.estado == "rodando", timeout=3000)
    a.continuar_agora()  # a cota voltou: b fica suspenso
    qtbot.waitUntil(lambda: cham_a == ["run", "run"], timeout=3000)
    qtbot.waitUntil(lambda: b._worker.controle.estado == "pausado", timeout=3000)
    assert w.fila.suspensos() == [b]
    w.pausar_tudo()
    qtbot.waitUntil(lambda: a._worker.controle.estado == "pausado", timeout=3000)
    w.continuar_tudo()
    assert a._worker.controle.estado == "rodando"
    assert b._worker.controle.estado == "pausado"  # só a fila solta o b
    lib_a.set()
    qtbot.waitUntil(lambda: a.status.painel_final.isVisibleTo(a), timeout=5000)
    qtbot.waitUntil(lambda: b._worker.controle.estado == "rodando", timeout=3000)
    assert w.fila.suspensos() == []


def test_status_limpa_ao_sair_da_espera_e_da_suspensao(qtbot, duas_na_janela):
    from roteiro_ia.ui.projeto import TEXTO_PAUSA_COTA
    w, (a, lib_a, cham_a), (b, lib_b, cham_b) = duas_na_janela
    a.btn_iniciar.click()
    b.btn_iniciar.click()
    assert "Na fila" in b.status.lbl_mensagem.text()
    qtbot.waitUntil(lambda: a.em_pausa_cota(), timeout=3000)
    assert a.controles.lbl_estado.text() == TEXTO_PAUSA_COTA
    qtbot.waitUntil(lambda: cham_b == ["run"], timeout=3000)
    # b saiu da espera e começou: nada de "Na fila…" velho
    assert "Na fila" not in b.status.lbl_mensagem.text()
    assert b.controles.estado == "rodando"
    a.continuar_agora()
    # a voltou a rodar: os controles saem da pausa da cota
    assert a.controles.estado == "rodando" and a.controles.lbl_estado.text() != TEXTO_PAUSA_COTA
    qtbot.waitUntil(lambda: b._worker.controle.estado == "pausado", timeout=3000)
    assert "prioridade" in b.status.lbl_mensagem.text()
    lib_a.set()
    qtbot.waitUntil(lambda: a.status.painel_final.isVisibleTo(a), timeout=5000)
    # b retomou: o aviso de prioridade sai e os controles voltam a "rodando" na hora
    assert "prioridade" not in b.status.lbl_mensagem.text()
    assert b.controles.estado == "rodando"
    assert b.controles.lbl_estado.text() == ""
