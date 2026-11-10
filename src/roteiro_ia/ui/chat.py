"""Janela "Roteiro pelo chat": o pedido vai num arquivo (e na área de transferência) para o chat
do site; a resposta colada é conferida com as mesmas regras da API."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from roteiro_ia.script.manual import (CHAT_PADRAO, CHATS, CHATS_PEDIDO_INTEIRO, LIMITE_COLAR,
                                      RespostaInvalida, SemJson, mensagem_do_anexo,
                                      mensagem_so_json)
from roteiro_ia.ui.widgets import Banner

ARQ_PEDIDO = "PEDIDO DO ROTEIRO.txt"


def _abrir_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def _mostrar_no_explorador(arq: Path) -> None:
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(arq)])  # noqa: S603,S607


class RoteiroChatDialog(QDialog):
    def __init__(self, pipe, pasta_analise: Path, roteiro_existe: bool,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.pipe = pipe
        self.pasta = Path(pasta_analise)
        self.sessao = None
        self.setWindowTitle("Roteiro pelo chat")
        self.resize(760, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        topo = QLabel("Sem cota na API? Faça o roteiro no chat do site. O sistema monta o mesmo "
                      "pedido que iria para a API (catálogo das cenas, regras, estilo, suas "
                      "observações e as trilhas) e confere a resposta com as mesmas regras.")
        topo.setWordWrap(True)
        topo.setProperty("muted", True)
        lay.addWidget(topo)

        linha = QHBoxLayout()
        linha.addWidget(QLabel("Chat:"))
        self.combo = QComboBox()
        for i, (cid, (nome, url)) in enumerate(CHATS.items()):
            self.combo.addItem(nome if url else f"{nome} (em breve)", cid)
            if url is None:
                self.combo.model().item(i).setEnabled(False)
        self.combo.setCurrentIndex(list(CHATS).index(CHAT_PADRAO))
        linha.addWidget(self.combo)
        self.chk_compacto = QCheckBox("Versão compacta (sem os trechos fracos)")
        self.chk_compacto.setToolTip("O pedido inteiro de um casamento tem ~200 mil tokens: cabe no "
                                     "Gemini, mas passa do que o chat do Claude e do ChatGPT aceita")
        linha.addWidget(self.chk_compacto)
        linha.addStretch(1)
        self.combo.currentIndexChanged.connect(
            lambda _i: self.chk_compacto.setChecked(self.chat() not in CHATS_PEDIDO_INTEIRO))
        lay.addLayout(linha)
        self.ajuste = QLineEdit()
        self.ajuste.setPlaceholderText("Pedido de ajuste (opcional): muda o roteiro atual em vez de "
                                       "fazer um novo")
        self.ajuste.setEnabled(roteiro_existe)
        lay.addWidget(self.ajuste)

        self.btn_pedido = QPushButton("1. Gerar o pedido e abrir o chat")
        self.btn_pedido.setObjectName("primario")
        lay.addWidget(self.btn_pedido)
        self.lbl_pedido = QLabel()
        self.lbl_pedido.setWordWrap(True)
        lay.addWidget(self.lbl_pedido)

        lay.addWidget(QLabel("2. Cole aqui a resposta inteira do chat:"))
        self.resposta = QPlainTextEdit()
        self.resposta.setPlaceholderText("{ \"arco\": …, \"pecas\": [ … ], \"alertas\": [ … ] }")
        lay.addWidget(self.resposta, 1)
        self.btn_conferir = QPushButton("Conferir a resposta")
        lay.addWidget(self.btn_conferir)
        self.banner_ok = Banner("ok")
        self.banner_erro = Banner("erro")
        lay.addWidget(self.banner_ok)
        lay.addWidget(self.banner_erro)

        fim = QHBoxLayout()
        self.btn_so_json = QPushButton("Pedir só o JSON")
        self.btn_so_json.setToolTip("Copia uma mensagem para o MESMO chat converter em JSON o "
                                    "roteiro que ele escreveu em texto")
        self.btn_so_json.hide()
        self.btn_correcao = QPushButton("Gerar o pedido de correção")
        self.btn_usar = QPushButton("Usar este roteiro")
        self.btn_usar.setObjectName("primario")
        self.btn_fechar = QPushButton("Fechar")
        fim.addWidget(self.btn_so_json)
        fim.addWidget(self.btn_correcao)
        fim.addStretch(1)
        fim.addWidget(self.btn_fechar)
        fim.addWidget(self.btn_usar)
        lay.addLayout(fim)
        self.btn_correcao.setEnabled(False)
        self.btn_usar.setEnabled(False)
        self.btn_conferir.setEnabled(False)

        self.btn_pedido.clicked.connect(self.gerar_pedido)
        self.btn_conferir.clicked.connect(self.conferir)
        self.btn_correcao.clicked.connect(self.gerar_correcao)
        self.btn_so_json.clicked.connect(self.pedir_so_json)
        self.btn_usar.clicked.connect(self.usar)
        self.btn_fechar.clicked.connect(self.reject)

    # ------------------------------------------------------------ passos
    def chat(self) -> str:
        return self.combo.currentData()

    def _entregar(self, texto: str, arq: Path, o_que: str) -> None:
        """Grava o arquivo, copia o texto e abre o chat e a pasta com o arquivo selecionado."""
        self.pasta.mkdir(parents=True, exist_ok=True)
        arq.write_text(texto, encoding="utf-8")
        grande = len(texto) > LIMITE_COLAR
        # grande: anexa o arquivo e cola a mensagem curta que exige o JSON (sem ela, o chat
        # do Gemini respondeu o roteiro em texto corrido)
        QGuiApplication.clipboard().setText(mensagem_do_anexo(arq.name) if grande else texto)
        _nome, url = CHATS[self.chat()]
        if url:
            _abrir_url(url)
        _mostrar_no_explorador(arq)
        self.lbl_pedido.setText(
            f"{o_que} em {arq} ({len(texto) // 1000} mil caracteres). "
            + ("É grande para colar: no chat, ANEXE esse arquivo (clipe de anexar) e COLE a "
               "mensagem que já está copiada (Ctrl+V) — ela pede a resposta só em JSON. Envie."
               if grande else
               "O texto foi copiado: cole no chat (Ctrl+V) e envie."))
        self.btn_so_json.hide()

    def gerar_pedido(self) -> None:
        self.banner_erro.limpar()
        self.banner_ok.limpar()
        try:
            self.sessao = self.pipe.sessao_roteiro_manual(self.ajuste.text().strip() or None,
                                                          compact=self.chk_compacto.isChecked())
            self._entregar(self.sessao.texto_inicial(), self.pasta / ARQ_PEDIDO, "Pedido gravado")
        except Exception as e:  # noqa: BLE001 - mostra na janela
            self.banner_erro.mostrar(f"Não consegui montar o pedido: {e}")
            return
        self.btn_conferir.setEnabled(True)
        self.btn_usar.setEnabled(False)
        self.btn_correcao.setEnabled(False)

    def conferir(self) -> None:
        self.banner_erro.limpar()
        self.banner_ok.limpar()
        if self.sessao is None:
            return
        try:
            probs = self.sessao.conferir(self.resposta.toPlainText())
        except RespostaInvalida as e:
            self.banner_erro.mostrar(str(e))
            self.btn_usar.setEnabled(False)
            self.btn_so_json.setVisible(isinstance(e, SemJson))
            return
        self.btn_so_json.hide()
        n = len(self.sessao.ultimo.pecas)
        if not probs:
            self.banner_ok.mostrar(f"Roteiro conferido: {n} peça(s), tudo certo. Clique em Usar "
                                   "este roteiro para gerar o PDF e o XML.")
            self.btn_usar.setText("Usar este roteiro")
        else:
            lista = "\n".join(f"• {p}" for p in probs[:15])
            mais = f"\n… e mais {len(probs) - 15}" if len(probs) > 15 else ""
            dica = ("Gere o pedido de correção e mande no MESMO chat." if self.sessao.pode_corrigir()
                    else "As rodadas de correção acabaram: use mesmo assim (o que estiver errado "
                         "sai e vira alerta) ou peça de novo.")
            self.banner_erro.mostrar(f"O roteiro tem {len(probs)} problema(s):\n{lista}{mais}\n{dica}")
            self.btn_usar.setText("Usar mesmo assim (o errado sai)")
        self.btn_correcao.setEnabled(self.sessao.pode_corrigir())
        self.btn_usar.setEnabled(True)

    def pedir_so_json(self) -> None:
        QGuiApplication.clipboard().setText(mensagem_so_json())
        self.resposta.clear()
        self.banner_erro.limpar()
        self.banner_ok.mostrar("Mensagem copiada: cole no MESMO chat (Ctrl+V), envie e cole aqui a "
                               "nova resposta.")

    def gerar_correcao(self) -> None:
        if self.sessao is None or not self.sessao.pode_corrigir():
            return
        texto = self.sessao.texto_correcao()
        arq = self.pasta / f"CORREÇÃO DO ROTEIRO {self.sessao.correcoes}.txt"
        self._entregar(texto, arq, f"Correção {self.sessao.correcoes} gravada")
        self.resposta.clear()
        self.btn_correcao.setEnabled(False)
        self.btn_usar.setEnabled(False)

    def usar(self) -> None:
        if self.sessao is None or self.sessao.ultimo is None:
            return
        try:
            self.sessao.aceitar([f"Roteiro feito pelo chat ({CHATS[self.chat()][0]})."])
        except Exception as e:  # noqa: BLE001
            self.banner_erro.mostrar(f"Não consegui gravar o roteiro: {e}")
            return
        self.accept()
