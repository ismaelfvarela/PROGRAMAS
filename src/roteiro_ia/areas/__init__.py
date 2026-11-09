"""Áreas de trabalho. As áreas só são importadas ao usar, para não criar ciclo com a interface."""
from __future__ import annotations

from roteiro_ia.areas.base import Area


def _todas() -> list[Area]:
    from roteiro_ia.areas.casamento import CASAMENTO
    from roteiro_ia.areas.formatura import FORMATURA
    return [CASAMENTO, FORMATURA]


class _Areas:
    """Lista preguiçosa: AREAS se comporta como list[Area] (iteração, índice, len)."""

    def __init__(self) -> None:
        self._lista: list[Area] | None = None

    def _get(self) -> list[Area]:
        if self._lista is None:
            self._lista = _todas()
        return self._lista

    def __iter__(self):
        return iter(self._get())

    def __len__(self) -> int:
        return len(self._get())

    def __getitem__(self, i):
        return self._get()[i]


AREAS = _Areas()


def area_por_id(id: str) -> Area:
    """Id desconhecido cai no Casamento."""
    for a in AREAS:
        if a.id == id:
            return a
    return AREAS[0]
