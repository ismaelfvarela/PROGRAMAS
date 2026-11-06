"""Abas Trilhas, Estilo e Configurações."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QSpinBox, QTextBrowser, QVBoxLayout, QWidget)

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


ICONES_ESTILO = {"aguardando": "○", "analisando": "▶", "feito": "✔", "erro": "✖", "ignorado": "⚠"}


class _EstiloWorker(TarefaWorker):
    """TarefaWorker com o estado de cada vídeo: (url, estado, feitos, total)."""

    video = Signal(str, str, int, int)


def _canonica(url: str) -> str | None:
    from roteiro_ia.gemini.style import expand_playlists
    vids, _ign = expand_playlists([url])
    return vids[0] if vids else None


class EstiloTab(QWidget):
    def __init__(self, s: Settings, settings_path: Path, runner: Runner,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.s, self.settings_path, self.runner = s, Path(settings_path), runner
        self._estado: dict[str, str] = {}  # url canônica -> estado na última geração
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
        for u in s.style_urls:
            self._novo_item(u)
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
        self.barra = QProgressBar()
        self.barra.setTextVisible(True)
        self.barra.setFormat("%v de %m vídeos analisados")
        card.body.addWidget(self.barra)
        self.lbl_atual = QLabel()
        self.lbl_atual.setProperty("muted", True)
        self.lbl_atual.setWordWrap(True)
        card.body.addWidget(self.lbl_atual)
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
        return [self.lista.item(i).data(Qt.UserRole) for i in range(self.lista.count())]

    def _novo_item(self, url: str) -> None:
        it = QListWidgetItem()
        it.setData(Qt.UserRole, url)
        self.lista.addItem(it)
        self._pintar(it, "aguardando")

    @staticmethod
    def _pintar(it: QListWidgetItem, estado: str) -> None:
        it.setText(f"{ICONES_ESTILO.get(estado, '○')}  {it.data(Qt.UserRole)}")
        it.setToolTip(estado)

    def _icones(self) -> None:
        """Estado de cada item: cache → feito; link ignorado → ⚠; senão o da última geração."""
        from roteiro_ia.gemini.style import video_em_cache
        feitos = total = 0
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            url = it.data(Qt.UserRole)
            canon = _canonica(url)
            if canon is None:
                estado = "ignorado"
            else:
                total += 1
                if video_em_cache(self.s, url):
                    estado = "feito"
                else:
                    estado = self._estado.get(canon, "aguardando")
                    if estado == "analisando":
                        estado = "aguardando"  # a geração parou no meio
                feitos += estado == "feito"
            self._pintar(it, estado)
        self.barra.setRange(0, max(total, 1))
        self.barra.setValue(feitos)
        self.barra.setVisible(total > 0)

    def _gravar(self) -> None:
        self.s.style_urls = self._urls()
        err = _salvar(self.s, self.settings_path)
        if err:
            self.banner.mostrar(err)
        self._atualizar()

    def adicionar(self) -> None:
        url = self.edit_url.text().strip()
        if url and url not in self._urls():
            self._novo_item(url)
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
        self._icones()
        prof = load_style_profile(self.s)
        self.txt_resumo.setPlainText(prof.resumo if prof else
                                     "Ainda não há perfil. Adicione links e clique em Gerar perfil.")

    def gerar(self) -> None:
        s = self.s
        self.banner.limpar()
        self._estado.clear()
        self.btn_gerar.setEnabled(False)
        self.btn_gerar.setText("Gerando…")
        ultimo = [0, 0]  # (feitos, total) do último aviso — lido só na thread do worker

        def fn(_p):
            from roteiro_ia.gemini import client as gc
            from roteiro_ia.gemini import style as st

            def prog(url: str, estado: str, feitos: int, total: int) -> None:
                ultimo[:] = [feitos, total]
                w.video.emit(url, estado, feitos, total)
            try:
                return st.build_style_profile(gc.GeminiClient(s), s, on_progress=prog)
            except gc.QuotaPaused as e:
                feitos, total = ultimo
                tipo = "diária" if e.daily else "por minuto"
                raise RuntimeError(
                    f"Cota {tipo} gratuita do Gemini esgotada. Continue a partir de "
                    f"{e.resume_at.astimezone():%d/%m %H:%M}; faltam {total - feitos} de {total} "
                    "vídeos (os já analisados ficam guardados).") from e

        w = _EstiloWorker(fn)
        w.video.connect(self._on_video)
        w.erro.connect(self.banner.mostrar)
        w.terminou.connect(self._fim_gerar)
        self.runner.start(w)

    def _on_video(self, url: str, estado: str, feitos: int, total: int) -> None:
        self._estado[url] = estado
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            raw = it.data(Qt.UserRole)
            if raw == url or _canonica(raw) == url:
                self._pintar(it, estado)
        self.barra.setRange(0, max(total, 1))
        self.barra.setValue(feitos)
        self.barra.setVisible(total > 0)
        if estado == "analisando":
            self.lbl_atual.setText(f"Analisando: {url}")

    def _fim_gerar(self, _status: str) -> None:
        self.btn_gerar.setText("Gerar perfil")
        self.lbl_atual.setText("")
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
        self.sp_pacote = QSpinBox()
        self.sp_pacote.setRange(60, 3600)
        self.sp_pacote.setSingleStep(60)
        self.sp_pacote.setValue(s.gemini_pacote_max_s)
        self.sp_pacote.setToolTip("Quanto vídeo vai em cada chamada de análise ao Gemini. Diminua se "
                                  "a cota por minuto do plano gratuito pausar sempre.")
        self.chk_copiar = QCheckBox("Copiar trilhas para o Y: (pasta TRILHAS do evento)")
        self.chk_copiar.setChecked(s.copy_music_to_work)
        for w in (self.ed_work, self.ed_e, self.ed_g, self.ed_music, self.ed_cliente,
                  self.sp_preco, self.sp_pacote):
            w.setMaximumWidth(420)
        f.addRow("Disco de trabalho (padrão)", self.ed_work)
        f.addRow("Projetos do Premiere", self.ed_e)
        f.addRow("Exportações", self.ed_g)
        f.addRow("Biblioteca de trilhas", self.ed_music)
        f.addRow("Pasta do cliente", self.ed_cliente)
        f.addRow("Preço por milhão de tokens", self.sp_preco)
        f.addRow("Máx. de vídeo por chamada (s)", self.sp_pacote)
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
        self.s.gemini_pacote_max_s = self.sp_pacote.value()
        self.s.copy_music_to_work = self.chk_copiar.isChecked()
        err = _salvar(self.s, self.settings_path)
        if err:
            self.banner.mostrar(err)
            return False
        self.lbl_ok.setText("Configurações salvas.")
        if self._ao_salvar:
            self._ao_salvar()
        return True
