"""Janela das observações do editor (perfil do casal, não pode faltar, evitar e músicas)."""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from roteiro_ia.observacoes import Observacoes


def _caixa(dica: str, altura: int = 64) -> QPlainTextEdit:
    c = QPlainTextEdit()
    c.setPlaceholderText(dica)
    c.setMinimumHeight(altura)
    c.setTabChangesFocus(True)
    return c


class ObservacoesDialog(QDialog):
    def __init__(self, o: Observacoes, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Observações do editor")
        self.resize(640, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        topo = QLabel("A IA segue estas observações com prioridade em todo roteiro deste evento "
                      "(o primeiro, os refeitos e os ajustes). Escreva como explicaria a um colega; "
                      "pode deixar campos em branco.")
        topo.setWordWrap(True)
        topo.setProperty("muted", True)
        lay.addWidget(topo)
        form = QFormLayout()
        form.setSpacing(8)
        self.perfil = _caixa("Ex.: casal discreto e elegante, nada de piadas; tom emotivo, "
                             "valorizar a família da noiva.")
        self.obrigatorio = _caixa("Ex.: discurso do pai da noiva; a avó na entrada; o cachorro "
                                  "levando as alianças.")
        self.evitar = _caixa("Ex.: o tio de camisa vermelha; tomadas tremidas da pista.")
        self.musicas = _caixa("Estilo e nomes de músicas, um por linha. Ex.: pop acústico; "
                              "\"Perfect - Ed Sheeran\"; \"Trem-Bala - Ana Vilela\".", 80)
        self.pasta = QLineEdit()
        self.pasta.setPlaceholderText("Pasta com as músicas do casal (opcional)")
        self.btn_pasta = QPushButton("Escolher…")
        linha = QHBoxLayout()
        linha.setSpacing(8)
        linha.addWidget(self.pasta, 1)
        linha.addWidget(self.btn_pasta)
        self.link = QLineEdit()
        self.link.setPlaceholderText("Link da playlist (Spotify, YouTube…)")
        form.addRow("Perfil do casal / estilo do vídeo", self.perfil)
        form.addRow("Não pode faltar", self.obrigatorio)
        form.addRow("Evitar", self.evitar)
        form.addRow("Músicas", self.musicas)
        form.addRow("Pasta de músicas do casal", linha)
        form.addRow("Playlist", self.link)
        lay.addLayout(form, 1)
        nota = QLabel("Músicas da pasta do casal e as que você nomear e estiverem na biblioteca "
                      "vão para a IA marcadas como preferidas. A IA não abre links: a playlist "
                      "fica no PDF para o editor.")
        nota.setWordWrap(True)
        nota.setProperty("muted", True)
        lay.addWidget(nota)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Salvar")
        bb.button(QDialogButtonBox.Ok).setObjectName("primario")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.btn_pasta.clicked.connect(self._escolher_pasta)
        self.set_observacoes(o)

    def _escolher_pasta(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta com as músicas do casal",
                                             self.pasta.text().strip())
        if d:
            self.pasta.setText(d.replace("/", "\\"))

    def set_observacoes(self, o: Observacoes) -> None:
        self.perfil.setPlainText(o.perfil)
        self.obrigatorio.setPlainText(o.obrigatorio)
        self.evitar.setPlainText(o.evitar)
        self.musicas.setPlainText(o.musicas)
        self.pasta.setText(o.musicas_pasta)
        self.link.setText(o.musicas_link)

    def observacoes(self) -> Observacoes:
        return Observacoes(perfil=self.perfil.toPlainText().strip(),
                           obrigatorio=self.obrigatorio.toPlainText().strip(),
                           evitar=self.evitar.toPlainText().strip(),
                           musicas=self.musicas.toPlainText().strip(),
                           musicas_pasta=self.pasta.text().strip(),
                           musicas_link=self.link.text().strip())
