"""Subprocessos sem janela preta de console e que o Parar consegue encerrar.

Toda chamada a ffmpeg/ffprobe/Edge/`net use` do pacote passa por `run`. No Windows o processo
nasce com CREATE_NO_WINDOW e STARTUPINFO(SW_HIDE) — sob o pythonw (a janela do programa) cada
console abriria uma tela preta por cima do trabalho do editor.
"""
from __future__ import annotations

import functools
import subprocess
import sys
import threading
import time

from roteiro_ia import controle

WIN = sys.platform == "win32"
POLL_S = 0.5  # de quanto em quanto tempo a espera confere o Parar
TASKKILL_TIMEOUT_S = 10.0
_TRAVA_CONSOLES = threading.Lock()


def _sem_console() -> dict:
    if not WIN:
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}


def matar_arvore(p: subprocess.Popen) -> None:
    """Encerra o processo e os filhos (ex.: o Edge abre vários). No Windows usa
    `taskkill /T /F` (sem console); se não der, `kill` só no processo."""
    if p.poll() is not None:
        return
    if WIN:
        try:
            subprocess.Popen(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **_sem_console()
                             ).wait(TASKKILL_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        if p.poll() is None:
            p.kill()
    except OSError:
        pass


class _Arvore:
    """O que o `Controle` registra: o Parar encerra a árvore inteira, uma vez só."""

    def __init__(self, p: subprocess.Popen):
        self.p = p
        self.encerrado = False
        self._lock = threading.Lock()

    def poll(self):
        return self.p.poll()

    def wait(self, timeout=None):
        return self.p.wait(timeout)

    def _marcar(self) -> bool:
        with self._lock:
            if self.encerrado:
                return False
            self.encerrado = True
            return True

    def terminate(self) -> None:
        """Chamado pelo Controle (thread da janela): o taskkill roda numa thread à parte."""
        if self._marcar():
            threading.Thread(target=matar_arvore, args=(self.p,), daemon=True,
                             name="roteiro-matar-arvore").start()

    kill = terminate

    def encerrar_ja(self) -> None:
        """Na thread do worker: encerra agora, se o Controle ainda não encerrou."""
        if self._marcar():
            matar_arvore(self.p)


def run(cmd, *, timeout: float | None = None, text: bool = False, encoding: str | None = None,
        errors: str | None = None, capture_output: bool = True,
        controlado: bool = True) -> subprocess.CompletedProcess:
    """Como `subprocess.run` (sem `check`), sem console e registrado no controle atual: o
    Parar mata o processo (e os filhos) e levanta `controle.Interrompido`. TimeoutExpired como
    no original. `controlado=False` (consultas curtas como `net use` da guarda de escrita, que
    também roda na limpeza depois de um Parar): só esconde o console, sem checar o controle."""
    c = controle.atual() if controlado else controle.NULO
    c.checkpoint()
    pipe = subprocess.PIPE if capture_output else None
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=pipe, stderr=pipe, text=text,
                         encoding=encoding, errors=errors, **_sem_console())
    arv = _Arvore(p)
    c.registrar(arv)
    try:
        fim = None if timeout is None else time.monotonic() + timeout
        while True:
            espera = POLL_S if fim is None else max(0.0, min(POLL_S, fim - time.monotonic()))
            try:
                out, err = p.communicate(timeout=espera)
                break
            except subprocess.TimeoutExpired:
                if c.parando:
                    arv.encerrar_ja()  # não faz nada se o Controle já encerrou a árvore
                    p.communicate()
                    c.checkpoint()  # marca "parado" e levanta Interrompido
                    raise controle.Interrompido() from None
                if fim is not None and time.monotonic() >= fim:
                    arv.encerrar_ja()
                    out, err = p.communicate()
                    raise subprocess.TimeoutExpired(cmd, timeout, out, err) from None
    except BaseException:
        if p.poll() is None:  # Interrompido, Ctrl+C...: nada de processo órfão
            arv.encerrar_ja()
            try:
                p.communicate(timeout=controle.MATAR_APOS_S)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass
        raise
    finally:
        c.liberar(arv)
    if c.parando:  # terminou porque o Parar o encerrou
        c.checkpoint()
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def esconder_consoles(cls=subprocess.Popen) -> None:
    """Bibliotecas de terceiros (ex.: audioread → ffmpeg) também abrem console: no Windows,
    todo Popen sem `creationflags` informado ganha CREATE_NO_WINDOW. Idempotente (com trava:
    vários workers podem chamar ao mesmo tempo); flags explícitos são preservados."""
    if not WIN:
        return
    with _TRAVA_CONSOLES:
        if getattr(cls.__init__, "_roteiro_sem_console", False):
            return
        original = cls.__init__

        @functools.wraps(original)
        def __init__(self, *args, **kw):
            if "creationflags" not in kw and len(args) < 14:  # 14º posicional = creationflags
                kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            original(self, *args, **kw)

        __init__._roteiro_sem_console = True
        cls.__init__ = __init__
