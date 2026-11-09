"""Diálogos do cadastro das formaturas (a ficha)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QInputDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from roteiro_ia.areas.formatura.ajustes import (ModeloAno, carregar_ajustes,
                                                salvar_ajustes)
from roteiro_ia.areas.formatura.cadastro import (Curso, Formatura, avisos, duplicar, listar,
                                                 nome_exibicao, salvar)
from roteiro_ia.config import Settings
from roteiro_ia.ui.widgets import Banner


class _CampoArquivo(QWidget):
    def __init__(self, titulo: str, pasta: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._titulo, self._pasta = titulo, pasta
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("(opcional)")
        b = QPushButton("Escolher…")
        b.clicked.connect(self._escolher)
        lay.addWidget(self.edit, 1)
        lay.addWidget(b)

    def _escolher(self) -> None:
        if self._pasta:
            v = QFileDialog.getExistingDirectory(self, self._titulo, self.edit.text())
        else:
            v, _ = QFileDialog.getOpenFileName(self, self._titulo, self.edit.text(),
                                               "Imagens (*.png *.jpg *.jpeg *.svg *.ai *.psd);;Todos (*)")
        if v:
            self.edit.setText(v)

    def valor(self) -> str | None:
        return self.edit.text().strip() or None


class DialogoFormatura(QDialog):
    """Cria ou edita uma ficha. `resultado` = a ficha gravada (None se cancelou)."""

    def __init__(self, s: Settings, f: Formatura | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.s = s
        self._id = f.id if f else ""
        self.resultado: Formatura | None = None
        self.setWindowTitle("Formatura")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edit_instituicao = QLineEdit(f.instituicao if f else "")
        self.campo_logo = _CampoArquivo("Logo da escola", pasta=False)
        self.campo_logo.edit.setText((f.logo_escola or "") if f else "")
        self.spin_ano = QSpinBox()
        self.spin_ano.setRange(2000, 2100)
        self.spin_ano.setValue(f.ano if f else 2026)
        self.combo_semestre = QComboBox()
        self.combo_semestre.addItems(["1º semestre", "2º semestre"])
        self.combo_semestre.setCurrentIndex((f.semestre - 1) if f else 0)
        self.campo_grafismos = _CampoArquivo("Pasta de vinhetas e logos", pasta=True)
        self.campo_grafismos.edit.setText((f.pasta_grafismos or "") if f else "")
        form.addRow("Instituição", self.edit_instituicao)
        form.addRow("Logo da escola", self.campo_logo)
        form.addRow("Ano", self.spin_ano)
        form.addRow("Semestre", self.combo_semestre)
        form.addRow("Vinhetas e logos", self.campo_grafismos)
        lay.addLayout(form)
        lay.addWidget(QLabel("Cursos e turmas (turmas separadas por vírgula: Manhã, Tarde, T106…)"))
        self.tabela = QTableWidget(0, 2)
        self.tabela.setHorizontalHeaderLabels(["Curso", "Turmas"])
        self.tabela.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabela.verticalHeader().hide()
        lay.addWidget(self.tabela, 1)
        botoes = QHBoxLayout()
        b_add, b_rem = QPushButton("+ Curso"), QPushButton("Remover curso")
        b_add.clicked.connect(lambda: self.adicionar_curso("", ""))
        b_rem.clicked.connect(lambda: self.tabela.removeRow(self.tabela.currentRow())
                              if self.tabela.currentRow() >= 0 else None)
        botoes.addWidget(b_add)
        botoes.addWidget(b_rem)
        botoes.addStretch(1)
        lay.addLayout(botoes)
        self.banner = Banner("erro")
        lay.addWidget(self.banner)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Salvar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.aceitar)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for c in (f.cursos if f else []):
            self.adicionar_curso(c.nome, ", ".join(c.turmas))

    def adicionar_curso(self, nome: str, turmas: str) -> None:
        r = self.tabela.rowCount()
        self.tabela.insertRow(r)
        self.tabela.setItem(r, 0, QTableWidgetItem(nome))
        self.tabela.setItem(r, 1, QTableWidgetItem(turmas))

    def _cursos(self) -> list[Curso]:
        out = []
        for r in range(self.tabela.rowCount()):
            nome = (self.tabela.item(r, 0).text() if self.tabela.item(r, 0) else "")
            turmas = (self.tabela.item(r, 1).text() if self.tabela.item(r, 1) else "")
            if nome.strip() or turmas.strip():
                out.append(Curso(nome=nome, turmas=[t for t in turmas.split(",")]))
        return out

    def aceitar(self) -> None:
        f = Formatura(id=self._id, instituicao=self.edit_instituicao.text(),
                      logo_escola=self.campo_logo.valor(), ano=self.spin_ano.value(),
                      semestre=self.combo_semestre.currentIndex() + 1, cursos=self._cursos(),
                      pasta_grafismos=self.campo_grafismos.valor())
        try:
            self.resultado = salvar(self.s, f)
        except (ValueError, OSError) as e:
            self.banner.mostrar(str(e))
            return
        self.accept()


class DialogoCadastro(QDialog):
    """Lista das formaturas cadastradas: Nova, Editar e Duplicar."""

    def __init__(self, s: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.s = s
        self.setWindowTitle("Formaturas")
        self.setMinimumSize(520, 380)
        lay = QVBoxLayout(self)
        # logo da produtora: vale para todas as formaturas (fim do clipe de encerramento)
        linha_logo = QHBoxLayout()
        linha_logo.addWidget(QLabel("Logo da produtora"))
        self.edit_logo = QLineEdit(carregar_ajustes(s).logo_produtora or "")
        self.edit_logo.setReadOnly(True)
        self.edit_logo.setPlaceholderText("(entra no fim do clipe de encerramento da colação)")
        b_logo = QPushButton("Escolher…")
        b_logo.clicked.connect(self._escolher_logo)
        linha_logo.addWidget(self.edit_logo, 1)
        linha_logo.addWidget(b_logo)
        lay.addLayout(linha_logo)
        # modelos do ano: vídeos modelo (estilo) e cartela MOGRT; a versão pode mudar a cada ano
        lay.addWidget(QLabel("Modelos do ano (vídeos modelo e cartela MOGRT; cada formatura usa "
                             "os do seu ano ou, se faltar, os do ano anterior mais recente)"))
        self.tabela_modelos = QTableWidget(0, 3)
        self.tabela_modelos.setHorizontalHeaderLabels(["Ano", "Pasta dos vídeos modelo", "Cartela MOGRT"])
        self.tabela_modelos.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabela_modelos.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tabela_modelos.verticalHeader().hide()
        self.tabela_modelos.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela_modelos.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela_modelos.setMaximumHeight(130)
        lay.addWidget(self.tabela_modelos)
        bm = QHBoxLayout()
        for texto, fn in (("Adicionar ano", self._adicionar_ano), ("Pasta dos vídeos…", self._escolher_pasta_modelo),
                          ("Cartela MOGRT…", self._escolher_mogrt), ("Remover ano", self._remover_selecionado)):
            b = QPushButton(texto)
            b.clicked.connect(fn)
            bm.addWidget(b)
        bm.addStretch(1)
        lay.addLayout(bm)
        self._mostrar_modelos()
        self.lista = QListWidget()
        lay.addWidget(self.lista, 1)
        self.lbl_avisos = QLabel()
        self.lbl_avisos.setProperty("muted", True)
        self.lbl_avisos.setWordWrap(True)
        lay.addWidget(self.lbl_avisos)
        botoes = QHBoxLayout()
        for texto, fn in (("Nova", self.nova), ("Editar", self.editar), ("Duplicar", self.duplicar)):
            b = QPushButton(texto)
            b.clicked.connect(fn)
            botoes.addWidget(b)
        botoes.addStretch(1)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(self.accept)
        botoes.addWidget(fechar)
        lay.addLayout(botoes)
        self.lista.currentItemChanged.connect(lambda *_: self._avisos())
        self.lista.itemDoubleClicked.connect(lambda *_: self.editar())
        self.recarregar()

    def _escolher_logo(self) -> None:
        v, _ = QFileDialog.getOpenFileName(self, "Logo da produtora", self.edit_logo.text(),
                                           "Imagens (*.png *.jpg *.jpeg *.tif *.tiff *.psd);;Todos (*)")
        if v:
            self.definir_logo(v)

    def definir_logo(self, caminho: str | None) -> None:
        a = carregar_ajustes(self.s)
        a.logo_produtora = caminho or None
        salvar_ajustes(self.s, a)
        self.edit_logo.setText(caminho or "")

    # ------------------------------------------------------------ modelos do ano
    def _mostrar_modelos(self) -> None:
        modelos = carregar_ajustes(self.s).modelos
        self.tabela_modelos.setRowCount(0)
        for ano in sorted(modelos, reverse=True):
            r = self.tabela_modelos.rowCount()
            self.tabela_modelos.insertRow(r)
            m = modelos[ano]
            for col, v in enumerate((ano, m.pasta or "(sem pasta)", m.mogrt or "(cartela simples)")):
                self.tabela_modelos.setItem(r, col, QTableWidgetItem(v))

    def definir_modelo(self, ano: str, pasta: str | None = None, mogrt: str | None = None) -> None:
        a = carregar_ajustes(self.s)
        m = a.modelos.get(ano, ModeloAno())
        upd = {k: v for k, v in (("pasta", pasta), ("mogrt", mogrt)) if v is not None}
        a.modelos[ano] = m.model_copy(update=upd)
        salvar_ajustes(self.s, a)
        self._mostrar_modelos()

    def remover_modelo(self, ano: str) -> None:
        a = carregar_ajustes(self.s)
        a.modelos.pop(ano, None)
        salvar_ajustes(self.s, a)
        self._mostrar_modelos()

    def _ano_selecionado(self) -> str | None:
        r = self.tabela_modelos.currentRow()
        return self.tabela_modelos.item(r, 0).text() if r >= 0 else None

    def _adicionar_ano(self) -> None:
        from datetime import date
        ano, ok = QInputDialog.getInt(self, "Modelos do ano", "Ano:", date.today().year, 2000, 2100)
        if ok:
            self.definir_modelo(str(ano))

    def _escolher_pasta_modelo(self) -> None:
        if (ano := self._ano_selecionado()) is None:
            return
        v = QFileDialog.getExistingDirectory(self, f"Vídeos modelo de {ano}")
        if v:
            self.definir_modelo(ano, pasta=v)

    def _escolher_mogrt(self) -> None:
        if (ano := self._ano_selecionado()) is None:
            return
        v, _ = QFileDialog.getOpenFileName(self, f"Cartela de {ano}", "", "Modelo do Premiere (*.mogrt)")
        if v:
            self.definir_modelo(ano, mogrt=v)

    def _remover_selecionado(self) -> None:
        if (ano := self._ano_selecionado()) is not None:
            self.remover_modelo(ano)

    def recarregar(self, selecionar: str | None = None) -> None:
        self.lista.clear()
        for f in listar(self.s):
            it = QListWidgetItem(nome_exibicao(f))
            it.setData(Qt.UserRole, f)
            self.lista.addItem(it)
            if f.id == selecionar:
                self.lista.setCurrentItem(it)

    def _atual(self) -> Formatura | None:
        it = self.lista.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _avisos(self) -> None:
        f = self._atual()
        self.lbl_avisos.setText("\n".join(avisos(f)) if f else "")

    def _abrir(self, f: Formatura | None) -> None:
        d = DialogoFormatura(self.s, f, self)
        if d.exec() and d.resultado is not None:
            self.recarregar(d.resultado.id)

    def nova(self) -> None:
        self._abrir(None)

    def editar(self) -> None:
        if f := self._atual():
            self._abrir(f)

    def duplicar(self) -> None:
        if f := self._atual():
            self._abrir(duplicar(f))
