"""Coluna da direita da aba Projeto: etapas, mensagem atual, avisos, log e ações finais."""
from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from roteiro_ia.ui.textos import PREMIERE_INSTRUCAO
from roteiro_ia.ui.widgets import Banner, Card, StageList

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
        self.painel_final.hide()
