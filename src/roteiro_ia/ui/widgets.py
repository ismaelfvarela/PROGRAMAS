"""Peças reutilizáveis da janela: cartão, faixa de aviso, lista de etapas e tabela de subpastas."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QProgressBar, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from roteiro_ia.models import FolderAssignment, Role
from roteiro_ia.ui.textos import ROLE_LABELS, STAGE_NAMES, label_to_role, role_label

ICONES = {"feito": "✔", "feito_aviso": "✔", "rodando": "▶", "pausado": "⏸",
          "pendente": "○", "erro": "✖"}


def repolish(w: QWidget) -> None:
    """Reaplica o QSS depois de mudar uma propriedade dinâmica."""
    st = w.style()
    st.unpolish(w)
    st.polish(w)
    w.update()


def set_prop(w: QWidget, name: str, value) -> None:
    if w.property(name) != value:
        w.setProperty(name, value)
        repolish(w)


class Card(QFrame):
    """Cartão com título (e número do passo, se houver); o conteúdo vai em `body`."""

    def __init__(self, titulo: str, numero: int | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        if numero is not None:
            n = QLabel(str(numero))
            n.setObjectName("numeroPasso")
            head.addWidget(n)
        t = QLabel(titulo)
        t.setObjectName("tituloCard")
        head.addWidget(t)
        head.addStretch(1)
        self.head = head
        lay.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        lay.addLayout(self.body)


class Banner(QLabel):
    """Faixa colorida: tipo "erro", "pausa" ou "ok". Some quando vazia."""

    def __init__(self, tipo: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.setProperty("tipo", tipo)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hide()

    def mostrar(self, texto: str) -> None:
        self.setText(texto)
        self.setVisible(bool(texto))

    def limpar(self) -> None:
        self.mostrar("")


class StageRow(QWidget):
    def __init__(self, nome: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("linhaEtapa")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 8, 3)
        lay.setSpacing(10)
        self.icone = QLabel()
        self.icone.setObjectName("iconeEtapa")
        self.nome = QLabel(nome)
        self.nome.setObjectName("nomeEtapa")
        self.detalhe = QLabel()
        self.detalhe.setObjectName("detalheEtapa")
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setFixedWidth(150)
        self.barra.setTextVisible(False)
        lay.addWidget(self.icone)
        lay.addWidget(self.nome)
        lay.addStretch(1)
        lay.addWidget(self.detalhe)
        lay.addWidget(self.barra)
        self.estado = ""
        self.set_estado("pendente")

    def set_estado(self, estado: str, detalhe: str = "", frac: float | None = None) -> None:
        self.estado = estado
        self.icone.setText(ICONES[estado])
        for w in (self, self.icone, self.nome):
            set_prop(w, "estado", estado)
        self.detalhe.setText(detalhe)
        rodando = estado == "rodando"
        self.barra.setVisible(rodando)
        if rodando and frac is not None:
            self.barra.setValue(int(max(0.0, min(1.0, frac)) * 1000))
        elif not rodando:
            self.barra.setValue(0)


class StageList(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.rows: dict[str, StageRow] = {}
        for key, nome in STAGE_NAMES.items():
            r = StageRow(nome)
            self.rows[key] = r
            lay.addWidget(r)

    def estado(self, etapa: str) -> str:
        return self.rows[etapa].estado

    def set_estado(self, etapa: str, estado: str, detalhe: str = "",
                   frac: float | None = None) -> None:
        if etapa in self.rows:
            self.rows[etapa].set_estado(estado, detalhe, frac)

    def reset(self) -> None:
        for r in self.rows.values():
            r.set_estado("pendente")


class SubfolderTable(QTableWidget):
    """Pasta | O que é (papel) | Dia (só para "Outro dia")."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["Pasta", "O que é", "Dia"])
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(36)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.Fixed)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        self.setColumnWidth(1, 220)
        self.setColumnWidth(2, 150)
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def load(self, folders: list[str], roles: dict[str, Role] | None = None,
             dias: dict[str, str] | None = None) -> None:
        from roteiro_ia.inventory import suggest_role
        self.setRowCount(0)
        for f in folders:
            row = self.rowCount()
            self.insertRow(row)
            it = QTableWidgetItem(f)
            it.setFlags(Qt.ItemIsEnabled)
            self.setItem(row, 0, it)
            combo = QComboBox()
            combo.addItems(list(ROLE_LABELS.values()))
            dia = QLineEdit()
            self.setCellWidget(row, 1, combo)
            self.setCellWidget(row, 2, dia)
            combo.currentTextChanged.connect(lambda _t, r=row: self._sync_dia(r))
            role = (roles or {}).get(f) or suggest_role(f)
            if dias and f in dias and role == Role.outro_dia:
                dia.setText(dias[f])
            self.set_role(row, role)
            self._sync_dia(row)

    def row_of(self, folder: str) -> int:
        for r in range(self.rowCount()):
            if self.item(r, 0).text() == folder:
                return r
        raise KeyError(folder)

    def combo(self, row: int) -> QComboBox:
        return self.cellWidget(row, 1)

    def dia_edit(self, row: int) -> QLineEdit:
        return self.cellWidget(row, 2)

    def set_role(self, row: int, role: Role) -> None:
        self.combo(row).setCurrentText(role_label(role))

    def _sync_dia(self, row: int) -> None:
        on = label_to_role(self.combo(row).currentText()) == Role.outro_dia
        dia = self.dia_edit(row)
        dia.setEnabled(on)
        dia.setPlaceholderText(self.item(row, 0).text() if on else "")

    def assignments(self) -> list[FolderAssignment]:
        out = []
        for r in range(self.rowCount()):
            folder = self.item(r, 0).text()
            role = label_to_role(self.combo(r).currentText())
            dia = "principal"
            if role == Role.outro_dia:
                dia = self.dia_edit(r).text().strip() or folder
            out.append(FolderAssignment(folder=folder, role=role, day_label=dia))
        return out
