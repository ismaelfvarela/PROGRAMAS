"""Ajustes da área Formatura que valem para tudo (ex.: logo da produtora no encerramento).

Ficam em <system_dir>/FORMATURAS/_ajustes.json, fora das Configurações comuns."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ValidationError

from roteiro_ia.areas.formatura.cadastro import PASTA
from roteiro_ia.config import Settings
from roteiro_ia.safety import safe_mkdir, safe_write_text

ARQUIVO = "_ajustes.json"


class AjustesFormatura(BaseModel):
    logo_produtora: str | None = None


def _caminho(s: Settings) -> Path:
    return Path(s.system_dir) / PASTA / ARQUIVO


def carregar_ajustes(s: Settings) -> AjustesFormatura:
    try:
        return AjustesFormatura.model_validate_json(_caminho(s).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return AjustesFormatura()


def salvar_ajustes(s: Settings, a: AjustesFormatura) -> None:
    safe_mkdir(_caminho(s).parent, s)
    safe_write_text(_caminho(s), a.model_dump_json(indent=2), s)
