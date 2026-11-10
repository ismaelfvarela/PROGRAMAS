"""Trabalho pesado fora da tela: cada worker roda numa QThread e conversa só por sinais.

O Pipeline (e o banco do projeto) é criado DENTRO da thread do worker e fechado no fim, então a
janela nunca toca no banco nem o worker toca em widgets.

Cada worker tem um `Controle` (Pausar/Continuar/Parar), ativo na thread dele durante a execução;
as mudanças de estado chegam à janela pelo sinal `estado`.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from roteiro_ia import controle, proc
from roteiro_ia.controle import Controle, Interrompido
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.safety import ProtectedPathError

Events = Callable[[str, str, float], None]
PipelineFactory = Callable[[Events], object]


def mensagem_erro(e: BaseException) -> str:
    """Mensagem em português para o editor."""
    if isinstance(e, ProtectedPathError):
        return f"Bloqueado por segurança: {e}"
    if isinstance(e, QuotaPaused):
        return (f"Limite gratuito atingido. Tente de novo a partir de "
                f"{e.resume_at.astimezone():%d/%m %H:%M}.")
    return str(e) or f"Erro inesperado ({type(e).__name__})."


class _SinalLogHandler(logging.Handler):
    """Avisos do pacote (logging) viram linhas no log da janela."""

    def __init__(self, sinal):
        super().__init__(level=logging.INFO)
        self._sinal = sinal

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sinal.emit(record.getMessage())
        except Exception:  # noqa: BLE001 - log nunca derruba o processamento
            pass


class _Base(QObject):
    terminou = Signal(str)
    erro = Signal(str)
    log = Signal(str)
    estado = Signal(str)  # rodando | pausando | pausado | parando | parado (do Controle)
    controlavel = False   # entra na barra geral (Pausar/Continuar/Parar tudo)

    def __init__(self):
        super().__init__()
        # ao_mudar roda na thread de quem mudou o estado; o sinal leva à thread da janela
        self.controle = Controle(ao_mudar=self.estado.emit)

    def _com_log(self, fn):
        proc.esconder_consoles()  # bibliotecas (audioread → ffmpeg...) sem tela preta
        logger = logging.getLogger("roteiro_ia")
        h = _SinalLogHandler(self.log)
        logger.addHandler(h)
        try:
            with controle.usar(self.controle):
                return fn()
        finally:
            logger.removeHandler(h)


class PipelineWorker(_Base):
    """Roda `Pipeline.prepare/run/revise`. `terminou` recebe "preparado", "concluido",
    "pausado", "ajustado", "parado" (Parar do editor) ou "erro" (neste caso `erro` é emitido
    antes, com a mensagem)."""

    controlavel = True
    progresso = Signal(str, str, float)
    estados = Signal(dict)       # {etapa: (status, detalhe)} lido do banco, no início e no fim
    custo = Signal(float)
    retomar_em = Signal(object)  # datetime com fuso

    def __init__(self, factory: PipelineFactory, acao: str = "run", aprovado_custo: bool = False,
                 pedido: str | None = None, refazer_falhas: bool = True):
        if acao not in ("prepare", "run", "revise", "manual"):
            raise ValueError(f"Ação desconhecida: {acao}")
        super().__init__()
        self._factory = factory
        self.acao = acao
        self.aprovado_custo = aprovado_custo
        self.pedido = pedido
        self.refazer_falhas = refazer_falhas  # False nas retomadas automáticas

    def _emit_estados(self, pipe) -> None:
        try:
            from roteiro_ia.pipeline import STAGES
            db = pipe.db
            self.estados.emit({n: (db.stage_status(n), db.stage_detail(n)) for n in STAGES})
        except Exception:  # noqa: BLE001 - só informativo (ex.: banco ainda não existe)
            pass

    def _executar(self) -> str:
        pipe = None
        try:
            pipe = self._factory(self.progresso.emit)
            self._emit_estados(pipe)
            if self.acao == "prepare":
                _p, custo = pipe.prepare()
                self.custo.emit(float(custo))
                return "preparado"
            if self.acao == "revise":
                pipe.revise(self.pedido or "", aprovado_custo=self.aprovado_custo)
                return "ajustado"
            if self.acao == "manual":  # roteiro feito pelo chat: só PDF e XML
                pipe.concluir_roteiro_manual()
                return "ajustado"
            status = pipe.run(aprovado_custo=self.aprovado_custo, refazer_falhas=self.refazer_falhas)
            if status == "pausado":
                self.retomar_em.emit(pipe.resume_at)
            return status
        except QuotaPaused as e:
            self.retomar_em.emit(e.resume_at)
            return "pausado"
        except Interrompido:
            return "parado"
        except Exception as e:  # noqa: BLE001 - toda falha vira mensagem na janela
            self.erro.emit(mensagem_erro(e))
            return "erro"
        finally:
            if pipe is not None:
                self._emit_estados(pipe)
                try:
                    pipe.close()
                except Exception:  # noqa: BLE001
                    pass

    @Slot()
    def run(self) -> None:
        self.terminou.emit(self._com_log(self._executar))


class TarefaWorker(_Base):
    """Executa `fn(progress)` (progress(i, total, nome)) e devolve o resultado por sinal.
    `terminou` recebe "ok", "parado" ou "erro". Se `fn` devolver normalmente depois de um
    Parar (ex.: update_index devolve o que já fez), o resultado é emitido e o status é "parado".
    `controlavel=True` nos processos longos (índice de trilhas, perfil de estilo)."""

    progresso = Signal(int, int, str)
    resultado = Signal(object)

    def __init__(self, fn: Callable[[Callable[[int, int, str], None]], object],
                 controlavel: bool = False):
        super().__init__()
        self._fn = fn
        self.controlavel = controlavel

    def _executar(self) -> str:
        try:
            r = self._fn(lambda i, t, nome="": self.progresso.emit(int(i), int(t), str(nome)))
        except Interrompido:
            return "parado"
        except Exception as e:  # noqa: BLE001
            self.erro.emit(mensagem_erro(e))
            return "erro"
        self.resultado.emit(r)
        return "parado" if self.controle.parando else "ok"

    @Slot()
    def run(self) -> None:
        self.terminou.emit(self._com_log(self._executar))


class Runner(QObject):
    """Guarda as threads ativas (evita coleta de lixo no meio) e as encerra no fim. É também o
    registro dos processos controláveis da barra geral (Pausar/Continuar/Parar tudo)."""

    mudou = Signal()  # um processo começou, terminou ou mudou de estado

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._ativos: list[tuple[QThread, QObject]] = []

    def start(self, worker: _Base) -> QThread:
        th = QThread()
        worker.moveToThread(th)
        th.started.connect(worker.run)
        # slot do Runner (thread principal): chega enfileirado, depois dos demais sinais do worker
        worker.terminou.connect(self._fim)
        worker.estado.connect(self._estado_mudou)
        self._ativos.append((th, worker))
        th.start()
        self.mudou.emit()
        return th

    @Slot(str)
    def _estado_mudou(self, _estado: str) -> None:
        self.mudou.emit()

    @Slot(str)
    def _fim(self, _status: str) -> None:
        w = self.sender()
        for par in list(self._ativos):
            if par[1] is w:
                par[0].quit()
                par[0].wait()
                self._ativos.remove(par)
        self.mudou.emit()

    def ativo(self) -> bool:
        return bool(self._ativos)

    def wait_all(self, ms: int = -1) -> bool:
        """Espera as tarefas em andamento (o laço da thread sai assim que o worker termina)."""
        ok = True
        for par in list(self._ativos):
            th = par[0]
            th.quit()
            fim = th.wait() if ms < 0 else th.wait(ms)
            if fim and par in self._ativos:
                self._ativos.remove(par)  # já terminou: não conta mais como ativa
            ok = fim and ok
        return ok

    # ------------------------------------------------------------ controle geral
    def controles(self) -> list[Controle]:
        """Controles dos processos longos em andamento (tarefas auxiliares curtas não contam;
        um processo já parado, à espera do fim da thread, também não)."""
        return [w.controle for _th, w in self._ativos
                if getattr(w, "controlavel", False) and w.controle.estado != "parado"]

    def n_ativos(self) -> int:
        return len(self.controles())

    def pausar_todos(self) -> None:
        for c in self.controles():
            c.pausar()

    def continuar_todos(self) -> None:
        for c in self.controles():
            c.continuar()

    def parar_todos(self) -> None:
        for c in self.controles():
            c.parar()

    def parar_e_esperar(self, ms: int) -> bool:
        """Para tudo (inclusive as tarefas auxiliares) e espera até `ms` no total; True se todas
        as threads terminaram a tempo."""
        for _th, w in self._ativos:
            w.controle.parar()
        fim = time.monotonic() + ms / 1000
        ok = True
        for par in list(self._ativos):
            th = par[0]
            th.quit()
            if th.wait(max(0, int((fim - time.monotonic()) * 1000))):
                if par in self._ativos:
                    self._ativos.remove(par)
            else:
                ok = False
        self.mudou.emit()
        return ok
