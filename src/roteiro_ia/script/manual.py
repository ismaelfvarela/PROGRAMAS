"""Roteiro pelo chat (sem a API): o sistema monta o MESMO pedido que iria para a API, o editor
manda no chat do site (Gemini, Claude, ChatGPT ou a IA interna), cola a resposta de volta e o
sistema confere com as mesmas regras; havendo problemas, monta o pedido de correção (até
CORRECTION_ROUNDS rodadas) e, no fim, o que continuar inválido sai e vira alerta."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from roteiro_ia.db import ProjectDB
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.script.generate import (CORRECTION_ROUNDS, Roteiro, finalizar_roteiro,
                                        pedido_correcao, validate_refs)

# chats que aguentam o pedido inteiro de um casamento (~200 mil tokens); nos outros, a versão
# compacta (sem os trechos fracos, descrições curtas) vem marcada
CHATS_PEDIDO_INTEIRO = {"gemini"}
# id → (nome, endereço do chat). A IA interna ainda não existe: entra quando for instalada.
CHATS = {
    "gemini": ("Gemini", "https://gemini.google.com/app"),
    "claude": ("Claude", "https://claude.ai/new"),
    "chatgpt": ("ChatGPT", "https://chatgpt.com/"),
    "interna": ("IA interna", None),
}
CHAT_PADRAO = "gemini"
LIMITE_COLAR = 60_000  # acima disso (caracteres), anexar o arquivo no chat em vez de colar


class RespostaInvalida(ValueError):
    pass


def instrucao_json() -> str:
    schema = json.dumps(Roteiro.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    return ("FORMATO DA RESPOSTA (obrigatório): responda SOMENTE com um único JSON válido — sem "
            "texto antes ou depois, sem comentários — que siga exatamente este JSON Schema:\n"
            + schema)


def texto_para_o_chat(pedido: str) -> str:
    return f"{pedido}\n\n{instrucao_json()}\n"


def ler_resposta(texto: str) -> Roteiro:
    """O JSON do roteiro colado do chat (aceita ```json … ``` e texto em volta)."""
    t = (texto or "").strip()
    if not t:
        raise RespostaInvalida("Cole a resposta do chat.")
    cerca = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if cerca:
        t = cerca.group(1)
    else:
        i, j = t.find("{"), t.rfind("}")
        if i < 0:
            raise RespostaInvalida("A resposta não tem um JSON (deve começar com { e terminar com }).")
        if j <= i:
            raise RespostaInvalida("A resposta está incompleta (o JSON não termina): o chat cortou. "
                                   "Peça no chat \"continue de onde parou\" e cole tudo junto.")
        t = t[i:j + 1]
    try:
        dados = json.loads(t)
    except ValueError as e:
        raise RespostaInvalida(f"O JSON da resposta está incompleto ou quebrado ({e}). Peça no "
                               "chat: \"responda de novo só com o JSON completo\".") from None
    try:
        return Roteiro.model_validate(dados)
    except ValidationError as e:
        faltas = "; ".join(f"{'.'.join(str(x) for x in er['loc'])}: {er['msg']}"
                           for er in e.errors()[:5])
        raise RespostaInvalida(f"O JSON não está no formato do roteiro: {faltas}") from None


@dataclass
class SessaoManual:
    """Uma rodada de roteiro pelo chat (o pedido inicial e até CORRECTION_ROUNDS correções)."""
    db: ProjectDB
    idx: MusicIndex
    base: str
    pedido: str
    pedido_ajuste: str | None = None
    correcoes: int = 0
    ultimo: Roteiro | None = None
    problemas: list[str] = field(default_factory=list)

    def texto_inicial(self) -> str:
        return texto_para_o_chat(self.pedido)

    def conferir(self, resposta: str) -> list[str]:
        """Lê e confere a resposta; devolve os problemas (vazio = pronto para usar)."""
        r = ler_resposta(resposta)
        self.problemas = validate_refs(r, self.db, self.idx)
        self.ultimo = r
        return self.problemas

    def pode_corrigir(self) -> bool:
        return bool(self.problemas) and self.correcoes < CORRECTION_ROUNDS

    def texto_correcao(self) -> str:
        if self.ultimo is None or not self.problemas:
            raise ValueError("Não há problemas para corrigir.")
        self.correcoes += 1
        return texto_para_o_chat(pedido_correcao(self.base, self.ultimo, self.problemas,
                                                 self.pedido_ajuste))

    def aceitar(self, avisos: list[str] | None = None) -> Roteiro:
        """Grava no banco (o que continuar inválido sai e vira alerta)."""
        if self.ultimo is None:
            raise ValueError("Confira uma resposta antes de usar.")
        return finalizar_roteiro(self.ultimo, self.db, self.idx, self.problemas, avisos)
