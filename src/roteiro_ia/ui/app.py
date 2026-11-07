"""Janela principal do Roteiro IA (`roteiro-ia-janela`)."""
from __future__ import annotations

import os
import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QTabWidget

from roteiro_ia import proc
from roteiro_ia.config import DEFAULT_CONFIG_PATH, Settings, load_settings
from roteiro_ia.ui.abas import ConfigTab, EstiloTab, TrilhasTab
from roteiro_ia.ui.projeto import PipelineFactory, ProjetoTab
from roteiro_ia.ui.widgets import BarraGeral
from roteiro_ia.ui.worker import Runner

WAIT_ON_EXIT_MS = 10_000  # Parar tudo ao fechar: espera até 10 s antes de sair


def load_theme() -> str:
    """QSS do pacote, com {ICONES} trocado pela pasta dos ícones SVG (url() precisa de caminho)."""
    base = files("roteiro_ia.ui")
    icones = str(base.joinpath("icones")).replace("\\", "/")
    return base.joinpath("tema.qss").read_text(encoding="utf-8").replace("{ICONES}", icones)


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


class MainWindow(QMainWindow):
    def __init__(self, s: Settings, settings_path: Path, factory: PipelineFactory | None = None):
        super().__init__()
        self.s = s
        self.setWindowTitle("Roteiro IA — Fokuss")
        self.setMinimumSize(1100, 720)
        self.resize(1280, 860)
        self.runner = Runner(self)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.projeto = ProjetoTab(s, settings_path, self.runner, factory)
        self.trilhas = TrilhasTab(s, self.runner)
        self.estilo = EstiloTab(s, settings_path, self.runner)
        self.config = ConfigTab(s, settings_path, ao_salvar=self._config_salva)
        self.tabs.addTab(self.projeto, "Projeto")
        self.tabs.addTab(self.trilhas, "Trilhas")
        self.tabs.addTab(self.estilo, "Estilo")
        self.tabs.addTab(self.config, "Configurações")
        # barra geral no canto das abas: age em todos os processos ativos
        self.barra = BarraGeral()
        self.tabs.setCornerWidget(self.barra, Qt.TopRightCorner)
        self.barra.pausar.connect(self.pausar_tudo)
        self.barra.continuar.connect(self.continuar_tudo)
        self.barra.parar.connect(self.parar_tudo)
        self.runner.mudou.connect(self._atualizar_barra)
        self.projeto.mudou.connect(self._atualizar_barra)
        self.setCentralWidget(self.tabs)
        self.sair_com_tarefas = False
        self._atualizar_barra()

    # ------------------------------------------------------------ barra geral
    def _atualizar_barra(self) -> None:
        cs = self.runner.controles()
        cota = self.projeto.em_pausa_cota()
        est = [c.estado for c in cs]
        self.barra.atualizar(
            len(cs) + int(cota),
            pode_pausar="rodando" in est,
            pode_continuar=cota or any(e in ("pausando", "pausado") for e in est),
            pode_parar=cota or any(e in ("rodando", "pausando", "pausado") for e in est))

    def pausar_tudo(self) -> None:
        self.runner.pausar_todos()

    def continuar_tudo(self) -> None:
        self.runner.continuar_todos()
        if self.projeto.em_pausa_cota():
            self.projeto.continuar_agora()

    def parar_tudo(self) -> None:
        self.runner.parar_todos()
        if self.projeto.em_pausa_cota():
            self.projeto.cancelar_retomada()

    def _config_salva(self) -> None:
        self.trilhas.textos()
        self.projeto.form.atualizar_preco()
        if not self.projeto.rodando:
            self.projeto.form.combo_disco.setCurrentText(self.s.work_drive)

    def closeEvent(self, e) -> None:
        # runner.ativo(): também tarefas auxiliares (índice de trilhas, estilo, estimativa)
        if self.projeto.rodando or self.projeto.timer_retomar.isActive() or self.runner.ativo():
            r = QMessageBox.question(
                self, "Fechar o Roteiro IA",
                "Há um processamento em andamento. Fechar mesmo assim?\n\nDa próxima vez, use "
                "\"Continuar projeto existente…\" para seguir de onde parou.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                e.ignore()
                return
            # Parar tudo e esperar (até 10 s) para sair sem nada pela metade; o que não parar
            # a tempo é encerrado na saída (o pipeline é retomável)
            self.projeto.timer_retomar.stop()
            self.sair_com_tarefas = not self.runner.parar_e_esperar(WAIT_ON_EXIT_MS)
        super().closeEvent(e)


def main() -> int:
    proc.esconder_consoles()  # sob o pythonw, nenhum subprocesso abre tela preta
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Roteiro IA")
    apply_theme(app)
    cfg = Path(os.environ.get("ROTEIRO_IA_CONFIG", str(DEFAULT_CONFIG_PATH)))
    try:
        s = load_settings(cfg)
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(None, "Roteiro IA", f"Não consegui ler a configuração {cfg}: {e}")
        return 1
    w = MainWindow(s, cfg)
    w.show()
    code = app.exec()
    if w.runner.ativo():
        if w.sair_com_tarefas:
            # o pipeline é retomável: encerra sem esperar a etapa atual terminar
            os._exit(code)
        if not w.runner.wait_all(WAIT_ON_EXIT_MS):
            os._exit(code)  # não trava a saída esperando uma tarefa presa
    return code


if __name__ == "__main__":
    sys.exit(main())
