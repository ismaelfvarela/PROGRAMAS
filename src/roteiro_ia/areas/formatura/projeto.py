"""Dados próprios de um projeto da Formatura: ANALISE/formatura.json, ao lado do projeto.json comum."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from roteiro_ia import recentes
from roteiro_ia.areas.formatura.funcoes import FuncaoFormatura
from roteiro_ia.areas.formatura.tipos import TipoTrabalho
from roteiro_ia.config import Settings
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import ProjectRequest
from roteiro_ia.safety import safe_write_text

ARQUIVO = "formatura.json"


class ProjetoFormatura(BaseModel):
    tipo: TipoTrabalho
    formatura_id: str
    curso: str | None = None
    turma: str | None = None
    duracao_min: float | None = None
    funcoes: dict[str, FuncaoFormatura] = {}
    canais_mesa: Literal["misturado", "L_mesa_R_ambiente"] = "misturado"
    duplicado_de: str | None = None
    seguir_ideia: bool = True
    musica: str | None = None
    local: str | None = None
    cidade: str | None = None
    turmas_colacao: list[tuple[str, str]] = []


@dataclass
class RequestFormatura(ProjectRequest):
    """O pedido comum mais os dados da Formatura (em memória; no disco vão para formatura.json)."""
    formatura: ProjetoFormatura | None = None


def caminho(analysis_dir: Path) -> Path:
    return Path(analysis_dir) / ARQUIVO


def salvar_projeto(analysis_dir: Path, pf: ProjetoFormatura, s: Settings) -> None:
    safe_write_text(caminho(analysis_dir), pf.model_dump_json(indent=2), s)


def carregar_projeto(analysis_dir: Path) -> ProjetoFormatura | None:
    try:
        return ProjetoFormatura.model_validate_json(caminho(analysis_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def _chave(p: Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def projetos_da_area(s: Settings) -> list[tuple[Path, str, ProjetoFormatura]]:
    """(pasta do evento, disco, dados) dos projetos de Formatura conhecidos (recentes e disco)."""
    out = []
    for r in recentes.listar(s, [s.work_drive], area="formatura"):
        try:
            ad = Path(build_event_paths(r.pasta, s, r.disco).analysis_dir)
        except ValueError:
            continue
        pf = carregar_projeto(ad)
        if pf is not None:
            out.append((r.pasta, r.disco, pf))
    return out


def musicas_usadas(s: Settings, formatura_id: str, exceto: Path | None) -> set[str]:
    """Trilhas já usadas por outros projetos da mesma formatura (para não repetir a música)."""
    ex = _chave(exceto) if exceto is not None else None
    return {pf.musica for pasta, _d, pf in projetos_da_area(s)
            if pf.formatura_id == formatura_id and pf.musica and _chave(pasta) != ex}
