"""Aba Projeto: formulário (esquerda) + andamento (direita) e o controle das execuções."""
from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QDialog, QMenu, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from roteiro_ia import recentes
from roteiro_ia.areas import area_por_id
from roteiro_ia.config import Settings
from roteiro_ia.models import Role
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import PROJECT_FILE, Pipeline, ProjectRequest
from roteiro_ia.ui.status import StatusPanel
from roteiro_ia.ui.worker import PipelineWorker, Runner

# (pedido, settings, eventos) -> objeto com prepare/run/revise/close/resume_at/db
PipelineFactory = Callable[[ProjectRequest, Settings, Callable], object]
MARGEM_RETOMADA_MS = 5_000
TEXTO_PAUSA_COTA = "Pausado pela cota do Gemini — continua sozinho"
TEXTO_PARADO = ("Parado. O que já foi feito está guardado: clique em Continuar para seguir de "
                "onde parou.")


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
    mudou = Signal()  # pausa da cota começou/terminou (a barra geral conta como processo)

    def __init__(self, s: Settings, settings_path: Path, runner: Runner,
                 factory: PipelineFactory | None = None, parent: QWidget | None = None,
                 area: str = "casamento", fila=None):
        super().__init__(parent)
        self.s = s
        self.settings_path = Path(settings_path)
        self.runner = runner
        self.area = area
        self.fila = fila
        self._factory = factory or self._pipeline_padrao
        self._req: ProjectRequest | None = None
        self._custo = 0.0
        self._resume_at: datetime | None = None
        self._ultima: tuple[str, bool, str | None] = ("run", False, None)
        self._continuar_com: tuple[str, bool, str | None] | None = None  # depois de um Parar
        self._worker: PipelineWorker | None = None
        self.rodando = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        self.form = area_por_id(area).formulario(s, runner, area=area)
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
        self.controles = self.status.controles
        self.controles.pausar.connect(self.pausar)
        self.controles.parar.connect(self.parar)
        self.controles.continuar.connect(self.continuar)
        self.status.btn_cota_continuar.clicked.connect(self.continuar_agora)
        self.status.btn_cota_parar.clicked.connect(self.cancelar_retomada)

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
        recentes.registrar(self.s, req.source_dir, req.work_drive, area=self.area)
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
        self._continuar_com = (acao, aprovado, pedido)
        w = PipelineWorker(lambda eventos: factory(req, s, eventos), acao=acao,
                           aprovado_custo=aprovado, pedido=pedido, refazer_falhas=refazer_falhas)
        w.progresso.connect(self.status.on_progresso)
        w.estados.connect(self.status.on_estados)
        w.log.connect(self.status.on_log)
        w.custo.connect(self._on_custo)
        w.retomar_em.connect(self._on_retomar_em)
        w.erro.connect(self._on_erro)
        w.terminou.connect(self._on_terminou)
        w.estado.connect(self._on_estado)
        self._worker = w
        self._set_rodando(True)
        self.status.banner_pausa.limpar()
        self.status.banner_erro.limpar()
        self.status.acoes_cota.hide()
        self.controles.set_estado("rodando")
        self.runner.start(w)
        self.mudou.emit()

    def _set_rodando(self, on: bool) -> None:
        self.rodando = on
        self.form.set_rodando(on)
        self.status.btn_ajuste.setEnabled(not on)

    # ------------------------------------------------------------ Play / Pause / Stop
    def em_pausa_cota(self) -> bool:
        return self.timer_retomar.isActive()

    def _on_estado(self, estado: str) -> None:
        if self.sender() is not self._worker:
            return  # aviso atrasado de uma execução anterior
        if estado in ("rodando", "pausando", "pausado", "parando"):
            self.controles.set_estado(estado)

    def pausar(self) -> None:
        if self._worker is not None:
            self._worker.controle.pausar()

    def parar(self) -> None:
        if self._worker is not None:
            self._worker.controle.parar()
        elif self.em_pausa_cota():
            self.cancelar_retomada()

    def continuar(self) -> None:
        """▶ Continuar: solta a pausa; na pausa da cota tenta já; depois de um Parar roda de
        novo a mesma ação (o pipeline retoma pelo banco, sem refazer o que foi gravado)."""
        if self._worker is not None:
            self._worker.controle.continuar()
        elif self.em_pausa_cota():
            self.continuar_agora()
        elif self._req is not None and self._continuar_com is not None:
            self.status.limpar_avisos()
            self.status.log_line("Continuando de onde parou.")
            acao, aprovado, pedido = self._continuar_com
            self._start(acao, aprovado, pedido)

    def continuar_agora(self) -> None:
        """Pausa da cota: tenta já (se a cota ainda estiver esgotada, volta a pausar)."""
        self.timer_retomar.stop()
        self.status.acoes_cota.hide()
        self.status.banner_pausa.limpar()
        self._retomar()
        self.mudou.emit()

    def cancelar_retomada(self) -> None:
        """Pausa da cota: Parar cancela a retomada automática."""
        self.timer_retomar.stop()
        self.status.acoes_cota.hide()
        self.status.banner_pausa.limpar()
        self._set_rodando(False)
        self.controles.set_estado("parado")
        self.status.lbl_mensagem.setText(TEXTO_PARADO)
        self.status.log_line("Retomada automática cancelada pelo editor.")
        self.mudou.emit()

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
        if self.sender() is not None and self.sender() is not self._worker:
            return
        self._worker = None
        if status == "parado":
            self._set_rodando(False)
            self.controles.set_estado("parado")
            self.status.lbl_mensagem.setText(TEXTO_PARADO)
            self.status.log_line("Parado pelo editor.")
            self.mudou.emit()
            return
        self.controles.set_estado("ocioso")
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
        self.status.acoes_cota.show()
        self.controles.set_estado("pausado", TEXTO_PAUSA_COTA)
        self.status.lbl_mensagem.setText(texto)
        self.status.log_line(texto)
        ms = int((local - datetime.now().astimezone()).total_seconds() * 1000)
        self.timer_retomar.start(max(1000, ms + MARGEM_RETOMADA_MS))
        # o formulário segue travado: a retomada usa o mesmo pedido
        self.form.set_rodando(True)
        self.status.btn_ajuste.setEnabled(False)
        self.mudou.emit()

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

    def menu_recentes(self) -> QMenu:
        """Lista suspensa: projetos abertos por último primeiro, com a última alteração."""
        menu = QMenu(self)
        discos = [self.form.combo_disco.currentText().strip(), self.s.work_drive]
        itens = recentes.listar(self.s, discos, area=self.area)
        if not itens:
            menu.addAction("Nenhum projeto recente").setEnabled(False)
        for r in itens:
            a = menu.addAction(f"{r.nome}	alterado {recentes.quando_texto(r.alterado_em)}")
            a.setToolTip(str(r.pasta))
            a.triggered.connect(lambda _=False, r=r: self.abrir_recente(r))
        menu.setToolTipsVisible(True)
        menu.addSeparator()
        menu.addAction("Outra pasta…").triggered.connect(self.continuar_outra_pasta)
        return menu

    def continuar_existente(self) -> None:
        if self.rodando:
            return
        b = self.form.btn_continuar
        self.menu_recentes().exec(b.mapToGlobal(b.rect().bottomLeft()))

    def abrir_recente(self, r: recentes.Recente) -> bool:
        if self.rodando:
            return False
        self.form.combo_disco.setCurrentText(r.disco)
        if not self.form.set_event_folder(r.pasta):
            self.status.banner_erro.mostrar(
                f"Não consegui abrir a pasta do evento {r.pasta}. O disco de origem está conectado?")
            return False
        return self.abrir_existente(r.pasta)

    def continuar_outra_pasta(self) -> None:
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
                if req.area != self.area:
                    nome = area_por_id(req.area).nome
                    self.status.banner_erro.mostrar(
                        f"Este projeto é de {nome}. Abra pela área {nome}.")
                    return False
                self.form.load_request(req)
                self.iniciar()
                return True
        self.status.banner_erro.mostrar(
            "Não encontrei um projeto deste evento no disco de trabalho. Confira o disco "
            "ou comece com Iniciar.")
        return False
