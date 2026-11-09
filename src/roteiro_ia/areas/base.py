"""Descrição de uma área de trabalho (Casamento, Formatura…)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Area:
    id: str
    nome: str
    formulario: type
    pode_iniciar: bool = True
    aviso_iniciar: str = ""
    # fábrica do pipeline da área: (req, s, gemini, transcriber, eventos, *, settings_path);
    # None = o Pipeline comum (Casamento)
    pipeline: Callable | None = None
