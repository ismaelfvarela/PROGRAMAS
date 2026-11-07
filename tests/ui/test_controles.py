"""Play / Pause / Stop: componente, barra geral, aba Projeto (e pausa da cota), Trilhas e saída."""
import threading
from datetime import datetime, timedelta

import pytest

from roteiro_ia import controle
from roteiro_ia.controle import Interrompido


# ------------------------------------------------------------------ componente

@pytest.fixture
def ctl(qtbot):
    from roteiro_ia.ui.widgets import ControlesProcesso
    w = ControlesProcesso("Gerar perfil", texto_rodando="Gerando…")
    qtbot.addWidget(w)
    return w


def _hab(w):
    return (w.btn_play.isEnabled(), w.btn_pausar.isEnabled(), w.btn_parar.isEnabled())


def test_estados_dos_botoes(ctl):
    assert ctl.estado == "ocioso" and _hab(ctl) == (True, False, False)
    assert ctl.btn_play.text() == "Gerar perfil" and ctl.lbl_estado.text() == ""
    ctl.set_pode_iniciar(False)
    assert _hab(ctl) == (False, False, False)
    ctl.set_pode_iniciar(True)
    ctl.set_estado("rodando")
    assert _hab(ctl) == (False, True, True) and ctl.btn_play.text() == "Gerando…"
    ctl.set_estado("pausando")
    assert _hab(ctl) == (True, False, True)
    assert ctl.lbl_estado.text() == "Pausando após o arquivo atual…"
    assert ctl.btn_play.text() == "Continuar"
    ctl.set_estado("pausado")
    assert ctl.lbl_estado.text() == "Pausado" and _hab(ctl) == (True, False, True)
    ctl.set_estado("parando")
    assert ctl.lbl_estado.text() == "Parando…" and _hab(ctl) == (False, False, False)
    ctl.set_estado("parado")
    assert ctl.lbl_estado.text() == "Parado — pode continuar depois"
    assert _hab(ctl) == (True, False, False) and ctl.btn_play.text() == "Continuar"
    ctl.set_estado("pausado", "Pausado pela cota do Gemini")
    assert ctl.lbl_estado.text() == "Pausado pela cota do Gemini"
    assert not ctl.btn_play.icon().isNull() and not ctl.btn_parar.icon().isNull()


def test_play_emite_iniciar_ou_continuar(ctl, qtbot):
    with qtbot.waitSignal(ctl.iniciar, timeout=1000):
        ctl.btn_play.click()
    ctl.set_estado("pausado")
    with qtbot.waitSignal(ctl.continuar, timeout=1000):
        ctl.btn_play.click()
    ctl.set_estado("rodando")
    with qtbot.waitSignal(ctl.pausar, timeout=1000):
        ctl.btn_pausar.click()
    with qtbot.waitSignal(ctl.parar, timeout=1000):
        ctl.btn_parar.click()


# ------------------------------------------------------------------ workers / runner

def _laco(liberar: threading.Event):
    """Tarefa longa: passa por checkpoints até ser liberada ou parada."""
    def fn(progress):
        n = 0
        while not liberar.is_set():
            controle.atual().checkpoint()
            n += 1
            liberar.wait(0.05)
        return n
    return fn


def test_tarefa_parada_devolve_resultado_e_status_parado(qtbot):
    from roteiro_ia.ui.worker import Runner, TarefaWorker
    runner = Runner()
    liberar = threading.Event()

    def fn(progress):
        while True:
            try:
                controle.atual().checkpoint()
            except Interrompido:
                return "parcial"  # como update_index: devolve o que fez
            liberar.wait(0.05)
    w = TarefaWorker(fn, controlavel=True)
    res = []
    w.resultado.connect(res.append)
    with qtbot.waitSignal(w.terminou, timeout=5000) as b:
        runner.start(w)
        qtbot.waitUntil(lambda: runner.n_ativos() == 1, timeout=2000)
        runner.parar_todos()
    assert b.args == ["parado"] and res == ["parcial"]
    qtbot.waitUntil(lambda: not runner.ativo(), timeout=5000)


def test_runner_pausa_continua_e_para_todos(qtbot):
    from roteiro_ia.ui.worker import Runner, TarefaWorker
    runner = Runner()
    liberar = threading.Event()
    ws = [TarefaWorker(_laco(liberar), controlavel=True) for _ in range(2)]
    aux = TarefaWorker(lambda p: liberar.wait(5))  # tarefa auxiliar: não conta
    fins = []
    for w in ws:
        w.terminou.connect(fins.append)
        runner.start(w)
    runner.start(aux)
    assert runner.n_ativos() == 2
    runner.pausar_todos()
    qtbot.waitUntil(lambda: all(w.controle.estado == "pausado" for w in ws), timeout=3000)
    runner.continuar_todos()
    assert all(w.controle.estado == "rodando" for w in ws)
    runner.parar_todos()
    qtbot.waitUntil(lambda: fins == ["parado", "parado"], timeout=5000)
    liberar.set()
    qtbot.waitUntil(lambda: not runner.ativo(), timeout=5000)


# ------------------------------------------------------------------ janela

class _PipeLongo:
    """run() passa por checkpoints até ser liberado; Parar → "parado" (como o Pipeline)."""

    def __init__(self, liberar, chamadas):
        self.liberar, self.chamadas, self.resume_at = liberar, chamadas, None

    def run(self, aprovado_custo=False, refazer_falhas=True):
        self.chamadas.append("run")
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
def janela_longa(qtbot, settings_tmp, tmp_path, evento):
    from roteiro_ia.ui.app import MainWindow
    liberar, chamadas = threading.Event(), []
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json",
                   factory=lambda req, s, ev: _PipeLongo(liberar, chamadas))
    qtbot.addWidget(w)
    w.projeto.set_event_folder(evento)
    yield w, liberar, chamadas
    liberar.set()
    w.runner.wait_all(5000)


def test_projeto_pausar_parar_e_continuar(qtbot, janela_longa):
    w, liberar, chamadas = janela_longa
    pj = w.projeto
    ctl = pj.controles
    assert not ctl.btn_pausar.isEnabled() and not ctl.btn_parar.isEnabled()
    pj.btn_iniciar.click()
    qtbot.waitUntil(lambda: ctl.estado == "rodando" and ctl.btn_pausar.isEnabled(), timeout=3000)
    ctl.btn_pausar.click()
    assert ctl.lbl_estado.text() == "Pausando após o arquivo atual…"
    qtbot.waitUntil(lambda: ctl.lbl_estado.text() == "Pausado", timeout=3000)
    ctl.btn_parar.click()
    qtbot.waitUntil(lambda: ctl.estado == "parado", timeout=5000)
    assert ctl.lbl_estado.text() == "Parado — pode continuar depois"
    assert not pj.rodando and pj.btn_iniciar.isEnabled()
    assert "Continuar" in pj.status.lbl_mensagem.text()
    assert not pj.status.banner_erro.isVisibleTo(pj)
    ctl.btn_play.click()  # Continuar: roda de novo o mesmo pedido (retoma pelo banco)
    qtbot.waitUntil(lambda: len(chamadas) == 2 and ctl.estado == "rodando", timeout=3000)
    liberar.set()
    qtbot.waitUntil(lambda: pj.status.painel_final.isVisibleTo(pj), timeout=5000)
    assert ctl.estado == "ocioso"


def test_barra_geral_pausa_e_para_todos(qtbot, janela_longa):
    w, liberar, _ = janela_longa
    barra = w.barra
    assert barra.lbl.text() == "Nenhum processo ativo"
    assert not any(b.isEnabled() for b in (barra.btn_pausar, barra.btn_continuar, barra.btn_parar))
    w.projeto.btn_iniciar.click()
    extra = []

    def outro(progress):  # ex.: o índice de trilhas rodando ao mesmo tempo
        while True:
            controle.atual().checkpoint()
            liberar.wait(0.05)
    from roteiro_ia.ui.worker import TarefaWorker
    t = TarefaWorker(outro, controlavel=True)
    t.terminou.connect(extra.append)
    w.runner.start(t)
    qtbot.waitUntil(lambda: barra.lbl.text() == "2 processo(s) ativo(s)", timeout=3000)
    assert barra.btn_pausar.isEnabled() and barra.btn_parar.isEnabled()
    barra.btn_pausar.click()
    qtbot.waitUntil(lambda: w.projeto.controles.lbl_estado.text() == "Pausado"
                    and t.controle.estado == "pausado", timeout=3000)
    assert barra.btn_continuar.isEnabled() and not barra.btn_pausar.isEnabled()
    barra.btn_continuar.click()
    assert t.controle.estado == "rodando"
    barra.btn_parar.click()
    qtbot.waitUntil(lambda: extra == ["parado"] and w.projeto.controles.estado == "parado",
                    timeout=5000)
    qtbot.waitUntil(lambda: barra.lbl.text() == "Nenhum processo ativo", timeout=3000)
    assert not barra.btn_parar.isEnabled()


def test_pausa_da_cota_continuar_agora_e_parar(qtbot, janela_longa):
    w, liberar, _ = janela_longa
    pj = w.projeto
    pj._req = pj.form.build_request()
    quando = (datetime.now() + timedelta(hours=2)).astimezone()
    pj._on_retomar_em(quando)
    pj._on_terminou("pausado")
    assert pj.status.acoes_cota.isVisibleTo(pj)
    assert pj.controles.estado == "pausado" and "cota" in pj.controles.lbl_estado.text()
    assert w.barra.lbl.text() == "1 processo(s) ativo(s)" and w.barra.btn_continuar.isEnabled()
    visto = []
    pj._start = lambda *a, **k: visto.append((a, k))
    pj.status.btn_cota_continuar.click()
    assert not pj.timer_retomar.isActive()
    assert visto == [(("run", False, None), {"refazer_falhas": False})]
    # de novo em pausa da cota: Parar cancela a retomada automática
    pj._on_retomar_em(quando)
    pj._on_terminou("pausado")
    pj.status.btn_cota_parar.click()
    assert not pj.timer_retomar.isActive()
    assert not pj.status.banner_pausa.isVisibleTo(pj)
    assert not pj.status.acoes_cota.isVisibleTo(pj)
    assert pj.controles.estado == "parado" and not pj.rodando
    assert w.barra.lbl.text() == "Nenhum processo ativo"


def test_trilhas_tem_controles(qtbot, settings_tmp, monkeypatch):
    from roteiro_ia import music_index
    from roteiro_ia.ui.abas import TrilhasTab
    from roteiro_ia.ui.worker import Runner
    liberar = threading.Event()

    def fake_update(s, idx, on_progress=None, **k):
        n = 0
        while not liberar.is_set():
            try:
                controle.atual().checkpoint()
            except Interrompido:
                return n
            n += 1
            liberar.wait(0.05)
        return n
    monkeypatch.setattr(music_index, "update_index", fake_update)
    runner = Runner()
    aba = TrilhasTab(settings_tmp, runner)
    qtbot.addWidget(aba)
    ctl = aba.controles
    assert aba.btn is ctl.btn_play
    aba.btn.click()
    qtbot.waitUntil(lambda: ctl.estado == "rodando", timeout=3000)
    assert ctl.btn_parar.isEnabled()
    ctl.btn_parar.click()
    qtbot.waitUntil(lambda: ctl.estado == "parado", timeout=5000)
    assert "Parado" in aba.lbl_atual.text()
    liberar.set()
    runner.wait_all(5000)


def test_estilo_tem_controles(qtbot, settings_tmp, tmp_path, monkeypatch):
    from roteiro_ia.ui.abas import EstiloTab
    from roteiro_ia.ui.worker import Runner
    settings_tmp.style_urls = ["https://www.youtube.com/watch?v=AAAAAAAAAAA"]
    runner = Runner()
    aba = EstiloTab(settings_tmp, tmp_path / "SISTEMA" / "config.json", runner)
    qtbot.addWidget(aba)
    assert aba.btn_gerar is aba.controles.btn_play
    assert aba.btn_gerar.isEnabled() and not aba.controles.btn_parar.isEnabled()


def test_fechar_para_tudo_e_espera(qtbot, janela_longa):
    from PySide6.QtGui import QCloseEvent
    w, liberar, _ = janela_longa
    w.projeto.btn_iniciar.click()
    qtbot.waitUntil(lambda: w.runner.n_ativos() == 1, timeout=3000)
    e = QCloseEvent()
    w.closeEvent(e)  # o conftest responde "Sim" à confirmação
    assert e.isAccepted()
    assert not w.runner.ativo() and not w.sair_com_tarefas  # parou a tempo: saída normal
