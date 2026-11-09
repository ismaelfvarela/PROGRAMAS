"""Descrição de uma área de trabalho (Casamento, Formatura…)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Area:
    id: str
    nome: str
    formulario: type
    pode_iniciar: bool = True
    aviso_iniciar: str = ""
