"""Formulário da Formatura: o do Casamento (pasta, disco, músicas, Gemini) com o card Trabalho
(clipe ou colação, formatura do cadastro, curso e turma) e as funções de pasta da Formatura."""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QScrollArea, QSizePolicy,
                               QVBoxLayout, QCheckBox, QComboBox, QDoubleSpinBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QWidget)

from roteiro_ia.areas.base import Area
from roteiro_ia.areas.formatura.cadastro import Formatura, carregar, listar, nome_exibicao
from roteiro_ia.areas.formatura.funcoes import (ROLE_DA_FUNCAO, ROTULO_FUNCAO, FuncaoFormatura,
                                                funcoes_do_grupo, listar_pastas, sugerir_funcao)
from roteiro_ia.areas.formatura.pipeline import MSG_SEM_PGM, PipelineFormatura
from roteiro_ia.areas.formatura.projeto import (ProjetoFormatura, RequestFormatura,
                                                carregar_projeto, projetos_da_area)
from roteiro_ia.areas.formatura.tipos import INFO_TIPO, TIPOS_CLIPE, TipoTrabalho
from roteiro_ia.config import Settings
from roteiro_ia.models import FolderAssignment
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import PROJECT_FILE, ProjectRequest
from roteiro_ia.ui.formulario import FormularioEvento
from roteiro_ia.ui.widgets import Card
from roteiro_ia.ui.worker import Runner

AVISO_FORMATURA = "Escolha a formatura."  # motivo inicial (sem pasta/formatura escolhidas)
_ESCOLHA = "— escolha —"


def _chave(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


class _RolagemVertical(QScrollArea):
    """Rola só na vertical e pede a largura mínima do conteúdo (nada cortado à direita)."""

    def __init__(self):
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def setWidget(self, w):
        super().setWidget(w)
        w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.widget() and ev.type() == QEvent.LayoutRequest:
            self.updateGeometry()  # conteúdo mudou: a largura pedida é recalculada
        return super().eventFilter(obj, ev)

    def minimumSizeHint(self):
        base = super().minimumSizeHint()
        w = self.widget()
        if w is None:
            return base
        largura = w.minimumSizeHint().width() + self.verticalScrollBar().sizeHint().width() + 2
        return base.expandedTo(base.__class__(largura, base.height()))


class FormularioFormatura(FormularioEvento):
    def __init__(self, s: Settings, runner: Runner, parent: QWidget | None = None,
                 area: str = "formatura"):
        super().__init__(s, runner, parent, area)
        self._pastas: list[tuple[str, str]] = []
        self._duplicado_de: str | None = None
        self._ficha_faltando: str | None = None
        self.card_entregas.hide()  # episódios/trailer… são do Casamento
        self.card_gemini.set_numero(5)  # sem Entregas, a numeração segue sem buraco
        self._montar_trabalho()
        # funções de pasta da Formatura no lugar da tabela do Casamento (mesmo card)
        self.tabela.hide()
        self.tabela_f = QTableWidget(0, 2)
        self.tabela_f.setHorizontalHeaderLabels(["Pasta", "O que é"])
        self.tabela_f.verticalHeader().hide()
        self.tabela_f.verticalHeader().setDefaultSectionSize(36)
        self.tabela_f.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabela_f.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tabela_f.setColumnWidth(1, 240)
        self.tabela_f.setMinimumHeight(180)
        self.tabela_f.setShowGrid(False)
        self.tabela_f.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cards[2].body.addWidget(self.tabela_f, 1)
        for lbl in self.cards[2].findChildren(QLabel):
            if lbl.text().startswith("Confira a sugestão."):  # a dica do Casamento fala de "Dia"
                lbl.setText("Confira a sugestão. Pastas de dias (ex.: 2026-03-10 › CAM A) já vêm "
                            "separadas por dia.")
        self.lbl_aviso = QLabel()
        self.lbl_aviso.setProperty("muted", True)
        self.lbl_aviso.setWordWrap(True)
        self.layout().addWidget(self.lbl_aviso)
        # caminho e nome do evento quebram linha: um caminho longo não alarga a tela
        for lbl in (self.lbl_evento, self.lbl_espaco):
            lbl.setWordWrap(True)
            lbl.setMinimumWidth(80)
        # o caminho pode ser um "palavrão" sem espaços: encolhe (o inteiro fica na dica do mouse)
        for lbl in (self.lbl_caminho, self.campo_musicas.lbl_caminho):
            pol = lbl.sizePolicy()
            pol.setHorizontalPolicy(QSizePolicy.Ignored)
            lbl.setSizePolicy(pol)
            lbl.setMinimumWidth(60)
        self._rolagem()
        self._recarregar_formaturas()
        self._mudou_grupo()

    def _rolagem(self) -> None:
        """Os cards vão para uma área com rolagem (a Formatura tem um card a mais que o
        Casamento); o Iniciar e o aviso ficam sempre à vista, embaixo."""
        lay = self.layout()
        fixos = (self.btn_iniciar, self.lbl_aviso)
        conteudo = QWidget()
        conteudo.setObjectName("conteudoFormatura")
        cl = QVBoxLayout(conteudo)
        cl.setContentsMargins(0, 0, 6, 0)
        cl.setSpacing(lay.spacing())
        itens = [lay.takeAt(0) for _ in range(lay.count())]
        def reparentar(item) -> None:  # addItem não muda o pai dos widgets: muda à mão
            if item.widget() is not None:
                item.widget().setParent(conteudo)
            elif item.layout() is not None:
                for k in range(item.layout().count()):
                    reparentar(item.layout().itemAt(k))
        for it in itens:
            if it.widget() not in fixos:
                reparentar(it)
                cl.addItem(it)
        self.rolagem = _RolagemVertical()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.NoFrame)
        self.rolagem.setStyleSheet("QScrollArea, QWidget#conteudoFormatura {background: transparent;}")
        self.rolagem.viewport().setAutoFillBackground(False)
        self.rolagem.setWidget(conteudo)
        # só rolagem vertical: a largura continua a do conteúdo, como no Casamento
        lay.addWidget(self.rolagem, 1)
        for w in fixos:
            lay.addWidget(w)

    # ------------------------------------------------------------ card Trabalho
    def _montar_trabalho(self) -> None:
        card = Card("Trabalho")
        self.card_trabalho = card
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.seg_clipes, self.seg_colacao = QPushButton("Clipes"), QPushButton("Colação")
        self._grupo_seg = QButtonGroup(self)
        for b, pos in ((self.seg_clipes, "esq"), (self.seg_colacao, "dir")):
            b.setObjectName("segmento")
            b.setProperty("pos", pos)
            b.setCheckable(True)
            self._grupo_seg.addButton(b)
            seg.addWidget(b)
        self.seg_clipes.setChecked(True)
        self.combo_formatura = QComboBox()
        self.btn_formaturas = QPushButton("Formaturas…")
        self.btn_nova = QPushButton("+ Nova")
        self.btn_duplicar = QPushButton("Duplicar oficina…")
        self.btn_duplicar.setToolTip("Copia a preparação de uma oficina já feita para outra turma.")
        seg.addStretch(1)
        for b in (self.btn_formaturas, self.btn_nova, self.btn_duplicar):
            seg.addSpacing(6)
            seg.addWidget(b)
        card.body.addLayout(seg)

        # grade de 4 colunas (rótulo, campo, rótulo, campo): cabe em telas estreitas
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        g.setColumnStretch(1, 3)
        g.setColumnStretch(3, 2)
        g.addWidget(QLabel("Formatura"), 0, 0)
        g.addWidget(self.combo_formatura, 0, 1, 1, 3)
        # clipes: tipo e duração; curso e turma
        self.combo_tipo = QComboBox()
        for t in TIPOS_CLIPE:
            self.combo_tipo.addItem(INFO_TIPO[t].nome, t.value)
        self.combo_curso, self.combo_turma = QComboBox(), QComboBox()
        self.spin_duracao = QDoubleSpinBox()
        self.spin_duracao.setRange(0.5, 120)
        self.spin_duracao.setSingleStep(0.5)
        self.spin_duracao.setDecimals(1)
        self.spin_duracao.setSuffix(" min")
        self.spin_duracao.setValue(INFO_TIPO[TipoTrabalho.oficina].duracao_min)
        self.lbl_tipo, self.lbl_curso = QLabel("Tipo"), QLabel("Curso")
        self.lbl_turma, self.lbl_duracao = QLabel("Turma"), QLabel("Duração")
        g.addWidget(self.lbl_tipo, 1, 0)
        g.addWidget(self.combo_tipo, 1, 1)
        g.addWidget(self.lbl_duracao, 1, 2)
        g.addWidget(self.spin_duracao, 1, 3)
        g.addWidget(self.lbl_curso, 2, 0)
        g.addWidget(self.combo_curso, 2, 1)
        g.addWidget(self.lbl_turma, 2, 2)
        g.addWidget(self.combo_turma, 2, 3)
        # colação: local e cidade; canais da mesa; turmas da noite
        self.edit_local, self.edit_cidade = QLineEdit(), QLineEdit()
        self.combo_canais = QComboBox()
        self.combo_canais.addItem("Áudio da mesa já misturado", "misturado")
        self.combo_canais.addItem("L = mesa de som / R = ambiente", "L_mesa_R_ambiente")
        self.lbl_local, self.lbl_cidade = QLabel("Local"), QLabel("Cidade")
        self.lbl_turmas, self.lbl_canais = QLabel("Turmas"), QLabel("Canais")
        self.lbl_canais.setToolTip("Canais de áudio da gravação da mesa de corte")
        self.lbl_turmas.setToolTip("Turmas que se formam nesta noite")
        g.addWidget(self.lbl_local, 3, 0)
        g.addWidget(self.edit_local, 3, 1)
        g.addWidget(self.lbl_cidade, 3, 2)
        g.addWidget(self.edit_cidade, 3, 3)
        g.addWidget(self.lbl_canais, 4, 0)
        g.addWidget(self.combo_canais, 4, 1, 1, 3)
        self.lista_turmas = QListWidget()
        self.lista_turmas.setFlow(QListWidget.LeftToRight)
        self.lista_turmas.setWrapping(True)
        self.lista_turmas.setSpacing(4)
        self.lista_turmas.setMinimumHeight(36)
        self.lista_turmas.setMaximumHeight(80)
        g.addWidget(self.lbl_turmas, 5, 0, Qt.AlignTop)
        g.addWidget(self.lista_turmas, 5, 1, 1, 3)
        card.body.addLayout(g)
        # duplicada de outra oficina
        self.chk_seguir = QCheckBox("Seguir a ideia da original (com música nova)")
        self.chk_seguir.setToolTip("Mesmos assuntos e ordem da oficina original, com música nova; "
                                   "o ritmo e as cenas seguem a trilha nova.")
        self.chk_seguir.setChecked(True)
        self.lbl_duplicado = QLabel()
        self.lbl_duplicado.setProperty("muted", True)
        self.lbl_duplicado.setWordWrap(True)
        card.body.addWidget(self.lbl_duplicado)
        card.body.addWidget(self.chk_seguir)
        for w in (self.combo_formatura, self.combo_tipo, self.combo_curso, self.combo_turma,
                  self.spin_duracao, self.edit_local, self.edit_cidade, self.combo_canais):
            w.setMinimumHeight(30)
        for c in (self.combo_formatura, self.combo_tipo, self.combo_curso, self.combo_turma,
                  self.combo_canais):
            # nome longo (ex.: curso) não estica a tela: a lista mostra o começo e "…"
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(8)
        self.layout().insertWidget(1, card)
        self.cards.append(card)
        self._clipe_ws = [self.lbl_tipo, self.combo_tipo, self.lbl_duracao, self.spin_duracao,
                          self.btn_duplicar]
        self._colacao_ws = [self.lbl_local, self.edit_local, self.lbl_cidade, self.edit_cidade,
                            self.lbl_turmas, self.lista_turmas, self.lbl_canais, self.combo_canais]

        self._grupo_seg.buttonToggled.connect(lambda _b, on: on and self._mudou_grupo())
        self.combo_formatura.currentIndexChanged.connect(lambda _i: self._mudou_formatura())
        self.combo_tipo.currentIndexChanged.connect(lambda _i: self._mudou_tipo())
        self.combo_curso.currentIndexChanged.connect(lambda _i: self._mudou_curso())
        self.combo_turma.currentIndexChanged.connect(lambda _i: self._atualizar_iniciar())
        self.lista_turmas.itemChanged.connect(lambda _it: self._atualizar_iniciar())
        self.btn_formaturas.clicked.connect(self._abrir_cadastro)
        self.btn_nova.clicked.connect(self._nova_formatura)
        self.btn_duplicar.clicked.connect(self._duplicar)

    # ------------------------------------------------------------ estado do trabalho
    def grupo(self) -> str:
        return "colacao" if self.seg_colacao.isChecked() else "clipe"

    def tipo(self) -> TipoTrabalho:
        if self.grupo() == "colacao":
            return TipoTrabalho.colacao
        return TipoTrabalho(self.combo_tipo.currentData())

    def ficha(self) -> Formatura | None:
        fid = self.combo_formatura.currentData()
        return carregar(self.s, fid) if fid else None

    def _recarregar_formaturas(self, selecionar: str | None = None) -> None:
        atual = selecionar if selecionar is not None else self.combo_formatura.currentData()
        self.combo_formatura.blockSignals(True)
        self.combo_formatura.clear()
        self.combo_formatura.addItem(_ESCOLHA, "")
        for f in listar(self.s):
            self.combo_formatura.addItem(nome_exibicao(f), f.id)
        i = self.combo_formatura.findData(atual) if atual else 0
        self.combo_formatura.setCurrentIndex(max(i, 0))
        self.combo_formatura.blockSignals(False)
        self._mudou_formatura()

    def _mudou_grupo(self) -> None:
        col = self.grupo() == "colacao"
        for w in self._clipe_ws:
            w.setVisible(not col)
        for w in self._colacao_ws:
            w.setVisible(col)
        self._carregar_tabela()  # as funções mudam entre clipe e colação: novas sugestões
        self._mudou_tipo()

    def _mudou_formatura(self) -> None:
        if self.combo_formatura.currentData():
            self._ficha_faltando = None
        f = self.ficha()
        curso_atual = self.combo_curso.currentData()
        marcadas = {tuple(self.lista_turmas.item(i).data(Qt.UserRole))
                    for i in range(self.lista_turmas.count())
                    if self.lista_turmas.item(i).checkState() == Qt.Checked}
        self.combo_curso.blockSignals(True)
        self.combo_curso.clear()
        if self.tipo() == TipoTrabalho.feira:
            self.combo_curso.addItem("(escola inteira)", None)
        else:
            self.combo_curso.addItem(_ESCOLHA, None)
        for c in (f.cursos if f else []):
            self.combo_curso.addItem(c.nome, c.nome)
        i = self.combo_curso.findData(curso_atual) if curso_atual else -1
        if i < 0 and f and len(f.cursos) == 1 and self.tipo() != TipoTrabalho.feira:
            i = 1
        self.combo_curso.setCurrentIndex(max(i, 0))
        self.combo_curso.blockSignals(False)
        self.lista_turmas.blockSignals(True)
        self.lista_turmas.clear()
        for c in (f.cursos if f else []):
            for t in c.turmas:
                it = QListWidgetItem(f"{c.nome} — {t}")
                it.setData(Qt.UserRole, (c.nome, t))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if (c.nome, t) in marcadas else Qt.Unchecked)
                self.lista_turmas.addItem(it)
        self.lista_turmas.blockSignals(False)
        self._mudou_curso()

    def _mudou_tipo(self) -> None:
        info = INFO_TIPO[self.tipo()]
        if info.duracao_min and self.tipo() != getattr(self, "_tipo_visto", None):
            self.spin_duracao.setValue(info.duracao_min)  # só quando o tipo muda de fato
        self._tipo_visto = self.tipo()
        sem_turma = self.grupo() == "colacao" or info.turma == "nenhuma"
        self.lbl_turma.setVisible(not sem_turma)
        self.combo_turma.setVisible(not sem_turma)
        clipe = self.grupo() == "clipe"
        self.lbl_curso.setVisible(clipe)
        self.combo_curso.setVisible(clipe)
        oficina = self.tipo() == TipoTrabalho.oficina
        self.chk_seguir.setVisible(oficina and self._duplicado_de is not None)
        self.lbl_duplicado.setVisible(oficina and self._duplicado_de is not None)
        if self.combo_formatura.count():
            curso = self.combo_curso.currentData()
            self._mudou_formatura_sem_loop(curso)

    def _mudou_formatura_sem_loop(self, curso) -> None:
        """Refaz a lista de cursos (a 1ª opção muda entre feira e os outros) mantendo o curso."""
        f = self.ficha()
        self.combo_curso.blockSignals(True)
        self.combo_curso.setItemText(0, "(escola inteira)" if self.tipo() == TipoTrabalho.feira
                                     else _ESCOLHA)
        i = self.combo_curso.findData(curso) if curso else -1
        if i < 0 and f and len(f.cursos) == 1 and self.tipo() != TipoTrabalho.feira:
            i = 1
        self.combo_curso.setCurrentIndex(max(i, 0))
        self.combo_curso.blockSignals(False)
        self._mudou_curso()

    def _mudou_curso(self, turma=None) -> None:
        f = self.ficha()
        curso = self.combo_curso.currentData()
        atual = turma if turma is not None else self.combo_turma.currentData()
        self.combo_turma.blockSignals(True)
        self.combo_turma.clear()
        info = INFO_TIPO[self.tipo()]
        self.combo_turma.addItem("(todas)" if info.turma == "opcional" else _ESCOLHA, None)
        turmas = next((c.turmas for c in (f.cursos if f else []) if c.nome == curso), [])
        for t in turmas:
            self.combo_turma.addItem(t, t)
        if atual and self.combo_turma.findData(atual) < 0 and curso:
            self.combo_turma.addItem(f"{atual} (turma não está mais na ficha)", atual)
        i = self.combo_turma.findData(atual) if atual else 0
        self.combo_turma.setCurrentIndex(max(i, 0))
        self.combo_turma.blockSignals(False)
        self._atualizar_iniciar()

    # ------------------------------------------------------------ tabela de pastas
    def funcao(self, row: int) -> FuncaoFormatura:
        return FuncaoFormatura(self.tabela_f.cellWidget(row, 1).currentData())

    def _carregar_tabela(self, funcoes: dict[str, FuncaoFormatura] | None = None) -> None:
        anteriores = funcoes or {}
        grupo = self.grupo()
        validas = funcoes_do_grupo(grupo)
        self.tabela_f.setRowCount(0)
        for pasta, _dia in self._pastas:
            r = self.tabela_f.rowCount()
            self.tabela_f.insertRow(r)
            it = QTableWidgetItem(pasta)
            it.setFlags(Qt.ItemIsEnabled)
            self.tabela_f.setItem(r, 0, it)
            combo = QComboBox()
            for fn in validas:
                combo.addItem(ROTULO_FUNCAO[fn], fn.value)
            fn = anteriores.get(pasta)
            if fn not in validas:
                fn = sugerir_funcao(pasta, grupo)
            combo.setCurrentIndex(combo.findData(fn.value))
            self.tabela_f.setCellWidget(r, 1, combo)

    # ------------------------------------------------------------ pasta do evento
    def set_event_folder(self, path: Path) -> bool:
        path = Path(path)
        if self._duplicado_de and _chave(path) == _chave(self._duplicado_de):
            self.source = None
            self._pastas = []
            self.tabela_f.setRowCount(0)
            self._erro_evento("Escolha a pasta da nova turma.")
            self._atualizar_iniciar()
            return False
        ok = super().set_event_folder(path)
        self.lbl_caminho.setToolTip(str(path))
        if hasattr(self, "rolagem"):
            self.rolagem.updateGeometry()  # textos novos: a largura pedida é recalculada
        if hasattr(self, "combo_formatura"):
            self._recarregar_formaturas()  # a ficha pode ter sido criada/editada em outro lugar
        self._pastas = listar_pastas(path) if ok else []
        if hasattr(self, "tabela_f"):
            self._carregar_tabela()
            self._atualizar_iniciar()
        return ok

    # ------------------------------------------------------------ pedido
    def assignments(self) -> list[FolderAssignment]:
        return [FolderAssignment(folder=pasta, role=ROLE_DA_FUNCAO[self.funcao(r)], day_label=dia)
                for r, (pasta, dia) in enumerate(self._pastas)]

    def projeto_formatura(self) -> ProjetoFormatura:
        tipo = self.tipo()
        clipe = self.grupo() == "clipe"
        turmas = [self.lista_turmas.item(i).data(Qt.UserRole) for i in range(self.lista_turmas.count())
                  if self.lista_turmas.item(i).checkState() == Qt.Checked]
        return ProjetoFormatura(
            tipo=tipo, formatura_id=self.combo_formatura.currentData() or self._ficha_faltando or "",
            curso=self.combo_curso.currentData() if clipe else None,
            turma=(self.combo_turma.currentData() if clipe and INFO_TIPO[tipo].turma != "nenhuma"
                   else None),
            duracao_min=self.spin_duracao.value() if clipe else None,
            funcoes={pasta: self.funcao(r) for r, (pasta, _d) in enumerate(self._pastas)},
            canais_mesa=self.combo_canais.currentData(),
            duplicado_de=self._duplicado_de if tipo == TipoTrabalho.oficina else None,
            seguir_ideia=self.chk_seguir.isChecked(),
            local=self.edit_local.text().strip() or None if not clipe else None,
            cidade=self.edit_cidade.text().strip() or None if not clipe else None,
            turmas_colacao=[tuple(t) for t in turmas] if not clipe else [])

    def pasta_pecas(self) -> str:
        """Pasta das timelines no projeto do Premiere."""
        return "PARTES DA COLAÇÃO" if self.grupo() == "colacao" else "CLIPES"

    def build_request(self) -> RequestFormatura:
        base = super().build_request()
        campos = {f.name: getattr(base, f.name) for f in dataclasses.fields(ProjectRequest)}
        campos.update(n_episodios=1, derivados=set())
        return RequestFormatura(**campos, formatura=self.projeto_formatura())

    def _aplicar(self, pf: ProjetoFormatura, com_turma: bool = True) -> None:
        (self.seg_colacao if INFO_TIPO[pf.tipo].grupo == "colacao" else self.seg_clipes).setChecked(True)
        if pf.tipo != TipoTrabalho.colacao:
            self.combo_tipo.setCurrentIndex(self.combo_tipo.findData(pf.tipo.value))
        self._recarregar_formaturas(pf.formatura_id)
        if self.combo_formatura.currentData() != pf.formatura_id:
            self._ficha_faltando = pf.formatura_id
        i = self.combo_curso.findData(pf.curso) if pf.curso else -1
        if i >= 0:
            self.combo_curso.setCurrentIndex(i)
        self._mudou_curso(turma=pf.turma if com_turma else None)
        if not com_turma:
            self.combo_turma.setCurrentIndex(0)
        if pf.duracao_min:
            self.spin_duracao.setValue(pf.duracao_min)
        self.combo_canais.setCurrentIndex(max(self.combo_canais.findData(pf.canais_mesa), 0))
        self.chk_seguir.setChecked(pf.seguir_ideia)
        self.edit_local.setText(pf.local or "")
        self.edit_cidade.setText(pf.cidade or "")
        marcadas = {tuple(t) for t in pf.turmas_colacao}
        for k in range(self.lista_turmas.count()):
            it = self.lista_turmas.item(k)
            it.setCheckState(Qt.Checked if tuple(it.data(Qt.UserRole)) in marcadas else Qt.Unchecked)

    def load_request(self, req: ProjectRequest) -> None:
        super().load_request(req)
        try:
            ad = Path(build_event_paths(req.source_dir, self.s, req.work_drive).analysis_dir)
        except ValueError:
            return
        pf = carregar_projeto(ad)
        if pf is None:
            return
        self._duplicado_de = pf.duplicado_de
        self._aplicar(pf)
        self._carregar_tabela(pf.funcoes)
        self._mostrar_duplicado()
        self._atualizar_iniciar()

    # ------------------------------------------------------------ duplicar oficina
    def _mostrar_duplicado(self) -> None:
        txt = f"Duplicada de: {Path(self._duplicado_de).name}" if self._duplicado_de else ""
        self.lbl_duplicado.setText(txt)
        self._mudou_tipo()

    def duplicar_de(self, pasta: Path) -> bool:
        """Copia a preparação da oficina em `pasta` (a turma fica para escolher)."""
        try:
            ad = Path(build_event_paths(Path(pasta), self.s, self.s.work_drive).analysis_dir)
        except ValueError:
            return False
        pf = carregar_projeto(ad)
        if pf is None or pf.tipo != TipoTrabalho.oficina:
            return False
        try:
            req = ProjectRequest.load(ad / PROJECT_FILE)
        except (OSError, ValueError, KeyError):
            req = None
        self._duplicado_de = str(pasta)
        self._aplicar(pf.model_copy(update={"seguir_ideia": True}), com_turma=False)
        if req is not None:
            self.campo_musicas.set_pasta(req.pasta_musicas)
            (self.btn_pago if req.gemini_mode == "pago" else self.btn_gratis).setChecked(True)
        self._mostrar_duplicado()
        self._atualizar_iniciar()
        return True

    def _duplicar(self) -> None:
        opcoes = [(pasta, pf) for pasta, _d, pf in projetos_da_area(self.s)
                  if pf.tipo == TipoTrabalho.oficina]
        if not opcoes:
            QMessageBox.information(self, "Duplicar oficina",
                                    "Ainda não há oficina preparada para duplicar.")
            return
        nomes = [p.name for p, _ in opcoes]
        nome, ok = QInputDialog.getItem(self, "Duplicar oficina", "Oficina original:", nomes, 0, False)
        if not ok:
            return
        pasta = opcoes[nomes.index(nome)][0]
        if not self.duplicar_de(pasta):
            return
        nova = self.escolher_pasta("Escolha a pasta da nova turma")
        if nova:
            self.set_event_folder(nova)

    # ------------------------------------------------------------ cadastro
    def _abrir_cadastro(self) -> None:
        from roteiro_ia.areas.formatura.ui_cadastro import DialogoCadastro
        DialogoCadastro(self.s, self).exec()
        self._recarregar_formaturas()

    def _nova_formatura(self) -> None:
        from roteiro_ia.areas.formatura.ui_cadastro import DialogoFormatura
        d = DialogoFormatura(self.s, None, self)
        if d.exec() and d.resultado is not None:
            self._recarregar_formaturas(d.resultado.id)

    # ------------------------------------------------------------ iniciar
    def motivo_bloqueio(self) -> str:
        if self.source is None:
            return "Escolha a pasta do evento."
        if self._ficha_faltando and not self.combo_formatura.currentData():
            return "Formatura não encontrada. Escolha outra."
        if not self.combo_formatura.currentData():
            return "Escolha a formatura."
        if self.grupo() == "colacao":
            if not any(self.lista_turmas.item(i).checkState() == Qt.Checked
                       for i in range(self.lista_turmas.count())):
                return "Marque as turmas da colação."
            if not any(self.funcao(r) == FuncaoFormatura.mesa_corte
                       for r in range(self.tabela_f.rowCount())):
                return MSG_SEM_PGM
            return ""
        if INFO_TIPO[self.tipo()].turma == "obrigatoria" and not self.combo_turma.currentData():
            return "Escolha a turma."
        return ""

    def _atualizar_iniciar(self) -> None:
        if not hasattr(self, "lbl_aviso"):  # chamado pelo __init__ do Casamento, antes do card
            self.btn_iniciar.setEnabled(False)
            self.btn_iniciar.setToolTip(AVISO_FORMATURA)
            return
        motivo = self.motivo_bloqueio()
        self.lbl_aviso.setText(motivo)
        self.btn_iniciar.setToolTip(motivo)
        self.btn_iniciar.setEnabled(not motivo and not self._rodando)


FORMATURA = Area("formatura", "Formatura", FormularioFormatura, pipeline=PipelineFormatura)
