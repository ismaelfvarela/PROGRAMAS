"""Peças reutilizáveis da janela: cartão, faixa de aviso, lista de etapas e tabela de subpastas."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

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


# ---------------------------------------------------------------- Play / Pause / Stop
COR_PLAY, COR_PAUSA, COR_PARAR = "#5fb37c", "#e0b04f", "#e06a5f"
_CACHE_GLIFOS: dict[tuple[str, str], QIcon] = {}


def icone_glifo(glifo: str, cor: str) -> QIcon:
    """Ícone colorido ▶ ⏸ ⏹ (desenhado em formas: não depende da fonte); apagado quando o
    botão está desabilitado. Outro glifo qualquer é desenhado como texto."""
    chave = (glifo, cor)
    if chave not in _CACHE_GLIFOS:
        ic = QIcon()
        for modo, c in ((QIcon.Normal, cor), (QIcon.Disabled, "#55555a")):
            pm = QPixmap(32, 32)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c))
            if glifo == "▶":
                p.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(27, 16), QPointF(8, 27)]))
            elif glifo == "⏸":
                p.drawRoundedRect(QRectF(7, 6, 7, 20), 1.5, 1.5)
                p.drawRoundedRect(QRectF(18, 6, 7, 20), 1.5, 1.5)
            elif glifo == "⏹":
                p.drawRoundedRect(QRectF(7, 7, 18, 18), 2.5, 2.5)
            else:
                f = QFont("Segoe UI Symbol", 17)
                f.setBold(True)
                p.setFont(f)
                p.setPen(QColor(c))
                p.drawText(pm.rect(), Qt.AlignCenter, glifo)
            p.end()
            ic.addPixmap(pm, modo)
        _CACHE_GLIFOS[chave] = ic
    return _CACHE_GLIFOS[chave]


TEXTOS_ESTADO = {"ocioso": "", "rodando": "", "pausando": "Pausando após o arquivo atual…",
                 "pausado": "Pausado", "parando": "Parando…",
                 "parado": "Parado — pode continuar depois"}


class ControlesProcesso(QWidget):
    """▶ Iniciar/Continuar, ⏸ Pausar e ⏹ Parar de um processo, com o rótulo do estado.

    Estados: "ocioso" (nada rodando), "rodando", "pausando" (até o próximo arquivo), "pausado",
    "parando" e "parado". O ▶ emite `iniciar` (ocioso) ou `continuar` (pausado/parado).
    `so_continuar=True` esconde o ▶ quando ocioso/rodando (a aba já tem o botão de início)."""

    iniciar = Signal()
    continuar = Signal()
    pausar = Signal()
    parar = Signal()

    def __init__(self, texto_iniciar: str = "Iniciar", texto_rodando: str | None = None,
                 texto_continuar: str = "Continuar", so_continuar: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("controles")
        self._txt = (texto_iniciar, texto_rodando or texto_iniciar, texto_continuar)
        self._so_continuar = so_continuar
        self._pode_iniciar = True
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.btn_play = QPushButton(texto_iniciar)
        self.btn_pausar = QPushButton("Pausar")
        self.btn_parar = QPushButton("Parar")
        for b, glifo, cor in ((self.btn_play, "▶", COR_PLAY), (self.btn_pausar, "⏸", COR_PAUSA),
                              (self.btn_parar, "⏹", COR_PARAR)):
            b.setIcon(icone_glifo(glifo, cor))
            b.setIconSize(QSize(16, 16))
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName("controle")
            lay.addWidget(b)
        self.btn_pausar.setToolTip("Pausa depois do arquivo atual (nada do que foi feito se perde)")
        self.btn_parar.setToolTip("Para o processo; o que já foi feito fica guardado e dá para "
                                  "continuar depois")
        self.lbl_estado = QLabel()
        self.lbl_estado.setObjectName("estadoProcesso")
        lay.addWidget(self.lbl_estado)
        lay.addStretch(1)
        self.btn_play.clicked.connect(self._play)
        self.btn_pausar.clicked.connect(self.pausar.emit)
        self.btn_parar.clicked.connect(self.parar.emit)
        self.estado = ""
        self.set_estado("ocioso")

    def _play(self) -> None:
        if self.estado in ("pausando", "pausado", "parado"):
            self.continuar.emit()
        else:
            self.iniciar.emit()

    def set_textos(self, iniciar: str, rodando: str | None = None) -> None:
        self._txt = (iniciar, rodando or iniciar, self._txt[2])
        self._aplicar()

    def set_pode_iniciar(self, on: bool) -> None:
        """Se o ▶ pode iniciar (ex.: há pasta/links válidos); só vale no estado ocioso."""
        self._pode_iniciar = on
        self._aplicar()

    def set_estado(self, estado: str, texto: str | None = None) -> None:
        if estado not in TEXTOS_ESTADO:
            raise ValueError(f"Estado desconhecido: {estado}")
        self.estado = estado
        self.lbl_estado.setText(TEXTOS_ESTADO[estado] if texto is None else texto)
        set_prop(self.lbl_estado, "estado", {"pausando": "aviso", "pausado": "aviso",
                                             "parando": "erro"}.get(estado, "ok"))
        self._aplicar()

    def _aplicar(self) -> None:
        e = self.estado
        ini, rod, cont = self._txt
        self.btn_play.setText({"ocioso": ini, "rodando": rod}.get(e, cont))
        self.btn_play.setVisible(not (self._so_continuar and e in ("ocioso", "rodando")))
        self.btn_play.setEnabled(e in ("pausando", "pausado", "parado")
                                 or (e == "ocioso" and self._pode_iniciar))
        self.btn_pausar.setEnabled(e == "rodando")
        self.btn_parar.setEnabled(e in ("rodando", "pausando", "pausado"))


class BarraGeral(QWidget):
    """Canto das abas: ⏸ Pausar tudo, ▶ Continuar tudo, ⏹ Parar tudo e quantos processos há."""

    pausar = Signal()
    continuar = Signal()
    parar = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("barraGeral")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 12, 4)
        lay.setSpacing(6)
        self.lbl = QLabel()
        self.lbl.setProperty("muted", True)
        lay.addWidget(self.lbl)
        lay.addSpacing(6)
        self.btn_pausar = QPushButton("Pausar tudo")
        self.btn_continuar = QPushButton("Continuar tudo")
        self.btn_parar = QPushButton("Parar tudo")
        for b, glifo, cor, sinal in ((self.btn_pausar, "⏸", COR_PAUSA, self.pausar),
                                     (self.btn_continuar, "▶", COR_PLAY, self.continuar),
                                     (self.btn_parar, "⏹", COR_PARAR, self.parar)):
            b.setIcon(icone_glifo(glifo, cor))
            b.setIconSize(QSize(14, 14))
            b.setObjectName("controleGeral")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(sinal.emit)
            lay.addWidget(b)
        self.atualizar(0, False, False, False)

    def atualizar(self, n: int, pode_pausar: bool, pode_continuar: bool, pode_parar: bool) -> None:
        self.lbl.setText(f"{n} processo(s) ativo(s)" if n else "Nenhum processo ativo")
        self.btn_pausar.setEnabled(n > 0 and pode_pausar)
        self.btn_continuar.setEnabled(n > 0 and pode_continuar)
        self.btn_parar.setEnabled(n > 0 and pode_parar)
