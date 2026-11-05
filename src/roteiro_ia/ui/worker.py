"""Trabalho pesado fora da tela: cada worker roda numa QThread e conversa só por sinais.

O Pipeline (e o banco do projeto) é criado DENTRO da thread do worker e fechado no fim, então a
janela nunca toca no banco nem o worker toca em widgets.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

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

    def _com_log(self, fn):
        logger = logging.getLogger("roteiro_ia")
        h = _SinalLogHandler(self.log)
        logger.addHandler(h)
        try:
            return fn()
        finally:
            logger.removeHandler(h)


class PipelineWorker(_Base):
    """Roda `Pipeline.prepare/run/revise`. `terminou` recebe "preparado", "concluido",
    "pausado", "ajustado" ou "erro" (neste caso `erro` é emitido antes, com a mensagem)."""

    progresso = Signal(str, str, float)
    estados = Signal(dict)       # {etapa: (status, detalhe)} lido do banco, no início e no fim
    custo = Signal(float)
    retomar_em = Signal(object)  # datetime com fuso

    def __init__(self, factory: PipelineFactory, acao: str = "run", aprovado_custo: bool = False,
                 pedido: str | None = None):
        super().__init__()
        if acao not in ("prepare", "run", "revise"):
            raise ValueError(f"Ação desconhecida: {acao}")
        self._factory = factory
        self.acao = acao
        self.aprovado_custo = aprovado_custo
        self.pedido = pedido

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
            status = pipe.run(aprovado_custo=self.aprovado_custo)
            if status == "pausado":
                self.retomar_em.emit(pipe.resume_at)
            return status
        except QuotaPaused as e:
            self.retomar_em.emit(e.resume_at)
            return "pausado"
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
    `terminou` recebe "ok" ou "erro"."""

    progresso = Signal(int, int, str)
    resultado = Signal(object)

    def __init__(self, fn: Callable[[Callable[[int, int, str], None]], object]):
        super().__init__()
        self._fn = fn

    def _executar(self) -> str:
        try:
            r = self._fn(lambda i, t, nome="": self.progresso.emit(int(i), int(t), str(nome)))
        except Exception as e:  # noqa: BLE001
            self.erro.emit(mensagem_erro(e))
            return "erro"
        self.resultado.emit(r)
        return "ok"

    @Slot()
    def run(self) -> None:
        self.terminou.emit(self._com_log(self._executar))


class Runner(QObject):
    """Guarda as threads ativas (evita coleta de lixo no meio) e as encerra no fim."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._ativos: list[tuple[QThread, QObject]] = []

    def start(self, worker: _Base) -> QThread:
        th = QThread()
        worker.moveToThread(th)
        th.started.connect(worker.run)
        # slot do Runner (thread principal): chega enfileirado, depois dos demais sinais do worker
        worker.terminou.connect(self._fim)
        self._ativos.append((th, worker))
        th.start()
        return th

    @Slot(str)
    def _fim(self, _status: str) -> None:
        w = self.sender()
        for par in list(self._ativos):
            if par[1] is w:
                par[0].quit()
                par[0].wait()
                self._ativos.remove(par)

    def ativo(self) -> bool:
        return bool(self._ativos)

    def wait_all(self, ms: int = -1) -> bool:
        """Espera as tarefas em andamento (o laço da thread sai assim que o worker termina)."""
        ok = True
        for th, _w in list(self._ativos):
            th.quit()
            ok = (th.wait() if ms < 0 else th.wait(ms)) and ok
        return ok
