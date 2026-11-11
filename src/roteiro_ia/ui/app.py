"""Janela principal do Roteiro IA (`roteiro-ia-janela`)."""
from __future__ import annotations

import os
import sys
from importlib.resources import files
from pathlib import Path

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QMainWindow, QMessageBox,
                               QPushButton, QSplashScreen, QStackedWidget, QTabWidget, QVBoxLayout,
                               QWidget)

from roteiro_ia import proc
from roteiro_ia.areas import area_por_id  # as áreas em si só carregam ao usar
from roteiro_ia.config import DEFAULT_CONFIG_PATH, Settings, load_settings

if TYPE_CHECKING:
    from roteiro_ia.ui.abas import EstiloTab
    from roteiro_ia.ui.projeto import PipelineFactory, ProjetoTab

# As abas (e o que elas importam: Gemini, pipeline, scipy...) só são carregadas dentro de
# MainWindow, depois que a trava de instância única e o aviso "Abrindo…" já apareceram.

WAIT_ON_EXIT_MS = 10_000  # Parar tudo ao fechar: espera até 10 s antes de sair


def load_theme() -> str:
    """QSS do pacote, com {ICONES} trocado pela pasta dos ícones SVG (url() precisa de caminho)."""
    base = files("roteiro_ia.ui")
    icones = str(base.joinpath("icones")).replace("\\", "/")
    return base.joinpath("tema.qss").read_text(encoding="utf-8").replace("{ICONES}", icones)


APP_ID = "Fokuss.RoteiroIA"  # o Windows agrupa a barra de tarefas por este id, não pelo pythonw


def icone_app() -> QIcon:
    """Ícone do programa (robô com o emblema da Fokuss), em todos os tamanhos do .ico."""
    return QIcon(str(files("roteiro_ia.ui").joinpath("icones", "app.ico")))


def _registrar_app_id() -> None:
    """Sem isto a barra de tarefas mostra o ícone do Python em vez do nosso."""
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    pal = QPalette()  # base escura para o que o QSS não cobre (diálogos do sistema, menus)
    for papel, cor in ((QPalette.Window, "#1b1b1d"), (QPalette.Base, "#1b1b1d"),
                       (QPalette.AlternateBase, "#252528"), (QPalette.Button, "#2f2f33"),
                       (QPalette.WindowText, "#e8e8ea"), (QPalette.Text, "#e8e8ea"),
                       (QPalette.ButtonText, "#e8e8ea"), (QPalette.ToolTipBase, "#252528"),
                       (QPalette.ToolTipText, "#e8e8ea"), (QPalette.PlaceholderText, "#6a6a70"),
                       (QPalette.Highlight, "#d9774a"), (QPalette.HighlightedText, "#ffffff")):
        pal.setColor(papel, QColor(cor))
    app.setPalette(pal)
    app.setStyleSheet(load_theme())


class PaginaArea(QWidget):
    """Página de uma área no seletor: as abas dela, com Projeto e Estilo próprios."""

    def __init__(self, tabs: QTabWidget, projeto: ProjetoTab, estilo: EstiloTab,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.tabs, self.projeto, self.estilo = tabs, projeto, estilo
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(tabs)


class MainWindow(QMainWindow):
    def __init__(self, s: Settings, settings_path: Path, factory: PipelineFactory | None = None):
        from roteiro_ia.areas import AREAS
        from roteiro_ia.ui.abas import ConfigTab, EstiloTab, TrilhasTab
        from roteiro_ia.ui.fila import FilaProjetos
        from roteiro_ia.ui.projeto import ProjetoTab
        from roteiro_ia.ui.widgets import BarraGeral
        from roteiro_ia.ui.worker import Runner
        super().__init__()
        self.s = s
        self.settings_path = Path(settings_path)
        self.setWindowTitle("Roteiro IA — Fokuss")
        # mínimo e tamanho inicial respeitam a área útil da tela (notebook com zoom do Windows:
        # uma janela maior que a tela corta a lateral direita e a parte de baixo)
        tela = self.screen().availableGeometry() if self.screen() is not None else None
        larg, alt = (tela.width(), tela.height()) if tela is not None else (1280, 860)
        self.setMinimumSize(min(1100, larg), min(720, alt))
        self.resize(min(1280, larg), min(860, alt))
        self.runner = Runner(self)
        self.fila = FilaProjetos(self)  # um projeto por vez, de qualquer área
        # Trilhas e Configurações são únicas: mudam de abas junto com a área à vista
        self.trilhas = TrilhasTab(s, self.runner)
        self.config = ConfigTab(s, settings_path, ao_salvar=self._config_salva)

        # faixa do seletor: um botão por área e, à direita, a barra geral
        faixa = QWidget()
        faixa.setObjectName("faixaAreas")
        lay_faixa = QHBoxLayout(faixa)
        lay_faixa.setContentsMargins(12, 8, 0, 0)
        lay_faixa.setSpacing(6)
        self.stack = QStackedWidget()
        self.areas: dict[str, PaginaArea] = {}
        self.botoes_area: dict[str, QPushButton] = {}
        grupo = QButtonGroup(self)
        for area in AREAS:
            tabs = QTabWidget()
            tabs.setDocumentMode(False)
            projeto = ProjetoTab(s, settings_path, self.runner, factory, area=area.id,
                                 fila=self.fila)
            estilo = EstiloTab(s, settings_path, self.runner, area=area.id)
            tabs.addTab(projeto, "Projeto")
            if area.id == "casamento":
                from roteiro_ia.ui.musicas import MusicasTab
                tabs.addTab(MusicasTab(projeto, s), "Músicas a baixar")
            tabs.addTab(estilo, "Estilo")  # Trilhas e Configurações entram em _trocar_area
            pagina = PaginaArea(tabs, projeto, estilo)
            self.areas[area.id] = pagina
            self.stack.addWidget(pagina)
            projeto.mudou.connect(self._atualizar_barra)
            b = QPushButton(area.nome)
            b.setObjectName("area")
            b.setProperty("nome", area.nome)  # o texto ganha " •" quando a área está ocupada
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=area.id: self.mostrar_area(i))
            grupo.addButton(b)
            self.botoes_area[area.id] = b
            lay_faixa.addWidget(b)
        lay_faixa.addStretch(1)
        # barra geral: age em todos os processos ativos, de todas as áreas
        self.barra = BarraGeral()
        lay_faixa.addWidget(self.barra)
        self.barra.pausar.connect(self.pausar_tudo)
        self.barra.continuar.connect(self.continuar_tudo)
        self.barra.parar.connect(self.parar_tudo)
        self.runner.mudou.connect(self._atualizar_barra)
        self.fila.mudou.connect(self._atualizar_barra)

        casamento = self.areas["casamento"]  # os atributos de sempre são os do Casamento
        self.tabs, self.projeto, self.estilo = casamento.tabs, casamento.projeto, casamento.estilo

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(faixa)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.sair_com_tarefas = False
        self._area = ""
        self._trocar_area(s.area_atual)  # abre na última área usada
        self._atualizar_barra()

    # ------------------------------------------------------------ áreas
    def projetos(self) -> list[ProjetoTab]:
        """As abas Projeto de todas as áreas."""
        return [p.projeto for p in self.areas.values()]

    def mostrar_area(self, id: str) -> None:
        """Troca a área à vista e grava a escolha nas configurações."""
        from roteiro_ia.ui.abas import _salvar
        self._trocar_area(id)
        self.s.area_atual = self._area
        err = _salvar(self.s, self.settings_path)
        if err:
            self.statusBar().showMessage(f"Não consegui salvar a área escolhida: {err}", 10_000)

    def _trocar_area(self, id: str) -> None:
        id = area_por_id(id).id  # id desconhecido cai no Casamento
        pagina = self.areas[id]
        if id != self._area:
            # Trilhas e Configurações saem das abas da área anterior e vão para as da nova:
            # Trilhas logo depois de Projeto, Configurações sempre por último
            for w, pos, nome in ((self.trilhas, 1, "Trilhas"), (self.config, None, "Configurações")):
                for p in self.areas.values():
                    i = p.tabs.indexOf(w)
                    if i >= 0:
                        p.tabs.removeTab(i)
                pagina.tabs.insertTab(pagina.tabs.count() if pos is None else pos, w, nome)
            self._area = id
        self.stack.setCurrentWidget(pagina)
        self.botoes_area[id].setChecked(True)
        self._marcar_areas()

    def _marcar_areas(self) -> None:
        """Marca " •" na área fora de vista com projeto rodando, em cota ou na fila."""
        na_fila = self.fila.na_fila()
        for id, pagina in self.areas.items():
            pj = pagina.projeto
            ocupada = pj.rodando or pj.em_pausa_cota() or any(c is pj for c in na_fila)
            b = self.botoes_area[id]
            nome = b.property("nome")
            b.setText(f"{nome} •" if ocupada and id != self._area else nome)

    # ------------------------------------------------------------ barra geral
    def _atualizar_barra(self) -> None:
        cs = self.runner.controles()
        cota = sum(pj.em_pausa_cota() for pj in self.projetos())
        est = [c.estado for c in cs]
        self.barra.atualizar(
            len(cs) + cota,
            pode_pausar="rodando" in est,
            pode_continuar=cota > 0 or any(e in ("pausando", "pausado") for e in est),
            pode_parar=cota > 0 or any(e in ("rodando", "pausando", "pausado") for e in est))
        self._marcar_areas()

    def pausar_tudo(self) -> None:
        self.runner.pausar_todos()

    def continuar_tudo(self) -> None:
        # quem a fila suspendeu (outro projeto tem a prioridade) só a fila solta; senão dois
        # projetos rodariam ao mesmo tempo
        presos = [c.controle_execucao() for c in self.fila.suspensos()
                  if hasattr(c, "controle_execucao")]
        for c in self.runner.controles():
            if not any(c is p for p in presos):
                c.continuar()
        for pj in self.projetos():
            if pj.em_pausa_cota():
                pj.continuar_agora()

    def parar_tudo(self) -> None:
        self.runner.parar_todos()
        for pj in self.projetos():
            if pj.em_pausa_cota():
                pj.cancelar_retomada()

    def _config_salva(self) -> None:
        self.trilhas.textos()
        for pj in self.projetos():
            pj.form.atualizar_preco()
            if not pj.rodando:
                pj.form.combo_disco.setCurrentText(self.s.work_drive)

    def closeEvent(self, e) -> None:
        # runner.ativo(): também tarefas auxiliares (índice de trilhas, estilo, estimativa)
        ocupado = any(pj.rodando or pj.timer_retomar.isActive() for pj in self.projetos())
        if ocupado or self.fila.na_fila() or self.runner.ativo():
            texto = ("Há um processamento em andamento. Fechar mesmo assim?\n\nDa próxima vez, use "
                     "\"Continuar projeto existente…\" para seguir de onde parou.")
            if na_fila := self.fila.na_fila():
                texto += "\n\nNa fila: " + ", ".join(c.nome_fila() for c in na_fila) + "."
            r = QMessageBox.question(
                self, "Fechar o Roteiro IA", texto,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                e.ignore()
                return
            # Parar tudo e esperar (até 10 s) para sair sem nada pela metade; o que não parar
            # a tempo é encerrado na saída (o pipeline é retomável)
            for pj in self.projetos():
                pj.timer_retomar.stop()
            self.fila.esvaziar()  # o projeto que parar não passa a vez a quem esperava
            self.sair_com_tarefas = not self.runner.parar_e_esperar(WAIT_ON_EXIT_MS)
        super().closeEvent(e)


def _aviso_abrindo() -> QSplashScreen:
    pix = QPixmap(360, 120)
    pix.fill(QColor("#1b1b1d"))
    sp = QSplashScreen(pix)
    sp.setFont(QFont("Segoe UI", 13))
    sp.showMessage("Roteiro IA\nAbrindo…", Qt.AlignCenter, QColor("#e8e8ea"))
    sp.show()
    QApplication.processEvents()
    return sp


def main() -> int:
    from roteiro_ia.ui.instancia import Servidor, Trava, avisar_primeira, trazer_para_frente
    proc.esconder_consoles()  # sob o pythonw, nenhum subprocesso abre tela preta
    _registrar_app_id()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Roteiro IA")
    app.setWindowIcon(icone_app())
    trava = Trava()
    if not trava.primeira:
        # já está aberto (ou abrindo): só traz a janela existente para frente
        avisar_primeira()
        return 0
    servidor = Servidor()
    apply_theme(app)
    aviso = _aviso_abrindo()
    cfg = Path(os.environ.get("ROTEIRO_IA_CONFIG", str(DEFAULT_CONFIG_PATH)))
    try:
        s = load_settings(cfg)
    except Exception as e:  # noqa: BLE001
        aviso.close()
        QMessageBox.critical(None, "Roteiro IA", f"Não consegui ler a configuração {cfg}: {e}")
        return 1
    w = MainWindow(s, cfg)
    servidor.mostrar.connect(lambda: trazer_para_frente(w))
    w.show()
    aviso.finish(w)
    code = app.exec()
    trava.liberar()
    if w.runner.ativo():
        if w.sair_com_tarefas:
            # o pipeline é retomável: encerra sem esperar a etapa atual terminar
            os._exit(code)
        if not w.runner.wait_all(WAIT_ON_EXIT_MS):
            os._exit(code)  # não trava a saída esperando uma tarefa presa
    return code


if __name__ == "__main__":
    sys.exit(main())
