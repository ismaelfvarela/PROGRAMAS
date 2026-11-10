"""Coluna da esquerda da aba Projeto: os passos de preparação de um evento."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from roteiro_ia.config import Settings, pasta_musicas_padrao
from roteiro_ia.inventory import VIDEO_EXTS, list_subfolders
from roteiro_ia.models import FolderAssignment, Role
from roteiro_ia.observacoes import Observacoes
from roteiro_ia.paths import EventNameError, estimate_proxy_gb, parse_event_name
from roteiro_ia.pipeline import ProjectRequest
from roteiro_ia.ui.widgets import Card, CampoPastaMusicas, SubfolderTable, set_prop
from roteiro_ia.ui.worker import Runner, TarefaWorker

_PREFIXO_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}\s*-?\s*")
# vídeo de câmera fica em torno de 100 Mb/s: ~45 GB por hora de gravação (só para a estimativa)
BYTES_POR_HORA_VIDEO = 45 * 1024**3
PASTA_INICIAL = "R:\\"


def fmt_gb(gb: float) -> str:
    if gb >= 1024:
        return f"{gb / 1024:.1f} TB".replace(".", ",")
    return f"{gb:.0f} GB" if gb >= 10 else f"{gb:.1f} GB".replace(".", ",")


def drive_root(valor: str) -> Path:
    v = valor.strip()
    if len(v) == 1 and v.isalpha():
        v += ":"
    return Path(v + "\\") if len(v) == 2 and v[1] == ":" else Path(v)


def espaco_livre_gb(valor: str) -> float | None:
    base = drive_root(valor)
    while not base.exists() and base.parent != base:
        base = base.parent
    try:
        return shutil.disk_usage(base).free / 1024**3
    except OSError:
        return None


def listar_discos() -> list[str]:
    """Letras de unidade ("C:", "Y:"...) sem consultar cada volume.

    QStorageInfo.mountedVolumes() pergunta a cada disco (inclusive de rede desconectado) e
    chegou a travar a abertura da janela por 20 s; GetLogicalDrives só lê as letras.
    """
    if os.name == "nt":
        import ctypes
        mascara = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{chr(65 + i)}:" for i in range(26) if mascara >> i & 1]
    from PySide6.QtCore import QStorageInfo
    return sorted({v.rootPath()[:2].upper() for v in QStorageInfo.mountedVolumes()
                   if v.isValid() and len(v.rootPath()) >= 2 and v.rootPath()[1] == ":"})


def estimar_necessario_gb(source: Path) -> float:
    """Proxies + análise, pelo tamanho dos vídeos (antes do inventário não há durações)."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [d for d in dirnames if d.lower() != "proxies"]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    return estimate_proxy_gb(total / BYTES_POR_HORA_VIDEO * 3600.0)


def _pasta_inicial() -> str:
    return PASTA_INICIAL if os.path.isdir(PASTA_INICIAL) else str(Path.home())


class FormularioEvento(QWidget):
    iniciar = Signal()
    continuar = Signal()
    observacoes_mudaram = Signal()

    def __init__(self, s: Settings, runner: Runner, parent: QWidget | None = None,
                 area: str = "casamento"):
        super().__init__(parent)
        self.s = s
        self.area = area
        self.runner = runner
        self.source: Path | None = None
        self._livre_gb: float | None = None
        self._necessario_gb: float | None = None
        self._rodando = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # 1. pasta do evento
        c1 = Card("Pasta do evento", 1)
        linha = QHBoxLayout()
        linha.setSpacing(8)
        self.lbl_caminho = QLabel("Nenhuma pasta escolhida")
        self.lbl_caminho.setObjectName("caminho")
        self.lbl_caminho.setProperty("muted", True)
        self.btn_escolher = QPushButton("Escolher…")
        linha.addWidget(self.lbl_caminho, 1)
        linha.addWidget(self.btn_escolher)
        c1.body.addLayout(linha)
        info = QHBoxLayout()
        self.lbl_evento = QLabel("A pasta deve se chamar 'AAAA-MM-DD NOME DO EVENTO'.")
        self.lbl_evento.setProperty("muted", True)
        self.lbl_evento.setWordWrap(True)
        self.btn_continuar = QPushButton("Continuar projeto existente…")
        self.btn_continuar.setObjectName("link")
        self.btn_continuar.setCursor(Qt.PointingHandCursor)
        info.addWidget(self.lbl_evento, 1)
        info.addWidget(self.btn_continuar, 0, Qt.AlignTop)
        c1.body.addLayout(info)
        lay.addWidget(c1)

        # 2. disco de trabalho
        c2 = Card("Disco de trabalho", 2)
        linha = QHBoxLayout()
        linha.setSpacing(12)
        self.combo_disco = QComboBox()
        self.combo_disco.setEditable(True)
        self.combo_disco.setFixedWidth(120)
        self.combo_disco.addItems(listar_discos())
        self.combo_disco.setCurrentText(s.work_drive)
        self.lbl_espaco = QLabel()
        self.lbl_espaco.setProperty("muted", True)
        linha.addWidget(self.combo_disco)
        linha.addWidget(self.lbl_espaco, 1)
        c2.body.addLayout(linha)

        # 3. músicas, ao lado do disco
        c_mus = Card("Músicas", 3)
        self.campo_musicas = CampoPastaMusicas()
        self.campo_musicas.set_padrao(pasta_musicas_padrao(s, area))
        dica_mus = QLabel("Vale a pasta e todas as subpastas.")
        dica_mus.setProperty("muted", True)
        c_mus.body.addWidget(self.campo_musicas)
        c_mus.body.addWidget(dica_mus)
        self.card_musicas = c_mus
        disco_mus = QHBoxLayout()
        disco_mus.setSpacing(12)
        disco_mus.addWidget(c2, 1)
        disco_mus.addWidget(c_mus, 1)
        lay.addLayout(disco_mus)

        # 4. subpastas
        c3 = Card("O que é cada pasta", 4)
        dica = QLabel("Confira a sugestão. \"Dia\" só vale para pastas de outro dia (despedida, pré…).")
        dica.setProperty("muted", True)
        dica.setWordWrap(True)
        self.tabela = SubfolderTable()
        self.tabela.setMinimumHeight(150)
        c3.body.addWidget(dica)
        c3.body.addWidget(self.tabela, 1)
        lay.addWidget(c3, 1)

        # 5. entregas + 6. gemini, lado a lado
        dupla = QHBoxLayout()
        dupla.setSpacing(12)
        c4 = Card("Entregas", 5)
        self.card_entregas = c4
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.addWidget(QLabel("Episódios"), 0, 0)
        self.spin_episodios = QSpinBox()
        self.spin_episodios.setRange(1, 20)
        self.spin_episodios.setValue(4)
        self.spin_episodios.setFixedWidth(80)
        self.chk_livre = QCheckBox("Livre (a IA decide)")
        self.chk_livre.setChecked(True)
        self.chk_livre.toggled.connect(lambda on: self.spin_episodios.setEnabled(not on))
        self.spin_episodios.setEnabled(False)
        g.addWidget(self.spin_episodios, 0, 1)
        g.addWidget(self.chk_livre, 0, 2)
        derivs = QHBoxLayout()
        derivs.setSpacing(16)
        self.chk_trailer = QCheckBox("Trailer")
        self.chk_teaser = QCheckBox("Teaser")
        self.chk_stories = QCheckBox("Stories/Reels")
        for c in (self.chk_trailer, self.chk_teaser, self.chk_stories):
            c.setChecked(True)
            derivs.addWidget(c)
        derivs.addStretch(1)
        g.addLayout(derivs, 1, 0, 1, 3)
        g.setColumnStretch(3, 1)
        c4.body.addLayout(g)
        c4.body.addStretch(1)
        dupla.addWidget(c4, 1)

        c5 = Card("Gemini", 6)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.btn_gratis = QPushButton("Grátis")
        self.btn_pago = QPushButton("Pago")
        self.grupo_modo = QButtonGroup(self)
        for b, pos in ((self.btn_gratis, "esq"), (self.btn_pago, "dir")):
            b.setObjectName("segmento")
            b.setProperty("pos", pos)
            b.setCheckable(True)
            self.grupo_modo.addButton(b)
            seg.addWidget(b)
        seg.addStretch(1)
        self.btn_chave = QPushButton("Configurar chave")
        seg.addWidget(self.btn_chave)
        c5.body.addLayout(seg)
        from roteiro_ia.gemini.client import PRIVACY_NOTICE_PT
        self.lbl_privacidade = QLabel(PRIVACY_NOTICE_PT)
        self.lbl_privacidade.setObjectName("privacidade")
        self.lbl_privacidade.setWordWrap(True)
        self.lbl_pago = QLabel("Você confirma o custo estimado antes de qualquer envio ao Gemini.")
        self.lbl_pago.setProperty("muted", True)
        self.lbl_pago.setWordWrap(True)
        c5.body.addWidget(self.lbl_privacidade)
        c5.body.addWidget(self.lbl_pago)
        c5.body.addStretch(1)
        dupla.addWidget(c5, 1)
        lay.addLayout(dupla)

        # observações do editor (Casamento; a Formatura pode ligar com _card_observacoes)
        self.observacoes = Observacoes()
        self.card_observacoes = None
        if self.area == "casamento":
            lay.addWidget(self._card_observacoes())

        # 7. iniciar
        self.btn_iniciar = QPushButton("Iniciar")
        self.btn_iniciar.setObjectName("primario")
        self.btn_iniciar.setCursor(Qt.PointingHandCursor)
        self.btn_iniciar.setMinimumHeight(46)
        lay.addWidget(self.btn_iniciar)

        self.card_gemini = c5
        self.cards = [c1, c2, c3, c4, c5, c_mus]
        (self.btn_pago if s.gemini_mode == "pago" else self.btn_gratis).setChecked(True)
        self.atualizar_preco()
        self.grupo_modo.buttonToggled.connect(lambda *_: self._atualizar_modo())
        self.btn_escolher.clicked.connect(self._escolher)
        self.btn_continuar.clicked.connect(self.continuar.emit)
        self.btn_chave.clicked.connect(self._configurar_chave)
        self.btn_iniciar.clicked.connect(self.iniciar.emit)
        self.combo_disco.currentTextChanged.connect(lambda _t: self._atualizar_disco())
        self._atualizar_modo()
        self._atualizar_disco()
        self._atualizar_iniciar()

    # ------------------------------------------------------------ pasta do evento
    def _escolher(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Escolha a pasta do evento", _pasta_inicial())
        if d:
            self.set_event_folder(Path(d))

    def escolher_pasta(self, titulo: str) -> Path | None:
        d = QFileDialog.getExistingDirectory(self, titulo, _pasta_inicial())
        return Path(d) if d else None

    def _erro_evento(self, msg: str) -> None:
        self.lbl_evento.setText(msg)
        set_prop(self.lbl_evento, "estado", "erro")

    def set_event_folder(self, path: Path) -> bool:
        path = Path(path)
        self.source = None
        self._necessario_gb = None
        self.tabela.setRowCount(0)
        self.lbl_caminho.setText(str(path))
        set_prop(self.lbl_caminho, "muted", False)
        try:
            data = parse_event_name(path.name)
            pastas = list_subfolders(path)
        except EventNameError as e:
            self._erro_evento(str(e))
            pastas = None
        except OSError as e:
            self._erro_evento(f"Não consegui abrir a pasta '{path}': {e}")
            pastas = None
        if pastas is not None and not pastas:
            self._erro_evento("A pasta não tem subpastas de mídia (A, B, H4…).")
        elif pastas:
            nome = _PREFIXO_DATA.sub("", path.name).strip() or path.name
            self.lbl_evento.setText(f"{nome}  ·  {data:%d/%m/%Y}  ·  {len(pastas)} subpastas")
            set_prop(self.lbl_evento, "estado", "ok")
            self.tabela.load(pastas)
            self.source = path
            self._estimar(path)
        self._atualizar_disco()
        self._atualizar_iniciar()
        return self.source is not None

    def _estimar(self, path: Path) -> None:
        w = TarefaWorker(lambda _p: (path, estimar_necessario_gb(path)))
        w.resultado.connect(self._set_necessario)  # slot do widget: roda na thread principal
        self.runner.start(w)

    def _set_necessario(self, r: tuple) -> None:
        path, gb = r
        if self.source == path:
            self._necessario_gb = gb
            self._atualizar_disco()

    # ------------------------------------------------------------ disco
    def _atualizar_disco(self) -> None:
        livre = espaco_livre_gb(self.combo_disco.currentText())
        partes = [f"Livre: {fmt_gb(livre)}" if livre is not None else "Disco não encontrado"]
        if self._necessario_gb is not None:
            partes.append(f"Necessário: cerca de {fmt_gb(self._necessario_gb)}")
        elif self.source is not None:
            partes.append("Calculando o espaço necessário…")
        self.lbl_espaco.setText("   ·   ".join(partes))
        falta = livre is None or (self._necessario_gb is not None and livre < self._necessario_gb)
        set_prop(self.lbl_espaco, "estado", "erro" if falta else "")
        set_prop(self.lbl_espaco, "muted", not falta)

    # ------------------------------------------------------------ gemini
    def modo(self) -> str:
        return "pago" if self.btn_pago.isChecked() else "gratis"

    def atualizar_preco(self) -> None:
        """O modo pago só fica disponível com o preço por milhão de tokens configurado."""
        tem_preco = self.s.price_usd_per_mtok > 0
        self.btn_pago.setEnabled(tem_preco)
        self.btn_pago.setToolTip("" if tem_preco else
                                 "Defina o preço por milhão de tokens em Configurações para "
                                 "usar o modo pago.")
        if not tem_preco and self.btn_pago.isChecked():
            self.btn_gratis.setChecked(True)
            self._atualizar_modo()

    def _atualizar_modo(self) -> None:
        gratis = self.modo() == "gratis"
        self.lbl_privacidade.setVisible(gratis)
        self.lbl_pago.setVisible(not gratis)

    def _configurar_chave(self) -> None:
        from roteiro_ia.gemini.client import set_api_key
        chave, ok = QInputDialog.getText(
            self, "Chave do Gemini", "Cole a chave de API do Gemini (fica guardada no Windows):",
            QLineEdit.Password)
        if not ok:
            return
        if not chave.strip():
            QMessageBox.warning(self, "Chave do Gemini", "Nenhuma chave informada.")
            return
        try:
            set_api_key(chave.strip())
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Chave do Gemini", f"Não foi possível gravar a chave: {e}")
            return
        QMessageBox.information(self, "Chave do Gemini", "Chave gravada com segurança.")

    # ------------------------------------------------------------ observações do editor
    def _card_observacoes(self) -> Card:
        """Fica sempre habilitado (fora de self.cards): dá para escrever até com o projeto
        rodando ou esperando a cota; vale no próximo roteiro gerado."""
        c = Card("Observações do editor")
        linha = QHBoxLayout()
        linha.setSpacing(10)
        self.lbl_observacoes = QLabel()
        self.lbl_observacoes.setWordWrap(True)
        self.lbl_observacoes.setProperty("muted", True)
        self.btn_observacoes = QPushButton("Escrever observações…")
        linha.addWidget(self.lbl_observacoes, 1)
        linha.addWidget(self.btn_observacoes)
        c.body.addLayout(linha)
        self.btn_observacoes.clicked.connect(self.editar_observacoes)
        self.card_observacoes = c
        self._resumo_observacoes()
        return c

    def _resumo_observacoes(self) -> None:
        if self.card_observacoes is None:
            return
        n = self.observacoes.preenchidas()
        self.lbl_observacoes.setText(
            "Perfil do casal, o que não pode faltar, o que evitar e as músicas. A IA segue "
            "com prioridade." if n == 0 else
            f"{n} campo(s) preenchido(s): a IA segue com prioridade em todo roteiro deste evento.")

    def set_observacoes(self, o: Observacoes) -> None:
        self.observacoes = o
        self._resumo_observacoes()

    def editar_observacoes(self) -> None:
        from roteiro_ia.ui.observacoes import ObservacoesDialog
        dlg = ObservacoesDialog(self.observacoes, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.set_observacoes(dlg.observacoes())
        self.observacoes_mudaram.emit()

    # ------------------------------------------------------------ pedido
    def assignments(self) -> list[FolderAssignment]:
        return self.tabela.assignments()

    def build_request(self) -> ProjectRequest:
        if self.source is None:
            raise ValueError("Escolha a pasta do evento.")
        derivados = {d for c, d in ((self.chk_trailer, "trailer"), (self.chk_teaser, "teaser"),
                                    (self.chk_stories, "stories")) if c.isChecked()}
        return ProjectRequest(
            source_dir=self.source, work_drive=self.combo_disco.currentText().strip(),
            assignments=self.assignments(),
            n_episodios=None if self.chk_livre.isChecked() else self.spin_episodios.value(),
            derivados=derivados, gemini_mode=self.modo(), area=self.area,
            pasta_musicas=self.campo_musicas.pasta(), observacoes=self.observacoes)

    def load_request(self, req: ProjectRequest) -> None:
        """Preenche o formulário com um projeto salvo (Continuar projeto existente)."""
        self.combo_disco.setCurrentText(req.work_drive)
        por_pasta = {a.folder: a for a in req.assignments}
        for r in range(self.tabela.rowCount()):
            a = por_pasta.get(self.tabela.item(r, 0).text())
            if a is not None:
                if a.role == Role.outro_dia:
                    self.tabela.dia_edit(r).setText(a.day_label)
                self.tabela.set_role(r, a.role)
        self.chk_livre.setChecked(req.n_episodios is None)
        if req.n_episodios:
            self.spin_episodios.setValue(req.n_episodios)
        self.chk_trailer.setChecked("trailer" in req.derivados)
        self.chk_teaser.setChecked("teaser" in req.derivados)
        self.chk_stories.setChecked("stories" in req.derivados)
        (self.btn_pago if req.gemini_mode == "pago" else self.btn_gratis).setChecked(True)
        self.campo_musicas.set_pasta(req.pasta_musicas)
        self.set_observacoes(req.observacoes)

    # ------------------------------------------------------------ estado
    def set_rodando(self, rodando: bool) -> None:
        self._rodando = rodando
        for c in self.cards:
            c.setEnabled(not rodando)
        self.btn_iniciar.setText("Processando…" if rodando else "Iniciar")
        self._atualizar_iniciar()

    def _atualizar_iniciar(self) -> None:
        self.btn_iniciar.setEnabled(self.source is not None and not self._rodando)
