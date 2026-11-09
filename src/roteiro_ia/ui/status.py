"""Coluna da direita da aba Projeto: etapas, mensagem atual, avisos, log e ações finais."""
from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from roteiro_ia.ui.textos import PREMIERE_INSTRUCAO
from roteiro_ia.ui.widgets import (COR_PARAR, COR_PLAY, Banner, Card, ControlesProcesso,
                                  StageList, icone_glifo)

LOG_MAX_LINHAS = 500
_CONTAGEM = re.compile(r"(\d+/\d+)")
FALHAS_PREFIX = "falhas="


class StatusPanel(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        card = Card("Andamento")
        # ⏸/⏹ do processamento; o ▶ aparece só para Continuar (o Iniciar fica no formulário)
        self.controles = ControlesProcesso(so_continuar=True)
        card.head.addWidget(self.controles)
        self.etapas = StageList()
        card.body.addWidget(self.etapas)
        self.lbl_mensagem = QLabel("Escolha a pasta do evento e clique em Iniciar.")
        self.lbl_mensagem.setProperty("muted", True)
        self.lbl_mensagem.setWordWrap(True)
        card.body.addSpacing(4)
        card.body.addWidget(self.lbl_mensagem)
        lay.addWidget(card)

        self.banner_erro = Banner("erro")
        self.banner_pausa = Banner("pausa")
        self.banner_ok = Banner("ok")
        for b in (self.banner_erro, self.banner_pausa, self.banner_ok):
            lay.addWidget(b)
        # pausa da cota do Gemini: dá para tentar já ou cancelar a retomada automática
        self.acoes_cota = QWidget()
        cota = QHBoxLayout(self.acoes_cota)
        cota.setContentsMargins(0, 0, 0, 0)
        cota.setSpacing(8)
        self.btn_cota_continuar = QPushButton("Continuar agora")
        self.btn_cota_continuar.setIcon(icone_glifo("▶", COR_PLAY))
        self.btn_cota_continuar.setToolTip("Tenta já; se a cota ainda estiver esgotada, volta a "
                                           "pausar")
        self.btn_cota_parar = QPushButton("Parar")
        self.btn_cota_parar.setIcon(icone_glifo("⏹", COR_PARAR))
        self.btn_cota_parar.setToolTip("Cancela a retomada automática (continue depois)")
        cota.addWidget(self.btn_cota_continuar)
        cota.addWidget(self.btn_cota_parar)
        cota.addStretch(1)
        self.acoes_cota.hide()
        lay.addWidget(self.acoes_cota)
        # projeto esperando a vez na fila (outro projeto está rodando)
        self.btn_tirar_fila = QPushButton("Tirar da fila")
        self.btn_tirar_fila.setToolTip("Desiste de esperar: o projeto sai da fila e não começa "
                                       "sozinho")
        self.btn_tirar_fila.hide()
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.addWidget(self.btn_tirar_fila)
        fila.addStretch(1)
        lay.addLayout(fila)

        self.painel_final = Card("Pronto")
        acoes = QHBoxLayout()
        acoes.setSpacing(10)
        self.btn_pdf = QPushButton("Abrir PDF")
        self.btn_pdf.setObjectName("primario")
        self.btn_ajuste = QPushButton("Pedir ajuste no roteiro…")
        acoes.addWidget(self.btn_pdf)
        acoes.addWidget(self.btn_ajuste)
        acoes.addStretch(1)
        self.painel_final.body.addLayout(acoes)
        self.lbl_premiere = QLabel(PREMIERE_INSTRUCAO)
        self.lbl_premiere.setProperty("muted", True)
        self.painel_final.body.addWidget(self.lbl_premiere)
        self.painel_final.hide()
        lay.addWidget(self.painel_final)

        log_card = Card("Registro")
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(LOG_MAX_LINHAS)
        self.log.setMinimumHeight(90)
        log_card.body.addWidget(self.log)
        lay.addWidget(log_card, 1)

    # ------------------------------------------------------------ log
    def log_line(self, texto: str) -> None:
        self.log.appendPlainText(f"{datetime.now():%H:%M}  {texto}")

    def on_log(self, texto: str) -> None:
        self.log_line(texto)

    # ------------------------------------------------------------ etapas
    def on_progresso(self, etapa: str, msg: str, frac: float) -> None:
        self.lbl_mensagem.setText(msg)
        tick = 0.0 < frac < 1.0 and _CONTAGEM.search(msg) is not None
        if not tick:
            self.log_line(msg)
        if msg.startswith("Concluído"):
            self.etapas.set_estado(etapa, "feito")
        elif msg.startswith("Cota gratuita"):
            self.etapas.set_estado(etapa, "pausado")
        elif msg.startswith(("A etapa ", "Erro em ")):
            self.etapas.set_estado(etapa, "erro")
        elif msg.startswith("Parado: "):
            self.etapas.set_estado(etapa, "pendente")
        else:
            for k, row in self.etapas.rows.items():
                if k != etapa and row.estado == "rodando":
                    row.set_estado("feito")
            m = _CONTAGEM.search(msg) if tick else None
            self.etapas.set_estado(etapa, "rodando", m.group(1) if m else "", frac)

    def on_estados(self, estados: dict) -> None:
        """Estado real lido do banco (início e fim de cada execução)."""
        for etapa, (status, detalhe) in estados.items():
            if status == "feito" and str(detalhe).startswith(FALHAS_PREFIX):
                n = str(detalhe)[len(FALHAS_PREFIX):]
                self.etapas.set_estado(etapa, "feito_aviso", f"{n} arquivo(s) com problema")
            elif status in ("feito", "pausado", "erro"):
                self.etapas.set_estado(etapa, status)
            else:  # pendente, ou "rodando" de uma execução interrompida
                self.etapas.set_estado(etapa, "pendente")

    def limpar_avisos(self) -> None:
        for b in (self.banner_erro, self.banner_pausa, self.banner_ok):
            b.limpar()
        self.acoes_cota.hide()
        self.painel_final.hide()
