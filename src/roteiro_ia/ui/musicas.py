"""Aba Músicas a baixar: buscas no Artlist para cada peça do roteiro, as sugestões populares (para
ouvir) e a chegada dos downloads ao M:\\<ANO>\\<MM - MÊS>, numerados na sequência da pasta."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from roteiro_ia.db import ProjectDB
from roteiro_ia.downloads import (DOWNLOADS_DIAS, downloads_recentes, link_artlist, link_youtube,
                                  pasta_do_mes, pasta_downloads, proximo_numero,
                                  trazer_para_biblioteca)
from roteiro_ia.script.generate import Roteiro
from roteiro_ia.ui.widgets import Banner, Card, RolagemVertical

PEDIDO_BAIXADAS = ("Use nas peças as músicas baixadas para este evento (marcadas com ★ na lista "
                   "de trilhas), onde combinarem com o clima de cada peça; mantenha o resto.")
_ROTULO = {"episodio": "Episódio", "trailer": "Trailer", "teaser": "Teaser", "stories": "Stories"}


def _abrir_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class MusicasTab(QWidget):
    def __init__(self, projeto, s, parent: QWidget | None = None):
        super().__init__(parent)
        self.projeto = projeto
        self.s = s
        conteudo = QWidget()
        lay = QVBoxLayout(conteudo)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        topo = QLabel("A IA não enxerga o catálogo do Artlist: para cada peça ela sugere buscas. "
                      "Ouça, baixe as que quiser (vão para a pasta Downloads do Windows), traga para o "
                      "M: e refaça o roteiro com elas.")
        topo.setWordWrap(True)
        topo.setProperty("muted", True)
        lay.addWidget(topo)
        self.banner_ok = Banner("ok")
        self.banner_erro = Banner("erro")
        lay.addWidget(self.banner_ok)
        lay.addWidget(self.banner_erro)

        # 1. buscas por peça
        self.card_pecas = Card("Buscas para cada peça do roteiro", 1)
        self.pecas = QVBoxLayout()
        self.pecas.setSpacing(10)
        self.card_pecas.body.addLayout(self.pecas)
        lay.addWidget(self.card_pecas)

        # 2. downloads → M:
        c2 = Card("Trazer os downloads para o M:", 2)
        self.lbl_destino = QLabel()
        self.lbl_destino.setWordWrap(True)
        c2.body.addWidget(self.lbl_destino)
        self.lista = QListWidget()
        self.lista.setMinimumHeight(140)
        c2.body.addWidget(self.lista)
        linha = QHBoxLayout()
        linha.setSpacing(10)
        self.btn_atualizar = QPushButton("Atualizar lista")
        self.btn_trazer = QPushButton("Trazer as marcadas para o M:")
        self.btn_trazer.setObjectName("primario")
        self.btn_pasta = QPushButton("Abrir pasta do mês")
        linha.addWidget(self.btn_atualizar)
        linha.addWidget(self.btn_trazer)
        linha.addWidget(self.btn_pasta)
        linha.addStretch(1)
        c2.body.addLayout(linha)
        lay.addWidget(c2)

        # 3. refazer o roteiro
        c3 = Card("Usar no roteiro", 3)
        self.lbl_baixadas = QLabel()
        self.lbl_baixadas.setWordWrap(True)
        self.lbl_baixadas.setProperty("muted", True)
        self.btn_refazer = QPushButton("Refazer o roteiro com as baixadas")
        c3.body.addWidget(self.lbl_baixadas)
        c3.body.addWidget(self.btn_refazer, 0, Qt.AlignLeft)
        lay.addWidget(c3)
        lay.addStretch(1)

        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.addWidget(RolagemVertical(conteudo))

        self.btn_atualizar.clicked.connect(self.atualizar)
        self.btn_trazer.clicked.connect(self.trazer)
        self.btn_pasta.clicked.connect(self.abrir_pasta_do_mes)
        self.btn_refazer.clicked.connect(self.refazer)
        projeto.mudou.connect(lambda *_: self.atualizar() if self.isVisible() else None)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.atualizar()

    # ------------------------------------------------------------ dados
    def _roteiro(self) -> Roteiro | None:
        try:
            p = self.projeto._paths()
        except ValueError:
            return None
        if not Path(p.db_path).is_file():
            return None
        try:
            with ProjectDB(p.db_path, self.s) as db:
                txt = db.latest_roteiro()
        except Exception:  # noqa: BLE001 - banco ocupado/antigo: só não mostra
            return None
        return Roteiro.model_validate_json(txt) if txt else None

    def atualizar(self) -> None:
        self._mostrar_pecas(self._roteiro())
        destino = pasta_do_mes(self.s.music_root)
        self.lbl_destino.setText(
            f"Destino: {destino}  ·  a próxima música recebe o número "
            f"{proximo_numero(destino):02d}. Downloads dos últimos {DOWNLOADS_DIAS} dias "
            f"(pasta {pasta_downloads()}); marque os que são deste evento:")
        self.lista.clear()
        for f in downloads_recentes(pasta_downloads()):
            quando = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M")
            it = QListWidgetItem(f"{f.name}   ({quando})")
            it.setData(Qt.UserRole, str(f))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.lista.addItem(it)
        if self.lista.count() == 0:
            vazio = QListWidgetItem("Nenhuma música baixada nos últimos dias.")
            vazio.setFlags(Qt.NoItemFlags)
            self.lista.addItem(vazio)
        baixadas = self._observacoes().baixadas
        self.lbl_baixadas.setText(
            "Nenhuma música baixada para este evento ainda." if not baixadas else
            f"{len(baixadas)} música(s) baixada(s) para este evento: "
            + "; ".join(Path(b).name for b in baixadas)
            + ". Elas vão para a IA marcadas como preferidas (★).")
        self.btn_refazer.setEnabled(bool(baixadas) and self.projeto._req is not None
                                    and not self.projeto.rodando)

    def _observacoes(self):
        return self.projeto.form.observacoes

    def _mostrar_pecas(self, r: Roteiro | None) -> None:
        while self.pecas.count():
            it = self.pecas.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if r is None:
            msg = QLabel("O roteiro ainda não foi gerado para o projeto aberto.")
            msg.setProperty("muted", True)
            self.pecas.addWidget(msg)
            return
        ordem = {"episodio": 0, "trailer": 1, "teaser": 2, "stories": 3}
        for pc in sorted(r.pecas, key=lambda x: (ordem.get(x.tipo, 9), x.numero or 0)):
            self.pecas.addWidget(self._linha_peca(pc))

    def _linha_peca(self, pc) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 6)
        v.setSpacing(6)
        rot = _ROTULO.get(pc.tipo, pc.tipo) + (f" {pc.numero}" if pc.numero else "")
        clima = "; ".join(dict.fromkeys(t.clima for t in pc.trilhas if t.clima))
        titulo = QLabel(f"<b>{rot} — {pc.titulo}</b>" + (f"  ·  clima: {clima}" if clima else ""))
        titulo.setWordWrap(True)
        v.addWidget(titulo)
        da_bib = [Path(t.path).name for t in pc.trilhas if t.origem == "biblioteca" and t.path]
        if da_bib:
            lb = QLabel("Já na biblioteca: " + "; ".join(da_bib))
            lb.setWordWrap(True)
            lb.setProperty("muted", True)
            v.addWidget(lb)
        botoes = QHBoxLayout()
        botoes.setSpacing(8)
        for termo in pc.termos_musicbed[:3]:
            b = QPushButton(f"Artlist: {termo}")
            b.setToolTip(link_artlist(termo))
            b.clicked.connect(lambda _=False, t=termo: _abrir_url(link_artlist(t)))
            botoes.addWidget(b)
        for t in pc.trilhas:
            if t.origem == "popular":
                b = QPushButton(f"Ouvir: {t.titulo}")
                b.setToolTip("Música popular: precisa de licença. Abre a busca no YouTube só para ouvir.")
                b.clicked.connect(lambda _=False, q=t.titulo: _abrir_url(link_youtube(q)))
                botoes.addWidget(b)
        botoes.addStretch(1)
        v.addLayout(botoes)
        return w

    # ------------------------------------------------------------ ações
    def _marcados(self) -> list[Path]:
        out = []
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            if it.data(Qt.UserRole) and it.checkState() == Qt.Checked:
                out.append(Path(it.data(Qt.UserRole)))
        return out

    def trazer(self) -> None:
        self.banner_ok.limpar()
        self.banner_erro.limpar()
        arquivos = self._marcados()
        if not arquivos:
            self.banner_erro.mostrar("Marque na lista as músicas baixadas para este evento.")
            return
        try:
            novos = trazer_para_biblioteca(arquivos, self.s.music_root)
        except (OSError, ValueError) as e:
            self.banner_erro.mostrar(f"Não consegui trazer as músicas para o M:: {e}")
            self.atualizar()
            return
        if self.projeto._req is not None:
            o = self._observacoes()
            atuais = list(o.baixadas)
            atuais += [str(n) for n in novos if str(n) not in atuais]
            self.projeto.form.set_observacoes(o.model_copy(update={"baixadas": atuais}))
            self.projeto.salvar_observacoes()
        self.banner_ok.mostrar("No M:: " + "; ".join(n.name for n in novos)
                               + (". Agora use \"Refazer o roteiro com as baixadas\"."
                                  if self.projeto._req is not None else
                                  ". Abra o projeto para usá-las no roteiro."))
        self.atualizar()

    def abrir_pasta_do_mes(self) -> None:
        d = pasta_do_mes(self.s.music_root)
        alvo = d if d.is_dir() else d.parent
        if not alvo.is_dir():
            self.banner_erro.mostrar(f"A pasta ainda não existe: {d}. Ela é criada ao trazer a "
                                     "primeira música do mês.")
            return
        os.startfile(str(alvo))  # noqa: S606

    def refazer(self) -> None:
        self.projeto.ajustar(PEDIDO_BAIXADAS)
