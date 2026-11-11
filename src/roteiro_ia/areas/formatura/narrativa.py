"""Fala costurada dos alunos nos clipes da Formatura.

1. Cada transcrição vira frases (pontuação ou pausa longa), com o tempo das palavras corrigido
   quando a transcrição estica uma palavra por cima de um silêncio.
2. O Gemini (só texto) lê todas as frases dos alunos, escolhe a melhor tomada de cada ideia,
   descarta bastidores e frases erradas, resume e compõe a narrativa: os alunos se completam
   ao longo do clipe. Ele devolve as PALAVRAS que ficam de cada frase.
3. As palavras que ficam viram pedaços de áudio: repetição, gaguejo, muleta e respiro (pausa
   dentro da frase) ficam de fora. Os pedaços tocam colados, um atrás do outro."""
from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel

from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.models import Word

PALAVRA_MAX_S = 1.0     # palavra mais longa que isto: a transcrição esticou por cima de silêncio
PALAVRA_FIX_S = 0.5     # (fica só o fim dela, que é onde a palavra está)
PAUSA_FRASE_S = 1.2     # pausa que separa frases mesmo sem pontuação
MAX_PALAVRAS = 45       # frase longa demais é quebrada na vírgula (o dobro: em qualquer palavra)
RESPIRO_S = 0.3         # pausa maior que isto dentro do que fica é cortada (respiro)
ANTES_S = 0.08          # folga antes da 1ª palavra de um pedaço
DEPOIS_S = 0.12         # e depois da última
MIN_PALAVRAS_VIDEO = 8  # vídeo com menos palavras não entra na conversa
MAX_FRASES = 260
MULETAS = {"hã", "ãh", "ah", "ahn", "hum", "hmm", "uh", "eh", "éé", "ééé", "humm", "aham"}


@dataclass
class Frase:
    id: int
    rel_path: str
    palavras: list[Word]
    antes: float          # fim da palavra anterior no vídeo (limite para a folga)
    depois: float | None  # início da palavra seguinte

    @property
    def texto(self) -> str:
        return " ".join(w.text for w in self.palavras)

    @property
    def dur(self) -> float:
        return self.palavras[-1].end_s - self.palavras[0].start_s


@dataclass
class Pedaco:
    rel_path: str
    in_s: float
    out_s: float
    texto: str = ""

    @property
    def dur(self) -> float:
        return self.out_s - self.in_s


def _nome(rel: str) -> str:
    return re.split(r"[\\/]", rel)[-1]


def _norm(t: str) -> str:
    return re.sub(r"[^\w]", "", t.casefold())


def corrigir_tempos(ws: list[Word]) -> list[Word]:
    out: list[Word] = []
    for w in ws:
        if w.end_s - w.start_s > PALAVRA_MAX_S:
            w = w.model_copy(update={"start_s": max(w.end_s - PALAVRA_FIX_S,
                                                   out[-1].end_s if out else 0.0)})
        out.append(w)
    return out


def frases_do_video(rel: str, ws: list[Word], primeiro_id: int) -> list[Frase]:
    ws = corrigir_tempos([w for w in ws if w.text.strip()])
    grupos: list[list[int]] = []
    atual: list[int] = []
    for i, w in enumerate(ws):
        if atual and w.start_s - ws[atual[-1]].end_s > PAUSA_FRASE_S:
            grupos.append(atual)
            atual = []
        atual.append(i)
        fim = w.text.rstrip().endswith((".", "!", "?", "…"))
        longa = len(atual) >= MAX_PALAVRAS and w.text.rstrip().endswith((",", ";", ":"))
        if fim or longa or len(atual) >= MAX_PALAVRAS * 2:
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    out = []
    for g in grupos:
        antes = ws[g[0] - 1].end_s if g[0] > 0 else 0.0
        depois = ws[g[-1] + 1].start_s if g[-1] + 1 < len(ws) else None
        out.append(Frase(primeiro_id + len(out), rel, [ws[i] for i in g], antes, depois))
    return out


def alinhar(frase: Frase, texto: str) -> tuple[list[int], int]:
    """Índices das palavras da frase que o texto devolvido mantém (em ordem) e quantas palavras
    do texto não foram achadas."""
    fic = [_norm(w.text) for w in frase.palavras]
    p, kept, faltou = 0, [], 0
    for tok in (_norm(t) for t in texto.split()):
        if not tok:
            continue
        try:
            j = fic.index(tok, p)
        except ValueError:
            faltou += 1
            continue
        kept.append(j)
        p = j + 1
    return kept, faltou


def tirar_tropecos(frase: Frase, kept: list[int]) -> list[int]:
    """Tira muleta, palavra repetida ("eu eu") e gaguejo ("apren aprendi") do que ficou."""
    ws = frase.palavras
    out = []
    for n, i in enumerate(kept):
        t = _norm(ws[i].text)
        prox = _norm(ws[kept[n + 1]].text) if n + 1 < len(kept) else None
        if t in MULETAS or ws[i].text.strip().endswith(("-", "…", "...")) and prox:
            continue
        if prox is not None and kept[n + 1] == i + 1 and (
                t == prox or (len(t) <= 5 and len(prox) > len(t) and prox.startswith(t))):
            continue
        out.append(i)
    return out


def pedacos(frase: Frase, kept: list[int]) -> list[Pedaco]:
    """Palavras que ficam → pedaços de áudio; pula o que saiu e as pausas (respiros)."""
    ws = frase.palavras
    grupos: list[list[int]] = []
    for i in kept:
        if grupos and i == grupos[-1][-1] + 1 and ws[i].start_s - ws[i - 1].end_s <= RESPIRO_S:
            grupos[-1].append(i)
        else:
            grupos.append([i])
    out = []
    for g in grupos:
        a, b = ws[g[0]], ws[g[-1]]
        lo = ws[g[0] - 1].end_s if g[0] > 0 else frase.antes
        hi = ws[g[-1] + 1].start_s if g[-1] + 1 < len(ws) else frase.depois
        ini = a.start_s - min(ANTES_S, max(0.0, (a.start_s - lo) / 2))
        fim = b.end_s + (DEPOIS_S if hi is None else min(DEPOIS_S, max(0.0, (hi - b.end_s) / 2)))
        out.append(Pedaco(frase.rel_path, max(0.0, ini), fim,
                          " ".join(ws[i].text for i in g)))
    return out


# ---------------------------------------------------------------- Gemini
class TrechoEscolhido(BaseModel):
    frase: int
    texto: str


class BlocoEscolhido(BaseModel):
    trechos: list[TrechoEscolhido]


class RespostaNarrativa(BaseModel):
    blocos: list[BlocoEscolhido]


def prompt_narrativa(frases: list[Frase], quem: dict[str, str], contexto: str, alvo_s: float,
                     pedido: str | None) -> str:
    fala_min, fala_max = round(alvo_s * 0.45), round(alvo_s * 0.65)
    linhas = [f"[{f.id}] {_nome(f.rel_path)} ({f.dur:.1f} s): {f.texto}"
              for f in frases]
    videos = [f"- {_nome(r)}: {d}" for r, d in quem.items() if d]
    out = [
        "Você é o editor de um clipe de formatura (vídeo curto com música). Abaixo estão TODAS "
        "as falas gravadas dos alunos, frase por frase, na ordem de gravação. Normalmente são "
        "até 3 alunos; cada um pode ter gravado a mesma fala mais de uma vez, errado, rido, "
        "conversado com a equipe ou com colegas.",
        "",
        f"CONTEXTO DO CLIPE: {contexto}",
        f"DURAÇÃO DO CLIPE: cerca de {round(alvo_s)} s. Fala total: entre {fala_min} e "
        f"{fala_max} s (some as durações das frases que você usar, já descontando o que tirar).",
        "",
        "O QUE FAZER:",
        "1. Escute tudo (leia todas as frases) e entenda o que cada aluno quis dizer.",
        "2. De cada ideia, use só a MELHOR tomada (a mais completa e fluida); descarte as "
        "repetidas, as erradas, os bastidores (\"vou fingir que…\", \"de novo\", \"tá gravando?\"), "
        "as conversas com a equipe e o que não for depoimento.",
        "3. Resuma: em cada frase escolhida tire repetições, gaguejos, muletas (\"é…\", \"né\", "
        "\"tipo\", \"assim\"), começos errados e partes que não acrescentam. O que sobra precisa "
        "ser uma FRASE INTEIRA e natural, com começo, meio e fim.",
        "4. Componha uma narrativa contínua: os alunos se completam, um continua a ideia do "
        "outro (apresentação → o curso e a experiência → o que aprenderam → agradecimento ou "
        "futuro). Alterne os alunos quando fizer sentido; use todos os que tiverem fala boa.",
        "5. Organize em BLOCOS de 2 a 5 trechos (entre um bloco e outro a música respira). "
        "Os blocos vão do começo ao fim do clipe.",
        "",
        "RESPOSTA: para cada trecho, \"frase\" é o número entre colchetes e \"texto\" são "
        "EXATAMENTE as palavras da frase que ficam, na ordem original, sem trocar, corrigir ou "
        "acrescentar palavra nenhuma (só pode tirar). Uma frase pode ser usada uma vez só.",
    ]
    if videos:
        out += ["", "QUEM APARECE EM CADA VÍDEO (da análise das imagens):", *videos]
    if pedido:
        out += ["", f"PEDIDO DE AJUSTE DO EDITOR (siga): {pedido}"]
    out += ["", "FRASES:", *linhas]
    return "\n".join(out)


def escolher_narrativa(c, model: str, frases: list[Frase], quem: dict[str, str], contexto: str,
                       alvo_s: float, pedido: str | None = None
                       ) -> tuple[list[list[list[Pedaco]]], list[str]]:
    """Blocos → trechos → pedaços de áudio. Sem resposta útil: lista vazia e o aviso."""
    if not frases:
        return [], []
    try:
        r: RespostaNarrativa = c.generate_json(model, [], RespostaNarrativa,
                                               prompt_narrativa(frases, quem, contexto, alvo_s,
                                                                pedido))
    except QuotaPaused:
        raise
    except Exception as e:  # noqa: BLE001 — sem a narrativa, o clipe usa as falas do roteiro
        return [], [f"Não consegui compor a fala dos alunos pelo Gemini ({e}); usei as falas "
                    "do roteiro."]
    return montar_blocos(r, frases)


def montar_blocos(r: RespostaNarrativa, frases: list[Frase]
                  ) -> tuple[list[list[list[Pedaco]]], list[str]]:
    por_id = {f.id: f for f in frases}
    usadas: set[int] = set()
    alertas: list[str] = []
    blocos: list[list[list[Pedaco]]] = []
    for b in r.blocos:
        trechos = []
        for t in b.trechos:
            f = por_id.get(t.frase)
            if f is None or t.frase in usadas:
                continue
            kept, faltou = alinhar(f, t.texto)
            kept = tirar_tropecos(f, kept)
            if len(kept) < 2:
                alertas.append(f"Trecho da frase {t.frase} não bateu com a transcrição; ficou "
                               "de fora.")
                continue
            if faltou > max(1, len(t.texto.split()) // 4):
                alertas.append(f"{f.rel_path}: o texto escolhido não bate todo com a fala "
                               f"(\"{t.texto[:60]}…\"); confira o trecho.")
            usadas.add(t.frase)
            trechos.append(pedacos(f, kept))
        if trechos:
            blocos.append(trechos)
    return blocos, alertas
