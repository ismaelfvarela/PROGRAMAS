"""Abas Trilhas, Estilo e Configurações."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
                               QSpinBox, QTextBrowser, QVBoxLayout, QWidget)

from roteiro_ia.config import Settings, save_settings, set_urls_estilo, urls_estilo
from roteiro_ia.ui.widgets import Banner, Card, ControlesProcesso
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
        self._w: TarefaWorker | None = None  # indexação em andamento
        self._feitas = 0
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
        self.controles = ControlesProcesso()
        self.btn = self.controles.btn_play
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.hide()
        self.lbl_atual = QLabel()
        self.lbl_atual.setProperty("muted", True)
        self.banner = Banner("erro")
        for w in (self.lbl_info, self.lbl_total):
            card.body.addWidget(w)
        card.body.addWidget(self.controles)
        card.body.addWidget(self.barra)
        card.body.addWidget(self.lbl_atual)
        lay.addWidget(card)
        lay.addWidget(self.banner)
        lay.addStretch(1)
        self.controles.iniciar.connect(self.atualizar)
        self.controles.continuar.connect(self._continuar)
        self.controles.pausar.connect(lambda: self._w and self._w.controle.pausar())
        self.controles.parar.connect(lambda: self._w and self._w.controle.parar())
        self.textos()

    def textos(self) -> None:
        self.controles.set_textos(
            f"Atualizar índice de músicas do {self.s.music_root.rstrip(chr(92))}",
            "Atualizando o índice…")
        self.lbl_info.setText(
            f"O programa analisa cada música de {self.s.music_root} (somente leitura) pela "
            "batida (BPM, tempos) e pela melodia: se tem voz ou é só tocada, onde a voz entra, "
            "tonalidade, clima e instrumentos (modelos locais na GPU). Só as novas, alteradas "
            "ou com análise incompleta são analisadas.")

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
            from roteiro_ia.music_index import resumo_indice
            with self._idx() as idx:
                return resumo_indice(idx)
        w = TarefaWorker(fn)
        w.resultado.connect(self._set_total)
        w.erro.connect(self.banner.mostrar)
        self.runner.start(w)

    def atualizar(self) -> None:
        from roteiro_ia.music_index import resumo_indice, update_index

        def fn(progress):
            with self._idx() as idx:
                n = update_index(self.s, idx, on_progress=progress)
                return n, resumo_indice(idx)
        self.banner.limpar()
        self.barra.setValue(0)
        self.barra.show()
        self._feitas = 0
        w = TarefaWorker(fn, controlavel=True)
        w.progresso.connect(self._prog)
        w.resultado.connect(self._fim)
        w.erro.connect(self.banner.mostrar)
        w.terminou.connect(self._fim_tarefa)
        w.estado.connect(self._on_estado)
        self._w = w
        self.controles.set_estado("rodando")
        self.runner.start(w)

    def _continuar(self) -> None:
        if self._w is not None:
            self._w.controle.continuar()
        else:  # depois de um Parar: só as que faltam são analisadas
            self.atualizar()

    def _on_estado(self, estado: str) -> None:
        if self.sender() is self._w and estado in ("rodando", "pausando", "pausado", "parando"):
            self.controles.set_estado(estado)

    # slots (métodos de widgets da thread principal: os sinais do worker chegam enfileirados)
    def _set_total(self, resumo) -> None:
        total, completas = resumo
        self.lbl_total.setText(f"{total} trilhas no índice ({completas} com análise completa)")

    def _fim_tarefa(self, status: str) -> None:
        self._w = None
        self.barra.hide()
        if status == "parado":
            self.controles.set_estado("parado")
            self.lbl_atual.setText(f"Parado: {self._feitas} trilha(s) analisada(s) ficam no índice; "
                                   "as demais ficam para o próximo Continuar.")
        else:
            self.controles.set_estado("ocioso")

    def _prog(self, i: int, total: int, nome: str) -> None:
        self.barra.setValue(int(i / total * 1000) if total else 1000)
        self.lbl_atual.setText(f"{i}/{total}  {nome}")

    def _fim(self, r) -> None:
        n, resumo = r
        self._feitas = n
        self._set_total(resumo)
        self.lbl_atual.setText(f"Pronto: {n} trilha(s) nova(s) ou alterada(s) analisada(s).")


ICONES_ESTILO = {"aguardando": "○", "analisando": "▶", "feito": "✔", "erro": "✖", "ignorado": "⚠"}
# Cor de cada ícone de estado (mesma paleta do tema).
CORES_ESTILO = {"aguardando": "#9a9aa0", "analisando": "#d9774a", "feito": "#5fb37c",
                "erro": "#e06a5f", "ignorado": "#e0b04f"}
_CACHE_ICONES: dict[str, QIcon] = {}


def _icone_estado(estado: str) -> QIcon:
    """Ícone colorido (glifo desenhado num pixmap) para o estado do vídeo."""
    if estado not in _CACHE_ICONES:
        pm = QPixmap(18, 18)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        f = QFont("Segoe UI Symbol", 11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(CORES_ESTILO.get(estado, "#9a9aa0")))
        p.drawText(pm.rect(), Qt.AlignCenter, ICONES_ESTILO.get(estado, "○"))
        p.end()
        _CACHE_ICONES[estado] = QIcon(pm)
    return _CACHE_ICONES[estado]


class _EstiloWorker(TarefaWorker):
    """TarefaWorker com o estado de cada vídeo: (url, estado, feitos, total)."""

    video = Signal(str, str, int, int)


def _canonica(url: str) -> str | None:
    from roteiro_ia.gemini.style import expand_playlists
    vids, _ign = expand_playlists([url])
    return vids[0] if vids else None


class EstiloTab(QWidget):
    def __init__(self, s: Settings, settings_path: Path, runner: Runner,
                 parent: QWidget | None = None, area: str = "casamento"):
        super().__init__(parent)
        self.s, self.settings_path, self.runner = s, Path(settings_path), runner
        self.area = area
        self._estado: dict[str, str] = {}  # url canônica -> estado na última geração
        self._w: TarefaWorker | None = None  # geração em andamento
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
        for u in urls_estilo(s, area):
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
        self.controles = ControlesProcesso("Gerar perfil", texto_rodando="Gerando…")
        self.btn_gerar = self.controles.btn_play
        card.body.addWidget(self.controles)
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
        self.controles.iniciar.connect(self.gerar)
        self.controles.continuar.connect(self._continuar)
        self.controles.pausar.connect(lambda: self._w and self._w.controle.pausar())
        self.controles.parar.connect(lambda: self._w and self._w.controle.parar())
        self._atualizar()

    def _kw_area(self) -> dict:
        """`area` só vai quando não é o Casamento (chamadas do Casamento ficam como sempre foram)."""
        return {} if self.area == "casamento" else {"area": self.area}

    def _urls(self) -> list[str]:
        return [self.lista.item(i).data(Qt.UserRole) for i in range(self.lista.count())]

    def _novo_item(self, url: str) -> None:
        it = QListWidgetItem()
        it.setData(Qt.UserRole, url)
        self.lista.addItem(it)
        self._pintar(it, "aguardando")

    @staticmethod
    def _pintar(it: QListWidgetItem, estado: str) -> None:
        it.setIcon(_icone_estado(estado))
        it.setText(str(it.data(Qt.UserRole)))
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
                if video_em_cache(self.s, url, **self._kw_area()):
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
        set_urls_estilo(self.s, self.area, self._urls())
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
        self.controles.set_pode_iniciar(bool(videos))
        self._icones()
        prof = load_style_profile(self.s, **self._kw_area())
        self.txt_resumo.setPlainText(prof.resumo if prof else
                                     "Ainda não há perfil. Adicione links e clique em Gerar perfil.")

    def gerar(self) -> None:
        s = self.s
        kw = self._kw_area()
        self.banner.limpar()
        self._estado.clear()
        ultimo = [0, 0]  # (feitos, total) do último aviso — lido só na thread do worker

        def fn(_p):
            from roteiro_ia.gemini import client as gc
            from roteiro_ia.gemini import style as st

            def prog(url: str, estado: str, feitos: int, total: int) -> None:
                ultimo[:] = [feitos, total]
                w.video.emit(url, estado, feitos, total)
            try:
                return st.build_style_profile(gc.GeminiClient(s), s, on_progress=prog, **kw)
            except gc.QuotaPaused as e:
                feitos, total = ultimo
                tipo = "diária" if e.daily else "por minuto"
                raise RuntimeError(
                    f"Cota {tipo} gratuita do Gemini esgotada. Continue a partir de "
                    f"{e.resume_at.astimezone():%d/%m %H:%M}; faltam {total - feitos} de {total} "
                    "vídeos (os já analisados ficam guardados).") from e

        w = _EstiloWorker(fn, controlavel=True)
        w.video.connect(self._on_video)
        w.erro.connect(self.banner.mostrar)
        w.terminou.connect(self._fim_gerar)
        w.estado.connect(self._on_estado)
        self._w = w
        self.controles.set_estado("rodando")
        self.runner.start(w)

    def _continuar(self) -> None:
        if self._w is not None:
            self._w.controle.continuar()
        else:  # depois de um Parar: os vídeos já analisados vêm do cache
            self.gerar()

    def _on_estado(self, estado: str) -> None:
        if self.sender() is self._w and estado in ("rodando", "pausando", "pausado", "parando"):
            self.controles.set_estado(estado)

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

    def _fim_gerar(self, status: str) -> None:
        self._w = None
        self.controles.set_estado("parado" if status == "parado" else "ocioso")
        self.lbl_atual.setText("Parado: os vídeos já analisados ficam guardados."
                               if status == "parado" else "")
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
