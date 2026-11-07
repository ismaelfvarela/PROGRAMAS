"""Uma janela só: o segundo clique no atalho traz a janela aberta para frente e sai.

A trava é um mutex nomeado do Windows (atômico: dois cliques quase juntos não abrem duas
janelas). O aviso para "mostrar" vai por QLocalSocket ao servidor da primeira instância;
como ela pode ainda estar abrindo, o segundo processo tenta por alguns segundos.
"""
from __future__ import annotations

import ctypes
import os
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

NOME = f"RoteiroIA-Fokuss-{os.environ.get('USERNAME', 'usuario')}"
ERROR_ALREADY_EXISTS = 183
MOSTRAR = b"mostrar"


class Trava:
    """Mutex nomeado; `primeira` é False se outra instância já o criou."""

    def __init__(self, nome: str = NOME):
        self._handle = None
        self.primeira = True
        if os.name != "nt":
            return
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        self._handle = k32.CreateMutexW(None, False, f"Local\\{nome}")
        self.primeira = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        self._k32 = k32

    def liberar(self) -> None:
        if self._handle:
            self._k32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None


def avisar_primeira(nome: str = NOME, espera_s: float = 15.0) -> bool:
    """Pede à instância aberta que mostre a janela; True se ela recebeu o aviso."""
    fim = time.monotonic() + espera_s
    while time.monotonic() < fim:
        s = QLocalSocket()
        s.connectToServer(nome)
        if s.waitForConnected(300):
            s.write(MOSTRAR)
            s.flush()
            s.waitForBytesWritten(1000)
            s.disconnectFromServer()
            return True
        time.sleep(0.3)  # a primeira ainda está abrindo: o servidor sobe logo
    return False


class Servidor(QObject):
    """Escuta os avisos das instâncias seguintes e emite `mostrar`."""

    mostrar = Signal()

    def __init__(self, nome: str = NOME, parent: QObject | None = None):
        super().__init__(parent)
        self._conexoes: list[QLocalSocket] = []
        self._srv = QLocalServer(self)
        QLocalServer.removeServer(nome)
        self._srv.listen(nome)
        self._srv.newConnection.connect(self._nova)

    def _nova(self) -> None:
        while self._srv.hasPendingConnections():
            c = self._srv.nextPendingConnection()
            self._conexoes.append(c)
            c.readyRead.connect(self._ler)
            c.disconnected.connect(self._ler)
            self._ler(c)  # o aviso pode já ter chegado junto com a conexão

    def _ler(self, c: QLocalSocket | None = None) -> None:
        c = c or self.sender()
        if c is None or c not in self._conexoes:
            return
        dados = bytes(c.readAll())
        if MOSTRAR in dados:
            self._conexoes.remove(c)
            c.abort()
            self.mostrar.emit()
        elif c.state() == QLocalSocket.UnconnectedState:
            self._conexoes.remove(c)

    def fechar(self) -> None:
        for c in self._conexoes:
            c.abort()
        self._conexoes.clear()
        self._srv.close()


def trazer_para_frente(w) -> None:
    from PySide6.QtCore import Qt
    if w.isMinimized():
        w.showNormal()
    w.show()
    w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
    w.raise_()
    w.activateWindow()
