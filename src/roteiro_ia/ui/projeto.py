"""Aba Projeto: formulário (esquerda) + andamento (direita) e o controle das execuções."""
from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QDialog, QMenu, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from roteiro_ia import proc, recentes
from roteiro_ia.areas import area_por_id
from roteiro_ia.config import Settings
from roteiro_ia.models import Role
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import PROJECT_FILE, Pipeline, ProjectRequest
from roteiro_ia.premiere.job import ler_resultado, pedido_pendente, pedir_ao_premiere, write_job
from roteiro_ia.ui.fila import FilaProjetos
from roteiro_ia.ui.status import StatusPanel
from roteiro_ia.ui.widgets import RolagemVertical
from roteiro_ia.ui.worker import PipelineWorker, Runner

# (pedido, settings, eventos) -> objeto com prepare/run/revise/close/resume_at/db
PipelineFactory = Callable[[ProjectRequest, Settings, Callable], object]
MARGEM_RETOMADA_MS = 5_000
TEXTO_PAUSA_COTA = "Pausado pela cota do Gemini — continua sozinho"
TEXTO_PARADO = ("Parado. O que já foi feito está guardado: clique em Continuar para seguir de "
                "onde parou.")
TEXTO_PRIORIDADE = ("Pausado: o projeto {nome} tem a prioridade. Este continua sozinho quando "
                    "ele terminar.")
TEXTO_COMECANDO = "Começando…"
TEXTO_VEZ = "Retomando: chegou a vez deste projeto."
TEXTO_FORA_DA_FILA = "Tirado da fila. Clique em Iniciar quando quiser processar."


def fmt_usd(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class AjusteDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Pedir ajuste no roteiro")
        self.resize(560, 320)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        lay.addWidget(QLabel("O que você quer mudar? Escreva como pediria a um colega."))
        self.texto = QPlainTextEdit()
        self.texto.setPlaceholderText("Ex.: usar mais os votos no episódio 2 e começar o trailer "
                                      "com o drone da igreja.")
        lay.addWidget(self.texto, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Gerar de novo")
        bb.button(QDialogButtonBox.Ok).setObjectName("primario")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def pedido(self) -> str:
        return self.texto.toPlainText().strip()


PREMIERE_CONFERIR_MS = 3000
PREMIERE_AVISO_S = 90       # sem ninguém pegar o pedido nesse tempo: avisa o editor
PREMIERE_DESISTIR_S = 40 * 60


def premiere_aberto() -> bool:
    """O Premiere Pro está rodando (o pedido é atendido pelo painel sem abrir outro)."""
    if os.name != "nt":
        return False
    try:
        r = proc.run(["tasklist", "/FI", "IMAGENAME eq Adobe Premiere Pro.exe", "/NH"],
                     text=True, errors="replace", timeout=10, controlado=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return "adobe premiere pro.exe" in r.stdout.lower()


def premiere_exe() -> Path | None:
    """O Premiere Pro instalado mais novo (pasta "Adobe Premiere Pro <ano>")."""
    raiz = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Adobe"
    try:
        achados = sorted(raiz.glob("Adobe Premiere Pro*/Adobe Premiere Pro.exe"), reverse=True)
    except OSError:
        return None
    return achados[0] if achados else None


class ProjetoTab(QWidget):
    mudou = Signal()  # pausa da cota começou/terminou (a barra geral conta como processo)

    def __init__(self, s: Settings, settings_path: Path, runner: Runner,
                 factory: PipelineFactory | None = None, parent: QWidget | None = None,
                 area: str = "casamento", fila=None):
        super().__init__(parent)
        self.s = s
        self.settings_path = Path(settings_path)
        self.runner = runner
        self.area = area
        # sem fila compartilhada, a própria: começa na hora (um projeto só)
        self.fila = fila if fila is not None else FilaProjetos(self)
        self._factory = factory or self._pipeline_padrao
        self._req: ProjectRequest | None = None
        self._custo = 0.0
        self._resume_at: datetime | None = None
        self._ultima: tuple[str, bool, str | None] = ("run", False, None)
        self._continuar_com: tuple[str, bool, str | None] | None = None  # depois de um Parar
        self._worker: PipelineWorker | None = None
        self._pendente: tuple[str, bool, str | None, bool] | None = None  # esperando a vez
        self._suspenso_fila = False  # worker pausado porque outro projeto tem a prioridade
        self.rodando = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        self.form = area_por_id(area).formulario(s, runner, area=area)
        self.status = StatusPanel()
        # a Formatura já rola o próprio formulário; o do Casamento e o andamento rolam aqui
        lay.addWidget(self.form if area != "casamento" else RolagemVertical(self.form), 55)
        lay.addWidget(RolagemVertical(self.status), 45)

        # acompanha o pedido ao Premiere até o painel/serviço gravar o resultado
        self.timer_premiere = QTimer(self)
        self.timer_premiere.setInterval(PREMIERE_CONFERIR_MS)
        self.timer_premiere.timeout.connect(self._conferir_premiere)
        self._pedido_premiere: tuple[str, str, float, bool] | None = None
        self.timer_retomar = QTimer(self)
        self.timer_retomar.setSingleShot(True)
        self.timer_retomar.timeout.connect(self._retomar)

        self.form.iniciar.connect(self.iniciar)
        self.form.continuar.connect(self.continuar_existente)
        self.form.observacoes_mudaram.connect(self.salvar_observacoes)
        self.status.btn_pdf.clicked.connect(self.abrir_pdf)
        self.status.btn_premiere.clicked.connect(self.abrir_premiere)
        self.status.btn_puxar.clicked.connect(self.puxar_roteiro)
        self.status.btn_pasta_videos.clicked.connect(self.abrir_pasta_videos)
        self.status.btn_pasta_projeto.clicked.connect(self.abrir_pasta_projeto)
        self.status.btn_ajuste.clicked.connect(self.pedir_ajuste)
        self.controles = self.status.controles
        self.controles.pausar.connect(self.pausar)
        self.controles.parar.connect(self.parar)
        self.controles.continuar.connect(self.continuar)
        self.status.btn_cota_continuar.clicked.connect(self.continuar_agora)
        self.status.btn_cota_parar.clicked.connect(self.cancelar_retomada)
        self.status.btn_cota_chat.clicked.connect(self.roteiro_pelo_chat)
        self.status.btn_chat.clicked.connect(self.roteiro_pelo_chat)
        self.status.btn_tirar_fila.clicked.connect(self.tirar_da_fila)

    # atalhos usados pela janela e pelos testes
    @property
    def btn_iniciar(self):
        return self.form.btn_iniciar

    def set_event_folder(self, path: Path) -> bool:
        return self.form.set_event_folder(path)

    def _pipeline_padrao(self, req: ProjectRequest, s: Settings, eventos) -> Pipeline:
        fab = area_por_id(self.area).pipeline or Pipeline
        return fab(req, s, None, None, eventos, settings_path=self.settings_path)

    # ------------------------------------------------------------ execução
    def iniciar(self) -> None:
        if self.rodando:
            return
        area = area_por_id(self.area)
        if not area.pode_iniciar:  # ex.: abrir_existente chama iniciar() direto
            self.status.banner_erro.mostrar(area.aviso_iniciar)
            return
        # o formulário da área pode exigir mais que a pasta (ex.: Formatura: formatura e turma);
        # vale também quando iniciar() vem direto do "Continuar projeto existente"
        motivo = getattr(self.form, "motivo_bloqueio", lambda: "")()
        if motivo:
            self.status.banner_erro.mostrar(motivo)
            return
        try:
            req = self.form.build_request()
        except ValueError as e:
            self.status.banner_erro.mostrar(str(e))
            return
        if all(a.role == Role.ignorar for a in req.assignments):
            self.status.banner_erro.mostrar("Marque pelo menos uma pasta com mídia (todas estão "
                                            "como \"Ignorar\").")
            return
        self._req = req
        self.status.painel_premiere.show()
        recentes.registrar(self.s, req.source_dir, req.work_drive, area=self.area)
        self.timer_retomar.stop()
        self.status.limpar_avisos()
        self.status.etapas.reset()
        self.status.log_line(f"Evento: {req.source_dir}")
        self._start("prepare" if req.gemini_mode == "pago" else "run")

    def _start(self, acao: str, aprovado: bool = False, pedido: str | None = None,
               refazer_falhas: bool = True) -> None:
        """Pede a vez na fila; `comecar()` roda quando for a vez deste projeto."""
        if acao != "prepare":
            self._ultima = (acao, aprovado, pedido)
        self._continuar_com = (acao, aprovado, pedido)
        self._pendente = (acao, aprovado, pedido, refazer_falhas)
        self._set_rodando(True)
        self.fila.pedir(self)

    # ------------------------------------------------------------ cliente da fila
    def nome_fila(self) -> str:
        return self._req.source_dir.name if self._req is not None else ""

    def comecar(self) -> None:
        if self._pendente is None:
            return
        acao, aprovado, pedido, refazer_falhas = self._pendente
        self._pendente = None
        self.status.btn_tirar_fila.hide()
        req, s, factory = self._req, self.s, self._factory
        w = PipelineWorker(lambda eventos: factory(req, s, eventos), acao=acao,
                           aprovado_custo=aprovado, pedido=pedido, refazer_falhas=refazer_falhas)
        w.progresso.connect(self.status.on_progresso)
        w.estados.connect(self.status.on_estados)
        w.log.connect(self.status.on_log)
        w.custo.connect(self._on_custo)
        w.retomar_em.connect(self._on_retomar_em)
        w.erro.connect(self._on_erro)
        w.terminou.connect(self._on_terminou)
        w.estado.connect(self._on_estado)
        self._worker = w
        self._set_rodando(True)
        self.status.banner_pausa.limpar()
        self.status.banner_erro.limpar()
        self.status.acoes_cota.hide()
        self.status.lbl_mensagem.setText(TEXTO_COMECANDO)  # apaga "Na fila…" e afins
        self.controles.set_estado("rodando")
        self.runner.start(w)
        self.mudou.emit()

    def suspender(self) -> None:
        if self._worker is None:
            return
        self._suspenso_fila = True
        self._worker.controle.pausar()
        dono = self.fila.ativo()
        nome = dono.nome_fila() if dono is not None else "outro projeto"
        texto = TEXTO_PRIORIDADE.format(nome=nome)
        self.status.lbl_mensagem.setText(texto)
        self.status.log_line(texto)

    def retomar_suspenso(self) -> None:
        self._suspenso_fila = False
        if self._worker is not None:
            self.status.lbl_mensagem.setText(TEXTO_VEZ)
            self.status.log_line(TEXTO_VEZ)
            self.controles.set_estado("rodando")
            self._worker.controle.continuar()

    def controle_execucao(self):
        """Controle do worker em andamento (None se nada roda); a janela usa no Continuar tudo."""
        return self._worker.controle if self._worker is not None else None

    def mostrar_espera(self, texto: str | None) -> None:
        if texto is None:
            self.status.btn_tirar_fila.hide()
            return
        self.status.lbl_mensagem.setText(texto)
        self.status.btn_tirar_fila.show()

    def tirar_da_fila(self) -> None:
        """Desiste de esperar a vez: sai da fila e destrava o formulário."""
        if self._pendente is None or self._worker is not None:
            return
        self._pendente = None
        self.fila.sair(self)
        self.status.btn_tirar_fila.hide()
        self._set_rodando(False)
        self.controles.set_estado("ocioso")
        self.status.lbl_mensagem.setText(TEXTO_FORA_DA_FILA)
        self.status.log_line("Tirado da fila pelo editor.")
        self.mudou.emit()

    def _set_rodando(self, on: bool) -> None:
        self.rodando = on
        self.form.set_rodando(on)
        self.status.btn_ajuste.setEnabled(not on)

    # ------------------------------------------------------------ Play / Pause / Stop
    def em_pausa_cota(self) -> bool:
        return self.timer_retomar.isActive()

    def _on_estado(self, estado: str) -> None:
        if self.sender() is not self._worker:
            return  # aviso atrasado de uma execução anterior
        if estado == "pausado" and self._suspenso_fila:
            self.controles.set_estado(estado, "Pausado: outro projeto tem a prioridade")
        elif estado in ("rodando", "pausando", "pausado", "parando"):
            self.controles.set_estado(estado)

    def pausar(self) -> None:
        if self._worker is not None:
            self._worker.controle.pausar()

    def parar(self) -> None:
        if self._worker is not None:
            self._worker.controle.parar()
        elif self.em_pausa_cota():
            self.cancelar_retomada()
        elif self._pendente is not None:
            self.tirar_da_fila()

    def continuar(self) -> None:
        """▶ Continuar: solta a pausa; na pausa da cota tenta já; depois de um Parar roda de
        novo a mesma ação (o pipeline retoma pelo banco, sem refazer o que foi gravado)."""
        if self._worker is not None:
            if self._suspenso_fila:  # a prioridade é de outro projeto: a fila solta sozinha
                self.status.log_line("Este projeto continua sozinho quando chegar a vez dele.")
                return
            self._worker.controle.continuar()
        elif self.em_pausa_cota():
            self.continuar_agora()
        elif self._req is not None and self._continuar_com is not None:
            self.status.limpar_avisos()
            self.status.log_line("Continuando de onde parou.")
            acao, aprovado, pedido = self._continuar_com
            self._start(acao, aprovado, pedido)

    def continuar_agora(self) -> None:
        """Pausa da cota: tenta já (se a cota ainda estiver esgotada, volta a pausar)."""
        self.timer_retomar.stop()
        self.status.acoes_cota.hide()
        self.status.banner_pausa.limpar()
        self._retomar()
        self.mudou.emit()

    def cancelar_retomada(self) -> None:
        """Pausa da cota: Parar cancela a retomada automática."""
        self.timer_retomar.stop()
        self.status.acoes_cota.hide()
        self.status.banner_pausa.limpar()
        self._set_rodando(False)
        self.controles.set_estado("parado")
        self.status.lbl_mensagem.setText(TEXTO_PARADO)
        self.status.log_line("Retomada automática cancelada pelo editor.")
        self.fila.sair(self)
        self.mudou.emit()

    def _on_custo(self, custo: float) -> None:
        self._custo = custo

    def _on_retomar_em(self, quando) -> None:
        self._resume_at = quando

    def _on_erro(self, msg: str) -> None:
        self.status.banner_erro.mostrar(msg)
        self.status.log_line(f"Erro: {msg}")

    def confirmar_custo(self, custo: float) -> bool:
        r = QMessageBox.question(self, "Modo pago do Gemini",
                                 f"Custo estimado: US$ {fmt_usd(custo)}. Continuar?",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes

    def _on_terminou(self, status: str) -> None:
        if self.sender() is not None and self.sender() is not self._worker:
            return
        self._worker = None
        self._suspenso_fila = False
        if status == "parado":
            self._set_rodando(False)
            self.controles.set_estado("parado")
            self.status.lbl_mensagem.setText(TEXTO_PARADO)
            self.status.log_line("Parado pelo editor.")
            self.fila.sair(self)
            self.mudou.emit()
            return
        self.controles.set_estado("ocioso")
        if status == "preparado":
            self._set_rodando(False)
            if self.confirmar_custo(self._custo):
                self._start("run", aprovado=True)  # mantém o lugar na fila
            else:
                self.status.lbl_mensagem.setText("Cancelado. Nada foi enviado ao Gemini.")
                self.status.log_line("Cancelado pelo editor antes do envio ao Gemini.")
                self.fila.sair(self)
            return
        if status == "pausado":
            self._agendar_retomada()
            return
        self._set_rodando(False)
        self.fila.sair(self)  # concluído, ajustado ou erro: o próximo da fila começa
        if status in ("concluido", "ajustado"):
            msg = ("Roteiro ajustado: PDF e XML do Premiere atualizados." if status == "ajustado"
                   else "Pronto! O PDF do roteiro e o XML do Premiere foram gerados.")
            self.status.banner_ok.mostrar(msg)
            self.status.lbl_mensagem.setText(msg)
            self.status.painel_final.show()
        elif status == "erro":
            self.status.lbl_mensagem.setText("O processamento parou. Corrija o problema e clique "
                                             "em Iniciar para continuar de onde parou.")

    def _agendar_retomada(self) -> None:
        quando = self._resume_at
        if quando is None:
            self._set_rodando(False)
            self.fila.sair(self)
            return
        local = quando.astimezone()
        hora = f"{local:%H:%M}"
        if local.date() != datetime.now().date():
            hora += f" de {local:%d/%m}"
        texto = f"Limite gratuito atingido. Continua automaticamente às {hora}."
        self.status.banner_pausa.mostrar(texto)
        self.status.acoes_cota.show()
        self.controles.set_estado("pausado", TEXTO_PAUSA_COTA)
        self.status.lbl_mensagem.setText(texto)
        self.status.log_line(texto)
        ms = int((local - datetime.now().astimezone()).total_seconds() * 1000)
        self.timer_retomar.start(max(1000, ms + MARGEM_RETOMADA_MS))
        # o formulário segue travado: a retomada usa o mesmo pedido
        self.form.set_rodando(True)
        self.status.btn_ajuste.setEnabled(False)
        self.fila.esperando_cota(self)  # o próximo da fila adianta enquanto isso
        self.mudou.emit()

    def _retomar(self) -> None:
        if self._req is None:
            return
        acao, aprovado, pedido = self._ultima
        self.status.log_line("Retomando após o limite gratuito do Gemini.")
        # retomada automática: não refaz etapas que já terminaram com falhas por arquivo
        self._start(acao, aprovado, pedido, refazer_falhas=False)

    # ------------------------------------------------------------ ações finais
    def _paths(self):
        req = self._req or self.form.build_request()
        return build_event_paths(req.source_dir, self.s, req.work_drive)

    def abrir_pdf(self) -> None:
        try:
            pdf = self._paths().pdf_path
        except ValueError as e:
            self.status.banner_erro.mostrar(str(e))
            return
        if not Path(pdf).is_file():
            self.status.banner_erro.mostrar(f"O PDF ainda não existe: {pdf}")
            return
        os.startfile(str(pdf))  # noqa: S606 - abre no leitor padrão do Windows

    def abrir_premiere(self) -> None:
        """Pede ao painel do Premiere o projeto no padrão de pastas da Fokuss (cria ou abre)."""
        self._pedir_premiere("abrir")

    def puxar_roteiro(self) -> None:
        """Pede ao painel que leve as timelines do roteiro e as mídias para o projeto."""
        self._pedir_premiere("puxar")

    def _pedir_premiere(self, acao: str) -> None:
        try:
            p = self._paths()
        except ValueError as e:
            self.status.banner_erro.mostrar(str(e))
            return
        xml = Path(p.analysis_dir) / f"{p.event_name} - PREMIERE.xml"
        if acao == "puxar" and not xml.is_file():
            self.status.banner_erro.mostrar("O roteiro ainda não foi gerado: o XML do Premiere sai "
                                            "no fim do processamento (etapa Premiere).")
            return
        agora = datetime.now().replace(microsecond=0)
        try:
            job = write_job(p, self.s, xml if xml.is_file() else None, area=self.area)
            pedir_ao_premiere(self.s, acao, job, agora)
        except Exception as e:  # noqa: BLE001 - disco cheio, sem permissão…
            self.status.banner_erro.mostrar(f"Não consegui preparar o pedido ao Premiere: {e}")
            return
        self._pedido_premiere = (acao, agora.isoformat(timespec="seconds"), time.monotonic(), False)
        self.timer_premiere.start()
        oque = ("abrir o projeto" if acao == "abrir"
                else "puxar o roteiro (timelines e mídias) para o projeto")
        if premiere_aberto():
            self.status.banner_ok.mostrar(
                f"Pedido enviado ao Premiere para {oque}. O painel Roteiro IA faz sozinho; se ele "
                "não estiver aberto, use Janela → Extensões → Roteiro IA.")
            return
        exe = premiere_exe()
        if exe is None:
            self.status.banner_erro.mostrar("Não encontrei o Premiere Pro instalado neste computador.")
            return
        args = [str(exe)]
        if Path(p.prproj_path).is_file():
            args.append(str(p.prproj_path))
        subprocess.Popen(args, close_fds=True)  # noqa: S603
        self.status.banner_ok.mostrar(
            f"Abrindo o Premiere para {oque}. Quando ele abrir, o painel Roteiro IA faz sozinho; "
            "na primeira vez, abra o painel em Janela → Extensões → Roteiro IA.")

    def _conferir_premiere(self) -> None:
        """Mostra o resultado do pedido; avisa se ninguém no Premiere pegou o pedido."""
        if self._pedido_premiere is None:
            self.timer_premiere.stop()
            return
        acao, quando, inicio, avisou = self._pedido_premiere
        r = ler_resultado(self.s, quando)
        if r is not None:
            self.timer_premiere.stop()
            self._pedido_premiere = None
            linhas = [re.sub(r"^(ok|aviso|erro):", "", m) for m in r.get("mensagens") or [] if m]
            for ln in linhas:
                self.status.log_line(f"Premiere: {ln}")
            titulo = {"abrir": "Projeto do Premiere pronto", "puxar": "Roteiro no projeto do Premiere"}
            if r.get("estado") == "erro":
                self.status.banner_erro.mostrar("O Premiere não conseguiu: " + " ".join(linhas[-3:]))
            else:
                extra = " (com avisos, veja o registro)" if r.get("estado") == "aviso" else ""
                self.status.banner_ok.mostrar(f"{titulo.get(acao, 'Premiere')}{extra}.")
            return
        passado = time.monotonic() - inicio
        if passado > PREMIERE_DESISTIR_S:
            self.timer_premiere.stop()
            self._pedido_premiere = None
            return
        if not avisou and passado > PREMIERE_AVISO_S and pedido_pendente(self.s):
            self._pedido_premiere = (acao, quando, inicio, True)
            self.status.banner_erro.mostrar(
                "O Premiere ainda não pegou o pedido. Se ele já estava aberto antes desta versão, "
                "feche e abra o Premiere (o serviço do Roteiro IA abre junto); ou abra o painel em "
                "Janela → Extensões → Roteiro IA. O pedido continua valendo por 30 min.")

    def abrir_pasta_videos(self) -> None:
        self._abrir_pasta(lambda p: p.export_dir,
                          "A pasta dos vídeos prontos ainda não existe ({}). Ela é criada quando o "
                          "projeto é montado no Premiere.")

    def abrir_pasta_projeto(self) -> None:
        self._abrir_pasta(lambda p: p.work_dir, "A pasta do projeto ainda não existe: {}")

    def _abrir_pasta(self, qual, msg_falta: str) -> None:
        try:
            pasta = Path(qual(self._paths()))
        except ValueError as e:
            self.status.banner_erro.mostrar(str(e))
            return
        if not pasta.is_dir():
            self.status.banner_erro.mostrar(msg_falta.format(pasta))
            return
        os.startfile(str(pasta))  # noqa: S606 - abre no Explorador

    def roteiro_pelo_chat(self) -> None:
        """Roteiro feito no chat do site (sem cota da API); aceito, gera o PDF e o XML."""
        from roteiro_ia.ui.chat import RoteiroChatDialog
        if self._req is None:
            self.status.banner_erro.mostrar("Abra ou inicie um projeto primeiro.")
            return
        if self.rodando:
            self.status.banner_erro.mostrar("Espere o processamento atual terminar (ou pause).")
            return
        try:
            p = self._paths()
            pipe = self._factory(self._req, self.s, lambda *a: None)
        except Exception as e:  # noqa: BLE001
            self.status.banner_erro.mostrar(f"Não consegui abrir o projeto: {e}")
            return
        try:
            existe = pipe.db.latest_roteiro() is not None
            dlg = RoteiroChatDialog(pipe, Path(p.analysis_dir), existe, self)
            aceito = dlg.exec() == QDialog.Accepted
        finally:
            pipe.close()
        if not aceito:
            return
        self.timer_retomar.stop()  # o roteiro já está feito: nada de retomada da cota
        self.status.limpar_avisos()
        self.status.log_line("Roteiro feito pelo chat: gerando PDF e XML.")
        self._start("manual", aprovado=True)

    def salvar_observacoes(self) -> None:
        """Observações mudadas no formulário: valem no próximo roteiro deste projeto (o pipeline
        relê o projeto.json na etapa do roteiro, até numa retomada depois da cota)."""
        if self._req is None:
            return  # projeto ainda não iniciado: vão junto no Iniciar
        self._req.observacoes = self.form.observacoes
        try:
            f = Path(self._paths().analysis_dir) / PROJECT_FILE
            if f.parent.is_dir():
                self._req.save(f, self.s)
        except (OSError, ValueError) as e:
            self.status.banner_erro.mostrar(f"Não consegui salvar as observações: {e}")
            return
        self.status.banner_ok.mostrar("Observações salvas: valem no próximo roteiro (use Pedir "
                                      "ajuste no roteiro para aplicar num roteiro já pronto).")

    def pedir_ajuste(self) -> None:
        if self._req is None or self.rodando:
            return
        dlg = AjusteDialog(self)
        if dlg.exec() != QDialog.Accepted or not dlg.pedido():
            return
        self.ajustar(dlg.pedido())

    def ajustar(self, pedido: str) -> bool:
        """Refaz roteiro, PDF e XML com o pedido (também usado pela aba Músicas a baixar)."""
        if self._req is None or self.rodando or not pedido:
            return False
        if self._req.gemini_mode == "pago" and QMessageBox.question(
                self, "Modo pago do Gemini", "O ajuste usa o Gemini no modo pago. Continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return False
        self.status.limpar_avisos()
        self.status.log_line(f"Pedido de ajuste: {pedido}")
        self._start("revise", aprovado=True, pedido=pedido)
        return True

    def menu_recentes(self) -> QMenu:
        """Lista suspensa: projetos abertos por último primeiro, com a última alteração."""
        menu = QMenu(self)
        discos = [self.form.combo_disco.currentText().strip(), self.s.work_drive]
        itens = recentes.listar(self.s, discos, area=self.area)
        if not itens:
            menu.addAction("Nenhum projeto recente").setEnabled(False)
        for r in itens:
            a = menu.addAction(f"{r.nome}	alterado {recentes.quando_texto(r.alterado_em)}")
            a.setToolTip(str(r.pasta))
            a.triggered.connect(lambda _=False, r=r: self.abrir_recente(r))
        menu.setToolTipsVisible(True)
        menu.addSeparator()
        menu.addAction("Outra pasta…").triggered.connect(self.continuar_outra_pasta)
        return menu

    def continuar_existente(self) -> None:
        if self.rodando:
            return
        b = self.form.btn_continuar
        self.menu_recentes().exec(b.mapToGlobal(b.rect().bottomLeft()))

    def abrir_recente(self, r: recentes.Recente) -> bool:
        if self.rodando:
            return False
        self.form.combo_disco.setCurrentText(r.disco)
        if not self.form.set_event_folder(r.pasta):
            self.status.banner_erro.mostrar(
                f"Não consegui abrir a pasta do evento {r.pasta}. O disco de origem está conectado?")
            return False
        return self.abrir_existente(r.pasta)

    def continuar_outra_pasta(self) -> None:
        if self.rodando:
            return
        pasta = self.form.escolher_pasta("Escolha a pasta do evento (no R:) para continuar")
        if pasta is None or not self.form.set_event_folder(pasta):
            return
        self.abrir_existente(pasta)

    def abrir_existente(self, pasta: Path) -> bool:
        """Carrega ANALISE\\projeto.json (disco escolhido ou o padrão) e retoma o processamento."""
        discos = dict.fromkeys([self.form.combo_disco.currentText().strip(), self.s.work_drive])
        for disco in discos:
            f = Path(build_event_paths(pasta, self.s, disco).analysis_dir) / PROJECT_FILE
            if f.is_file():
                try:
                    req = ProjectRequest.load(f)
                except (OSError, ValueError, KeyError) as e:
                    self.status.banner_erro.mostrar(f"Não consegui ler {f}: {e}")
                    return False
                if req.area != self.area:
                    nome = area_por_id(req.area).nome
                    self.status.banner_erro.mostrar(
                        f"Este projeto é de {nome}. Abra pela área {nome}.")
                    return False
                self.form.load_request(req)
                self.iniciar()
                return True
        self.status.banner_erro.mostrar(
            "Não encontrei um projeto deste evento no disco de trabalho. Confira o disco "
            "ou comece com Iniciar.")
        return False
