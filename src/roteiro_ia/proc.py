"""Subprocessos sem janela preta de console e que o Parar consegue encerrar.

Toda chamada a ffmpeg/ffprobe/Edge/`net use` do pacote passa por `run`. No Windows o processo
nasce com CREATE_NO_WINDOW e STARTUPINFO(SW_HIDE) — sob o pythonw (a janela do programa) cada
console abriria uma tela preta por cima do trabalho do editor.
"""
from __future__ import annotations

import functools
import subprocess
import sys
import time

from roteiro_ia import controle

WIN = sys.platform == "win32"
POLL_S = 0.5  # de quanto em quanto tempo a espera confere o Parar


def _sem_console() -> dict:
    if not WIN:
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}


def _encerrar(p: subprocess.Popen) -> None:
    try:
        p.terminate()
        p.communicate(timeout=controle.MATAR_APOS_S)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
    except (OSError, ValueError):
        pass


def run(cmd, *, timeout: float | None = None, text: bool = False, encoding: str | None = None,
        errors: str | None = None, capture_output: bool = True) -> subprocess.CompletedProcess:
    """Como `subprocess.run` (sem `check`), sem console e registrado no controle atual: o
    Parar mata o processo e levanta `controle.Interrompido`. TimeoutExpired como no original."""
    c = controle.atual()
    c.checkpoint()
    pipe = subprocess.PIPE if capture_output else None
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=pipe, stderr=pipe, text=text,
                         encoding=encoding, errors=errors, **_sem_console())
    c.registrar(p)
    try:
        fim = None if timeout is None else time.monotonic() + timeout
        while True:
            espera = POLL_S if fim is None else max(0.0, min(POLL_S, fim - time.monotonic()))
            try:
                out, err = p.communicate(timeout=espera)
                break
            except subprocess.TimeoutExpired:
                if c.parando:
                    _encerrar(p)
                    c.checkpoint()  # marca "parado" e levanta Interrompido
                    raise controle.Interrompido() from None
                if fim is not None and time.monotonic() >= fim:
                    p.kill()
                    out, err = p.communicate()
                    raise subprocess.TimeoutExpired(cmd, timeout, out, err) from None
    except BaseException:
        if p.poll() is None:  # Interrompido, Ctrl+C...: nada de processo órfão
            _encerrar(p)
        raise
    finally:
        c.liberar(p)
    if c.parando:  # terminou porque o Parar o encerrou
        c.checkpoint()
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def esconder_consoles(cls=subprocess.Popen) -> None:
    """Bibliotecas de terceiros (ex.: audioread → ffmpeg) também abrem console: no Windows,
    todo Popen sem `creationflags` informado ganha CREATE_NO_WINDOW. Idempotente; flags
    explícitos são preservados."""
    if not WIN or getattr(cls.__init__, "_roteiro_sem_console", False):
        return
    original = cls.__init__

    @functools.wraps(original)
    def __init__(self, *args, **kw):
        if "creationflags" not in kw and len(args) < 14:  # 14º posicional = creationflags
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        original(self, *args, **kw)

    __init__._roteiro_sem_console = True
    cls.__init__ = __init__
