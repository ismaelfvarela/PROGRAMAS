"""Tipos de trabalho da Formatura: clipes (Oficina, Feira, Prova de toga, Paraninfo) e colação."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class TipoTrabalho(StrEnum):
    oficina = "oficina"
    feira = "feira"
    prova_toga = "prova_toga"
    paraninfo = "paraninfo"
    colacao = "colacao"


@dataclass(frozen=True)
class InfoTipo:
    nome: str
    grupo: Literal["clipe", "colacao"]
    turma: Literal["obrigatoria", "opcional", "nenhuma"]
    duracao_min: float | None


INFO_TIPO: dict[TipoTrabalho, InfoTipo] = {
    TipoTrabalho.oficina: InfoTipo("Oficina", "clipe", "obrigatoria", 4),
    TipoTrabalho.feira: InfoTipo("Feira", "clipe", "nenhuma", 8),
    TipoTrabalho.prova_toga: InfoTipo("Prova de toga", "clipe", "opcional", 3),
    TipoTrabalho.paraninfo: InfoTipo("Escolha do paraninfo", "clipe", "opcional", 3),
    TipoTrabalho.colacao: InfoTipo("Colação de grau", "colacao", "obrigatoria", None),
}

TIPOS_CLIPE = [t for t in TipoTrabalho if INFO_TIPO[t].grupo == "clipe"]
