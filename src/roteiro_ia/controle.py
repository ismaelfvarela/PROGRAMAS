"""Play / Pause / Stop dos processos longos.

Cada processo (pipeline, índice de trilhas, perfil de estilo) roda com um `Controle`. As etapas
chamam `atual().checkpoint()` no início de cada item (arquivo, trilha, vídeo, pacote): ali a
pausa bloqueia e o Parar levanta `Interrompido`. O controle "atual" é por thread/contexto
(`contextvars`), então as funções das etapas não mudam de assinatura; sem controle ativo vale
um controle nulo, que nunca pausa nem para.
"""
from __future__ import annotations

import contextvars
import logging
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Literal

Estado = Literal["rodando", "pausando", "pausado", "parando", "parado"]
ESPERA_S = 0.2          # granularidade da espera na pausa
MATAR_APOS_S = 5.0      # Parar: terminate, e kill se o subprocesso não sair nesse tempo
_log = logging.getLogger("roteiro_ia")


class Interrompido(BaseException):
    """O editor clicou em Parar. BaseException de propósito: os `except Exception` por arquivo
    das etapas não a transformam em falha, e ela sobe até o pipeline/worker."""


class Controle:
    def __init__(self, ao_mudar: Callable[[str], None] | None = None):
        self._lock = threading.Lock()
        self._estado: Estado = "rodando"
        self._mudou = threading.Event()   # acorda quem espera (pausa ou dormir) a cada mudança
        self._procs: set = set()
        self.ao_mudar = ao_mudar          # chamado com o novo estado (em qualquer thread)

    # ------------------------------------------------------------ estado
    @property
    def estado(self) -> Estado:
        return self._estado

    @property
    def aguardando_pausa(self) -> bool:
        """True entre o pedido de pausa e o próximo checkpoint."""
        return self._estado == "pausando"

    @property
    def parando(self) -> bool:
        return self._estado in ("parando", "parado")

    def _set(self, novo: Estado) -> None:
        # chamado com o lock; o aviso sai depois (fora do lock)
        self._estado = novo
        self._mudou.set()

    def _avisar(self, estado: str) -> None:
        if self.ao_mudar:
            try:
                self.ao_mudar(estado)
            except Exception:  # noqa: BLE001 - aviso de interface nunca derruba o processo
                pass

    # ------------------------------------------------------------ comandos
    def pausar(self) -> None:
        with self._lock:
            if self._estado != "rodando":
                return
            self._set("pausando")
        self._avisar("pausando")

    def continuar(self) -> None:
        with self._lock:
            if self._estado not in ("pausando", "pausado"):
                return
            self._set("rodando")
        self._avisar("rodando")

    def parar(self) -> None:
        with self._lock:
            if self._estado in ("parando", "parado"):
                return
            self._set("parando")
            procs = list(self._procs)
        self._avisar("parando")
        for p in procs:
            _encerrar(p)

    def _marcar_parado(self) -> None:
        with self._lock:
            if self._estado == "parado":
                return
            self._set("parado")
        self._avisar("parado")

    # ------------------------------------------------------------ etapas
    def checkpoint(self) -> None:
        """Ponto seguro entre itens: bloqueia na pausa; no Parar levanta Interrompido."""
        avisar = None
        with self._lock:
            if self._estado == "pausando":
                self._set("pausado")
                avisar = "pausado"
        if avisar:
            self._avisar(avisar)
        while True:
            with self._lock:
                est = self._estado
                if est == "pausado":
                    self._mudou.clear()  # o próximo continuar/parar acorda o wait abaixo
            if est in ("parando", "parado"):
                self._marcar_parado()
                raise Interrompido()
            if est != "pausado":
                return
            self._mudou.wait(ESPERA_S)

    def esperar(self, segundos: float) -> None:
        """Dorme até `segundos`, acordando no Parar (levanta Interrompido). A pausa não
        interrompe a espera (ela vale no próximo checkpoint)."""
        fim = time.monotonic() + max(0.0, segundos)
        while True:
            if self.parando:
                self._marcar_parado()
                raise Interrompido()
            resta = fim - time.monotonic()
            if resta <= 0:
                return
            time.sleep(min(ESPERA_S, resta))

    def registrar(self, proc) -> None:
        """Subprocesso em andamento: o Parar o encerra."""
        with self._lock:
            self._procs.add(proc)
            parando = self._estado in ("parando", "parado")
        if parando:
            _encerrar(proc)

    def liberar(self, proc) -> None:
        with self._lock:
            self._procs.discard(proc)


class _ControleNulo(Controle):
    """Sem processo controlado (CLI, testes): nunca pausa nem para."""

    def pausar(self) -> None:
        pass

    def parar(self) -> None:
        pass

    def checkpoint(self) -> None:
        pass

    def esperar(self, segundos: float) -> None:
        if segundos > 0:
            time.sleep(segundos)

    def registrar(self, proc) -> None:
        pass


NULO = _ControleNulo()
_atual: contextvars.ContextVar[Controle] = contextvars.ContextVar("roteiro_controle", default=NULO)


def atual() -> Controle:
    return _atual.get()


@contextmanager
def usar(c: Controle) -> Iterator[Controle]:
    tok = _atual.set(c)
    try:
        yield c
    finally:
        _atual.reset(tok)


def dormir(segundos: float) -> None:
    """time.sleep que o Parar interrompe (usado nas esperas de nova tentativa)."""
    atual().esperar(segundos)


def _encerrar(p) -> None:
    """terminate e, se não sair em MATAR_APOS_S, kill (numa thread: não trava a interface)."""
    try:
        if p.poll() is not None:
            return
        p.terminate()
    except OSError:
        return

    def matar() -> None:
        try:
            p.wait(MATAR_APOS_S)
        except subprocess.TimeoutExpired:
            try:
                p.kill()
            except OSError:
                pass
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=matar, daemon=True, name="roteiro-matar-proc").start()
