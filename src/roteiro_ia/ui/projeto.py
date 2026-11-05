"""Aba Projeto: formulário (esquerda) + andamento (direita) e o controle das execuções."""
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from roteiro_ia.config import Settings
from roteiro_ia.models import Role
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import PROJECT_FILE, Pipeline, ProjectRequest
from roteiro_ia.ui.formulario import FormularioEvento
from roteiro_ia.ui.status import StatusPanel
from roteiro_ia.ui.worker import PipelineWorker, Runner

# (pedido, settings, eventos) -> objeto com prepare/run/revise/close/resume_at/db
PipelineFactory = Callable[[ProjectRequest, Settings, Callable], object]
MARGEM_RETOMADA_MS = 5_000


def fmt_usd(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class AjusteDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Pedir ajuste no roteiro")
        self.resize(560, 320)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        lay.addWidget(QLabel("O que você quer mudar? Escreva como pediria a um colega."))
        self.texto = QPlainTextEdit()
        self.texto.setPlaceholderText("Ex.: usar mais os votos no episódio 2 e começar o trailer "
                                      "com o drone da igreja.")
        lay.addWidget(self.texto, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Gerar de novo")
        bb.button(QDialogButtonBox.Ok).setObjectName("primario")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def pedido(self) -> str:
        return self.texto.toPlainText().strip()


class ProjetoTab(QWidget):
    def __init__(self, s: Settings, settings_path: Path, runner: Runner,
                 factory: PipelineFactory | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.s = s
        self.settings_path = Path(settings_path)
        self.runner = runner
        self._factory = factory or self._pipeline_padrao
        self._req: ProjectRequest | None = None
        self._custo = 0.0
        self._resume_at: datetime | None = None
        self._ultima: tuple[str, bool, str | None] = ("run", False, None)
        self.rodando = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        self.form = FormularioEvento(s, runner)
        self.status = StatusPanel()
        lay.addWidget(self.form, 55)
        lay.addWidget(self.status, 45)

        self.timer_retomar = QTimer(self)
        self.timer_retomar.setSingleShot(True)
        self.timer_retomar.timeout.connect(self._retomar)

        self.form.iniciar.connect(self.iniciar)
        self.form.continuar.connect(self.continuar_existente)
        self.status.btn_pdf.clicked.connect(self.abrir_pdf)
        self.status.btn_ajuste.clicked.connect(self.pedir_ajuste)

    # atalhos usados pela janela e pelos testes
    @property
    def btn_iniciar(self):
        return self.form.btn_iniciar

    def set_event_folder(self, path: Path) -> bool:
        return self.form.set_event_folder(path)

    def _pipeline_padrao(self, req: ProjectRequest, s: Settings, eventos) -> Pipeline:
        return Pipeline(req, s, None, None, eventos, settings_path=self.settings_path)

    # ------------------------------------------------------------ execução
    def iniciar(self) -> None:
        if self.rodando:
            return
        try:
            req = self.form.build_request()
        except ValueError as e:
            self.status.banner_erro.mostrar(str(e))
            return
        if all(a.role == Role.ignorar for a in req.assignments):
            self.status.banner_erro.mostrar("Marque pelo menos uma pasta com mídia (todas estão "
                                            "como \"Ignorar\").")
            return
        self._req = req
        self.timer_retomar.stop()
        self.status.limpar_avisos()
        self.status.etapas.reset()
        self.status.log_line(f"Evento: {req.source_dir}")
        self._start("prepare" if req.gemini_mode == "pago" else "run")

    def _start(self, acao: str, aprovado: bool = False, pedido: str | None = None,
               refazer_falhas: bool = True) -> None:
        req, s, factory = self._req, self.s, self._factory
        if acao != "prepare":
            self._ultima = (acao, aprovado, pedido)
        w = PipelineWorker(lambda eventos: factory(req, s, eventos), acao=acao,
                           aprovado_custo=aprovado, pedido=pedido, refazer_falhas=refazer_falhas)
        w.progresso.connect(self.status.on_progresso)
        w.estados.connect(self.status.on_estados)
        w.log.connect(self.status.on_log)
        w.custo.connect(self._on_custo)
        w.retomar_em.connect(self._on_retomar_em)
        w.erro.connect(self._on_erro)
        w.terminou.connect(self._on_terminou)
        self._set_rodando(True)
        self.status.banner_pausa.limpar()
        self.status.banner_erro.limpar()
        self.runner.start(w)

    def _set_rodando(self, on: bool) -> None:
        self.rodando = on
        self.form.set_rodando(on)
        self.status.btn_ajuste.setEnabled(not on)

    def _on_custo(self, custo: float) -> None:
        self._custo = custo

    def _on_retomar_em(self, quando) -> None:
        self._resume_at = quando

    def _on_erro(self, msg: str) -> None:
        self.status.banner_erro.mostrar(msg)
        self.status.log_line(f"Erro: {msg}")

    def confirmar_custo(self, custo: float) -> bool:
        r = QMessageBox.question(self, "Modo pago do Gemini",
                                 f"Custo estimado: US$ {fmt_usd(custo)}. Continuar?",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes

    def _on_terminou(self, status: str) -> None:
        if status == "preparado":
            self._set_rodando(False)
            if self.confirmar_custo(self._custo):
                self._start("run", aprovado=True)
            else:
                self.status.lbl_mensagem.setText("Cancelado. Nada foi enviado ao Gemini.")
                self.status.log_line("Cancelado pelo editor antes do envio ao Gemini.")
            return
        if status == "pausado":
            self._agendar_retomada()
            return
        self._set_rodando(False)
        if status in ("concluido", "ajustado"):
            msg = ("Roteiro ajustado: PDF e XML do Premiere atualizados." if status == "ajustado"
                   else "Pronto! O PDF do roteiro e o XML do Premiere foram gerados.")
            self.status.banner_ok.mostrar(msg)
            self.status.lbl_mensagem.setText(msg)
            self.status.painel_final.show()
        elif status == "erro":
            self.status.lbl_mensagem.setText("O processamento parou. Corrija o problema e clique "
                                             "em Iniciar para continuar de onde parou.")

    def _agendar_retomada(self) -> None:
        quando = self._resume_at
        if quando is None:
            self._set_rodando(False)
            return
        local = quando.astimezone()
        hora = f"{local:%H:%M}"
        if local.date() != datetime.now().date():
            hora += f" de {local:%d/%m}"
        texto = f"Limite gratuito atingido. Continua automaticamente às {hora}."
        self.status.banner_pausa.mostrar(texto)
        self.status.lbl_mensagem.setText(texto)
        self.status.log_line(texto)
        ms = int((local - datetime.now().astimezone()).total_seconds() * 1000)
        self.timer_retomar.start(max(1000, ms + MARGEM_RETOMADA_MS))
        # o formulário segue travado: a retomada usa o mesmo pedido
        self.form.set_rodando(True)
        self.status.btn_ajuste.setEnabled(False)

    def _retomar(self) -> None:
        if self._req is None:
            return
        acao, aprovado, pedido = self._ultima
        self.status.log_line("Retomando após o limite gratuito do Gemini.")
        # retomada automática: não refaz etapas que já terminaram com falhas por arquivo
        self._start(acao, aprovado, pedido, refazer_falhas=False)

    # ------------------------------------------------------------ ações finais
    def _paths(self):
        req = self._req or self.form.build_request()
        return build_event_paths(req.source_dir, self.s, req.work_drive)

    def abrir_pdf(self) -> None:
        try:
            pdf = self._paths().pdf_path
        except ValueError as e:
            self.status.banner_erro.mostrar(str(e))
            return
        if not Path(pdf).is_file():
            self.status.banner_erro.mostrar(f"O PDF ainda não existe: {pdf}")
            return
        os.startfile(str(pdf))  # noqa: S606 - abre no leitor padrão do Windows

    def pedir_ajuste(self) -> None:
        if self._req is None or self.rodando:
            return
        dlg = AjusteDialog(self)
        if dlg.exec() != QDialog.Accepted or not dlg.pedido():
            return
        if self._req.gemini_mode == "pago" and QMessageBox.question(
                self, "Modo pago do Gemini", "O ajuste usa o Gemini no modo pago. Continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.status.limpar_avisos()
        self.status.log_line(f"Pedido de ajuste: {dlg.pedido()}")
        self._start("revise", aprovado=True, pedido=dlg.pedido())

    def continuar_existente(self) -> None:
        if self.rodando:
            return
        pasta = self.form.escolher_pasta("Escolha a pasta do evento (no R:) para continuar")
        if pasta is None or not self.form.set_event_folder(pasta):
            return
        self.abrir_existente(pasta)

    def abrir_existente(self, pasta: Path) -> bool:
        """Carrega ANALISE\\projeto.json (disco escolhido ou o padrão) e retoma o processamento."""
        discos = dict.fromkeys([self.form.combo_disco.currentText().strip(), self.s.work_drive])
        for disco in discos:
            f = Path(build_event_paths(pasta, self.s, disco).analysis_dir) / PROJECT_FILE
            if f.is_file():
                try:
                    req = ProjectRequest.load(f)
                except (OSError, ValueError, KeyError) as e:
                    self.status.banner_erro.mostrar(f"Não consegui ler {f}: {e}")
                    return False
                self.form.load_request(req)
                self.iniciar()
                return True
        self.status.banner_erro.mostrar(
            "Não encontrei um projeto deste evento no disco de trabalho. Confira o disco "
            "ou comece com Iniciar.")
        return False
