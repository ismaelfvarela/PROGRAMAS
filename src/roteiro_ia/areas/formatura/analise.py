"""Textos da análise do Gemini por tipo de trabalho da Formatura (as regras comuns são as mesmas)."""
from __future__ import annotations

from roteiro_ia.areas.formatura.momentos import MOMENTOS_POR_TIPO, PROBLEMAS_TECNICOS
from roteiro_ia.areas.formatura.tipos import INFO_TIPO, TipoTrabalho
from roteiro_ia.gemini.analysis import TextosAnalise


def _textos(tipo: TipoTrabalho) -> TextosAnalise:
    nome = INFO_TIPO[tipo].nome
    material = (f"Este material é de um clipe de {nome}." if INFO_TIPO[tipo].grupo == "clipe"
                else "Este material é da cerimônia de colação de grau.")
    return TextosAnalise(
        papel=f"Você é um assistente de edição de vídeos de formatura da produtora Fokuss. {material}",
        evento="da mesma formatura",
        momentos=list(MOMENTOS_POR_TIPO[tipo]),
        problemas="falhas técnicas (" + ", ".join(PROBLEMAS_TECNICOS) + ", áudio ruim)")


TEXTOS_POR_TIPO: dict[TipoTrabalho, TextosAnalise] = {t: _textos(t) for t in TipoTrabalho}
