"""Roteiro pelo chat (sem a API): o sistema monta o MESMO pedido que iria para a API, o editor
manda no chat do site (Gemini, Claude, ChatGPT ou a IA interna), cola a resposta de volta e o
sistema confere com as mesmas regras; havendo problemas, monta o pedido de correção (até
CORRECTION_ROUNDS rodadas) e, no fim, o que continuar inválido sai e vira alerta."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

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


class SemJson(RespostaInvalida):
    """O chat respondeu em texto corrido (sem nenhum JSON)."""


def instrucao_json() -> str:
    schema = json.dumps(Roteiro.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    return ("FORMATO DA RESPOSTA (obrigatório): responda SOMENTE com um único JSON válido — sem "
            "texto antes ou depois, sem comentários — que siga exatamente este JSON Schema:\n"
            + schema)


AVISO_INICIO = ("ATENÇÃO — FORMATO DA RESPOSTA: este pedido é lido por um programa. Responda "
                "APENAS com um JSON (começando com { e terminando com }), no formato do JSON "
                "Schema que está no FIM deste texto. Nada de texto corrido, títulos, listas ou "
                "markdown fora do JSON.")


def texto_para_o_chat(pedido: str) -> str:
    """O formato vai no começo e no fim: no chat, anexos grandes têm o fim mal lido."""
    return f"{AVISO_INICIO}\n\n{pedido}\n\n{instrucao_json()}\n"


def mensagem_do_anexo(nome_arquivo: str) -> str:
    """O que mandar escrito junto do arquivo anexado (o arquivo grande não cabe para colar)."""
    return (f"Anexei o arquivo {nome_arquivo}. Siga TODAS as instruções dele e responda APENAS "
            "com o JSON completo, no formato do JSON Schema que está no fim do arquivo — sem "
            "texto antes ou depois, sem markdown, sem explicações. Comece a resposta com { e "
            "termine com }. Se a resposta for longa, escreva o JSON inteiro mesmo assim.")


def mensagem_so_json() -> str:
    """Para o MESMO chat, quando ele respondeu em texto corrido em vez do JSON."""
    return ("Sua resposta veio em texto corrido, mas ela é lida por um programa. Converta o "
            "roteiro que você acabou de escrever para JSON — mesmas peças, cenas (rel_path, "
            "start_s, end_s exatamente como no catálogo), falas e trilhas — e responda APENAS "
            "com o JSON, começando com { e terminando com }, sem nenhum texto em volta.\n\n"
            + instrucao_json())


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
            raise SemJson("O chat respondeu em texto corrido, sem o JSON. Clique em \"Pedir só "
                          "o JSON\", cole no MESMO chat e envie: ele converte o que escreveu.")
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
        return Roteiro.model_validate(normalizar(dados))
    except ValidationError as e:
        faltas = "; ".join(f"{'.'.join(str(x) for x in er['loc'])}: {er['msg']}"
                           for er in e.errors()[:5])
        raise RespostaInvalida(f"O JSON não está no formato do roteiro: {faltas}") from None


_ORIGENS = {"biblioteca", "musicbed", "popular"}
_CORTES = {"1-3", "2-4", "misto"}
_TIPOS = {"episodio", "trailer", "teaser", "stories"}


def _lista_txt(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v if str(x).strip()]


def _cena(c):
    """Cena do chat → SceneRef: sem descrição, usa o motivo (ou a fala)."""
    if not isinstance(c, dict):
        return c
    c = dict(c)
    c.setdefault("fala", None)
    c.setdefault("motivo", None)
    if not str(c.get("descricao") or "").strip():
        c["descricao"] = c.get("motivo") or c.get("fala") or "(sem descrição)"
    return c


def _trilha(t, termos: list[str]):
    """Trilha do chat → MusicSuggestion (campos que faltam preenchidos). Só termos de busca
    (sem música) vão para os termos da peça. Devolve None quando não sobra trilha."""
    if not isinstance(t, dict):
        return None
    t = dict(t)
    for k in ("termos_musicbed", "termos", "busca"):
        termos += _lista_txt(t.pop(k, None))
    path = t.get("path") or None
    titulo = t.get("titulo") or t.get("nome") or (Path(str(path)).stem if path else "")
    if not titulo and not path:
        return None
    origem = t.get("origem") if t.get("origem") in _ORIGENS else ("biblioteca" if path else "popular")
    return {
        "origem": origem, "path": path, "titulo": titulo, "bpm": t.get("bpm"),
        "clima": t.get("clima") or "", "motivo": t.get("motivo") or "",
        "padrao_corte": t.get("padrao_corte") if t.get("padrao_corte") in _CORTES else "misto",
        "exige_licenca": bool(t.get("exige_licenca", origem == "popular")),
        "trecho_inicio_s": t.get("trecho_inicio_s"),
    }


def _peca(p):
    if not isinstance(p, dict):
        return p
    p = dict(p)
    for k in ("abertura", "gancho"):
        if p.get(k) is not None:
            p[k] = _cena(p[k])
    p.setdefault("gancho", None)
    p["desenvolvimento"] = [_cena(c) for c in p.get("desenvolvimento") or []]
    termos = _lista_txt(p.get("termos_musicbed"))
    trilhas = [x for x in (_trilha(t, termos) for t in p.get("trilhas") or []) if x]
    p["trilhas"] = trilhas
    p["termos_musicbed"] = list(dict.fromkeys(termos))
    p["misturas"] = _lista_txt(p.get("misturas"))
    p.setdefault("titulo", "")
    p.setdefault("tema", "")
    p.setdefault("gancho_resolve_em", None)
    p.setdefault("curva_emocao", [])
    if p.get("tipo") not in _TIPOS:
        p["tipo"] = "episodio"
    p.setdefault("numero", None)
    if p.get("duracao_estimada_s") is None:
        cenas = [p.get("abertura"), *p["desenvolvimento"], p.get("gancho")]
        p["duracao_estimada_s"] = sum(float(c["end_s"]) - float(c["start_s"])
                                      for c in cenas if isinstance(c, dict)
                                      and "start_s" in c and "end_s" in c)
    return p


def normalizar(dados):
    """Desvios comuns do chat (nomes de campos, campos faltando) → formato do roteiro. O
    conteúdo não muda; o que for inválido (cena ou trilha que não existe) a conferência acusa."""
    if not isinstance(dados, dict):
        return dados
    d = dict(dados)
    if "arco" not in d:
        for k in ("arco_da_serie", "arco_serie", "arco_narrativo"):
            if k in d:
                d["arco"] = d.pop(k)
                break
    d.setdefault("arco", "")
    if "pecas" not in d and "peças" in d:
        d["pecas"] = d.pop("peças")
    d["pecas"] = [_peca(p) for p in d.get("pecas") or []]
    d["alertas"] = _lista_txt(d.get("alertas"))
    return d


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
