"""Abas Trilhas, Estilo e Configurações."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QProgressBar, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from roteiro_ia.config import Settings, save_settings
from roteiro_ia.ui.widgets import Banner, Card
from roteiro_ia.ui.worker import Runner, TarefaWorker, mensagem_erro


def _pagina(parent: QWidget | None = None) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget(parent)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(12)
    return w, lay


def _salvar(s: Settings, path: Path) -> str | None:
    try:
        save_settings(s, path)
    except Exception as e:  # noqa: BLE001
        return mensagem_erro(e)
    return None


class TrilhasTab(QWidget):
    def __init__(self, s: Settings, runner: Runner, parent: QWidget | None = None):
        super().__init__(parent)
        self.s, self.runner = s, runner
        self._contado = False
        _w, lay = _pagina(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_w)
        card = Card("Biblioteca de trilhas")
        self.lbl_info = QLabel()
        self.lbl_info.setProperty("muted", True)
        self.lbl_info.setWordWrap(True)
        self.lbl_total = QLabel("—")
        self.lbl_total.setObjectName("tituloApp")
        self.btn = QPushButton()
        self.btn.setObjectName("primario")
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.hide()
        self.lbl_atual = QLabel()
        self.lbl_atual.setProperty("muted", True)
        self.banner = Banner("erro")
        linha = QHBoxLayout()
        linha.addWidget(self.btn)
        linha.addStretch(1)
        for w in (self.lbl_info, self.lbl_total):
            card.body.addWidget(w)
        card.body.addLayout(linha)
        card.body.addWidget(self.barra)
        card.body.addWidget(self.lbl_atual)
        lay.addWidget(card)
        lay.addWidget(self.banner)
        lay.addStretch(1)
        self.btn.clicked.connect(self.atualizar)
        self.textos()

    def textos(self) -> None:
        self.btn.setText(f"Atualizar índice de músicas do {self.s.music_root.rstrip(chr(92))}")
        self.lbl_info.setText(
            f"O programa analisa BPM, clima e batidas de cada música de {self.s.music_root} "
            "(somente leitura) para sugerir trilhas no roteiro. Só as novas ou alteradas são "
            "analisadas.")

    def _idx(self):
        from roteiro_ia.music_index import MusicIndex
        return MusicIndex(Path(self.s.system_dir) / "trilhas.db", self.s)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._contado:
            self._contado = True
            self.contar()

    def contar(self) -> None:
        def fn(_p):
            with self._idx() as idx:
                return len(idx.all())
        w = TarefaWorker(fn)
        w.resultado.connect(self._set_total)
        w.erro.connect(self.banner.mostrar)
        self.runner.start(w)

    def atualizar(self) -> None:
        from roteiro_ia.music_index import update_index

        def fn(progress):
            with self._idx() as idx:
                n = update_index(self.s, idx, on_progress=progress)
                return n, len(idx.all())
        self.banner.limpar()
        self.btn.setEnabled(False)
        self.barra.setValue(0)
        self.barra.show()
        w = TarefaWorker(fn)
        w.progresso.connect(self._prog)
        w.resultado.connect(self._fim)
        w.erro.connect(self.banner.mostrar)
        w.terminou.connect(self._fim_tarefa)
        self.runner.start(w)

    # slots (métodos de widgets da thread principal: os sinais do worker chegam enfileirados)
    def _set_total(self, n: int) -> None:
        self.lbl_total.setText(f"{n} trilhas no índice")

    def _fim_tarefa(self, _status: str) -> None:
        self.btn.setEnabled(True)
        self.barra.hide()

    def _prog(self, i: int, total: int, nome: str) -> None:
        self.barra.setValue(int(i / total * 1000) if total else 1000)
        self.lbl_atual.setText(f"{i}/{total}  {nome}")

    def _fim(self, r) -> None:
        n, total = r
        self.lbl_total.setText(f"{total} trilhas no índice")
        self.lbl_atual.setText(f"Pronto: {n} trilha(s) nova(s) ou alterada(s) analisada(s).")


class EstiloTab(QWidget):
    def __init__(self, s: Settings, settings_path: Path, runner: Runner,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.s, self.settings_path, self.runner = s, Path(settings_path), runner
        _w, lay = _pagina(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_w)

        card = Card("Vídeos de referência (YouTube)")
        dica = QLabel("Links de vídeos publicados pela Fokuss. A IA estuda o ritmo, as aberturas e "
                      "os ganchos para seguir o mesmo estilo nos roteiros.")
        dica.setProperty("muted", True)
        dica.setWordWrap(True)
        card.body.addWidget(dica)
        self.lista = QListWidget()
        self.lista.addItems(s.style_urls)
        card.body.addWidget(self.lista, 1)
        linha = QHBoxLayout()
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.btn_add = QPushButton("Adicionar")
        self.btn_rem = QPushButton("Remover selecionado")
        linha.addWidget(self.edit_url, 1)
        linha.addWidget(self.btn_add)
        linha.addWidget(self.btn_rem)
        card.body.addLayout(linha)
        self.lbl_ignoradas = QLabel()
        self.lbl_ignoradas.setProperty("estado", "aviso")
        self.lbl_ignoradas.setWordWrap(True)
        card.body.addWidget(self.lbl_ignoradas)
        g = QHBoxLayout()
        self.btn_gerar = QPushButton("Gerar perfil")
        self.btn_gerar.setObjectName("primario")
        g.addWidget(self.btn_gerar)
        g.addStretch(1)
        card.body.addLayout(g)
        lay.addWidget(card, 1)

        self.banner = Banner("erro")
        lay.addWidget(self.banner)
        perfil = Card("Perfil de estilo atual")
        self.txt_resumo = QTextBrowser()
        self.txt_resumo.setMinimumHeight(120)
        perfil.body.addWidget(self.txt_resumo)
        lay.addWidget(perfil, 1)

        self.btn_add.clicked.connect(self.adicionar)
        self.edit_url.returnPressed.connect(self.adicionar)
        self.btn_rem.clicked.connect(self.remover)
        self.btn_gerar.clicked.connect(self.gerar)
        self._atualizar()

    def _urls(self) -> list[str]:
        return [self.lista.item(i).text() for i in range(self.lista.count())]

    def _gravar(self) -> None:
        self.s.style_urls = self._urls()
        err = _salvar(self.s, self.settings_path)
        if err:
            self.banner.mostrar(err)
        self._atualizar()

    def adicionar(self) -> None:
        url = self.edit_url.text().strip()
        if url and url not in self._urls():
            self.lista.addItem(url)
            self._gravar()
        self.edit_url.clear()

    def remover(self) -> None:
        for it in self.lista.selectedItems():
            self.lista.takeItem(self.lista.row(it))
        self._gravar()

    def _atualizar(self) -> None:
        from roteiro_ia.gemini.style import expand_playlists, load_style_profile
        videos, ignoradas = expand_playlists(self._urls())
        self.lbl_ignoradas.setText(
            "Estes links não são vídeos individuais (playlists?) e serão ignorados — adicione os "
            "vídeos individualmente:\n" + "\n".join(ignoradas) if ignoradas else "")
        self.lbl_ignoradas.setVisible(bool(ignoradas))
        self.btn_gerar.setEnabled(bool(videos))
        prof = load_style_profile(self.s)
        self.txt_resumo.setPlainText(prof.resumo if prof else
                                     "Ainda não há perfil. Adicione links e clique em Gerar perfil.")

    def gerar(self) -> None:
        from roteiro_ia.gemini.client import GeminiClient
        from roteiro_ia.gemini.style import build_style_profile
        s = self.s
        self.banner.limpar()
        self.btn_gerar.setEnabled(False)
        self.btn_gerar.setText("Gerando…")
        w = TarefaWorker(lambda _p: build_style_profile(GeminiClient(s), s))
        w.erro.connect(self.banner.mostrar)
        w.terminou.connect(self._fim_gerar)
        self.runner.start(w)

    def _fim_gerar(self, _status: str) -> None:
        self.btn_gerar.setText("Gerar perfil")
        self._atualizar()


class ConfigTab(QWidget):
    def __init__(self, s: Settings, settings_path: Path,
                 ao_salvar: Callable[[], None] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.s, self.settings_path, self._ao_salvar = s, Path(settings_path), ao_salvar
        _w, lay = _pagina(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_w)

        card = Card("Configurações")
        f = QFormLayout()
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(10)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ed_work = QLineEdit(s.work_drive)
        self.ed_e = QLineEdit(s.e_root)
        self.ed_g = QLineEdit(s.g_root)
        self.ed_music = QLineEdit(s.music_root)
        self.ed_cliente = QLineEdit(s.client_folder)
        self.sp_preco = QDoubleSpinBox()
        self.sp_preco.setRange(0.0, 1000.0)
        self.sp_preco.setDecimals(2)
        self.sp_preco.setPrefix("US$ ")
        self.sp_preco.setValue(s.price_usd_per_mtok)
        self.chk_copiar = QCheckBox("Copiar trilhas para o Y: (pasta TRILHAS do evento)")
        self.chk_copiar.setChecked(s.copy_music_to_work)
        for w in (self.ed_work, self.ed_e, self.ed_g, self.ed_music, self.ed_cliente,
                  self.sp_preco):
            w.setMaximumWidth(420)
        f.addRow("Disco de trabalho (padrão)", self.ed_work)
        f.addRow("Projetos do Premiere", self.ed_e)
        f.addRow("Exportações", self.ed_g)
        f.addRow("Biblioteca de trilhas", self.ed_music)
        f.addRow("Pasta do cliente", self.ed_cliente)
        f.addRow("Preço por milhão de tokens", self.sp_preco)
        f.addRow("", self.chk_copiar)
        card.body.addLayout(f)
        linha = QHBoxLayout()
        self.btn_salvar = QPushButton("Salvar")
        self.btn_salvar.setObjectName("primario")
        self.lbl_ok = QLabel()
        self.lbl_ok.setProperty("muted", True)
        linha.addWidget(self.btn_salvar)
        linha.addWidget(self.lbl_ok, 1)
        card.body.addSpacing(6)
        card.body.addLayout(linha)
        lay.addWidget(card)
        self.banner = Banner("erro")
        lay.addWidget(self.banner)
        lay.addStretch(1)
        self.btn_salvar.clicked.connect(self.salvar)

    def salvar(self) -> bool:
        self.banner.limpar()
        campos = {"work_drive": self.ed_work.text().strip(), "e_root": self.ed_e.text().strip(),
                  "g_root": self.ed_g.text().strip(), "music_root": self.ed_music.text().strip(),
                  "client_folder": self.ed_cliente.text().strip()}
        vazios = [k for k, v in campos.items() if not v]
        if vazios:
            self.banner.mostrar("Preencha todos os campos.")
            return False
        for k, v in campos.items():
            setattr(self.s, k, v)
        self.s.price_usd_per_mtok = self.sp_preco.value()
        self.s.copy_music_to_work = self.chk_copiar.isChecked()
        err = _salvar(self.s, self.settings_path)
        if err:
            self.banner.mostrar(err)
            return False
        self.lbl_ok.setText("Configurações salvas.")
        if self._ao_salvar:
            self._ao_salvar()
        return True
