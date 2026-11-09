"""Ajustes da área Formatura que valem para tudo (ex.: logo da produtora no encerramento).

Ficam em <system_dir>/FORMATURAS/_ajustes.json, fora das Configurações comuns."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ValidationError

from roteiro_ia.areas.formatura.cadastro import PASTA
from roteiro_ia.config import Settings
from roteiro_ia.safety import safe_mkdir, safe_write_text

ARQUIVO = "_ajustes.json"


class ModeloAno(BaseModel):
    pasta: str | None = None   # vídeos modelo do ano (estudo de estilo)
    mogrt: str | None = None   # cartela editável do ano (o painel preenche os textos)


class AjustesFormatura(BaseModel):
    logo_produtora: str | None = None
    modelos: dict[str, ModeloAno] = {}


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


def modelos_do_ano(s: Settings, ano: int) -> ModeloAno | None:
    """Modelos do ano; sem eles, os do ano mais recente que não passe de `ano`."""
    anos = sorted((int(a) for a in carregar_ajustes(s).modelos if a.isdigit() and int(a) <= ano),
                  reverse=True)
    return carregar_ajustes(s).modelos[str(anos[0])] if anos else None
