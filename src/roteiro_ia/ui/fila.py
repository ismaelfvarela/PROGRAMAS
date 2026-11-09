"""Fila de projetos no mesmo PC: um projeto (de qualquer área) roda por vez.

Quem pede primeiro tem a prioridade. Enquanto o projeto da vez espera a cota do Gemini, o próximo
adianta o que der; quando a cota volta, o primeiro retoma e o que adiantava fica pausado até ele
terminar. A fila fica só na memória.
"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject, Signal

TEXTO_NA_FILA = "Na fila — começa quando {nome} terminar."


class ClienteFila(Protocol):
    def nome_fila(self) -> str: ...
    def comecar(self) -> None: ...
    def suspender(self) -> None: ...          # pausar o worker
    def retomar_suspenso(self) -> None: ...   # soltar a pausa
    def mostrar_espera(self, texto: str | None) -> None: ...  # None apaga o aviso


class FilaProjetos(QObject):
    mudou = Signal()  # ordem ou estado de algum projeto mudou

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._ordem: list[ClienteFila] = []
        self._cota: list[ClienteFila] = []        # esperando a cota (deixam o próximo rodar)
        self._comecou: list[ClienteFila] = []     # com execução em andamento
        self._suspensos: list[ClienteFila] = []   # pausados porque outro tem a prioridade
        self._despachando = False
        self._de_novo = False

    # ------------------------------------------------------------ pedidos dos projetos
    def pedir(self, c: ClienteFila) -> None:
        """Quer rodar (Iniciar, Continuar, retomada da cota…): entra no fim da ordem ou, se já
        estiver nela, mantém o lugar."""
        if c not in self._ordem:
            self._ordem.append(c)
        for lista in (self._cota, self._comecou, self._suspensos):
            _tirar(lista, c)
        self._despachar()

    def sair(self, c: ClienteFila) -> None:
        """Terminou, parou, deu erro, foi cancelado ou saiu da fila."""
        if c not in self._ordem:
            return
        esperava = c not in self._comecou and c not in self._cota
        for lista in (self._ordem, self._cota, self._comecou, self._suspensos):
            _tirar(lista, c)
        if esperava:
            c.mostrar_espera(None)
        self._despachar()

    def esperando_cota(self, c: ClienteFila) -> None:
        """Pausou pela cota: continua na ordem, mas deixa o próximo rodar."""
        if c not in self._ordem:
            return
        for lista in (self._comecou, self._suspensos):
            _tirar(lista, c)
        if c not in self._cota:
            self._cota.append(c)
        self._despachar()

    def esvaziar(self) -> None:
        """Fechando o programa: tira todos da fila sem começar ninguém (cada projeto continua
        depois pelo "Continuar", como hoje)."""
        for lista in (self._ordem, self._cota, self._comecou, self._suspensos):
            lista.clear()
        self.mudou.emit()

    # ------------------------------------------------------------ consultas
    def ativo(self) -> ClienteFila | None:
        """O projeto da vez: o primeiro da ordem que não está esperando a cota."""
        return next((c for c in self._ordem if c not in self._cota), None)

    def na_fila(self) -> list[ClienteFila]:
        """Projetos esperando para começar."""
        dono = self.ativo()
        return [c for c in self._ordem
                if c is not dono and c not in self._comecou and c not in self._cota]

    def suspensos(self) -> list[ClienteFila]:
        """Projetos com execução pausada porque outro tem a prioridade (só a fila os solta)."""
        return list(self._suspensos)

    # ------------------------------------------------------------ despacho
    def _despachar(self) -> None:
        if self._despachando:  # um cliente mexeu na fila durante o despacho
            self._de_novo = True
            return
        self._despachando = True
        try:
            self._de_novo = True
            while self._de_novo:
                self._de_novo = False
                self._um_despacho()
        finally:
            self._despachando = False
        self.mudou.emit()

    def _um_despacho(self) -> None:
        dono = self.ativo()
        for c in list(self._ordem):
            if c not in self._ordem:
                continue
            if c is dono:
                if c not in self._comecou:
                    self._comecou.append(c)
                    c.mostrar_espera(None)
                    c.comecar()
                elif c in self._suspensos:
                    _tirar(self._suspensos, c)
                    c.retomar_suspenso()
            elif c in self._cota:
                continue
            elif c in self._comecou:
                if c not in self._suspensos:
                    self._suspensos.append(c)
                    c.suspender()
            else:
                c.mostrar_espera(TEXTO_NA_FILA.format(nome=dono.nome_fila()))


def _tirar(lista: list, c) -> None:
    """Remove por identidade (clientes são widgets; nada de comparar por igualdade)."""
    for i, x in enumerate(lista):
        if x is c:
            del lista[i]
            return
