"""Partes da cerimônia achadas pela transcrição da mesa de corte (Gemini, só texto)."""
from __future__ import annotations

from pydantic import BaseModel

from roteiro_ia.gemini.client import QuotaPaused

PARTES_PADRAO: list[tuple[str, str]] = [
    ("abertura", "Abertura do Mestre de Cerimônias e Entrada dos Professores"),
    ("entrada_turmas", "Entrada das Turmas"),
    ("hino", "Hino Nacional"),
    ("fala_diretor", "Fala do Diretor"),
    ("colacao", "Colação"),
    ("oradores", "Oradores"),
    ("paraninfos", "Paraninfos"),
    ("homenagens", "Homenagens"),
    ("fala_final", "Fala Final do Diretor"),
    ("encerramento", "Hino e Encerramento"),
]
_NOMES = dict(PARTES_PADRAO)
COMPLETA = "Cerimônia Completa"


class ParteDetectada(BaseModel):
    codigo: str
    curso: str | None = None
    turma: str | None = None
    inicio_s: float


class RespostaPartes(BaseModel):
    partes: list[ParteDetectada]


class ParteNomeada(BaseModel):
    codigo: str
    nome: str
    inicio_s: float


def nome_parte(codigo: str, curso: str | None, turma: str | None) -> str:
    if codigo == "colacao":
        return " - ".join(["Colação", *(x for x in (curso, turma) if x)])
    return _NOMES.get(codigo, codigo)


def _hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def transcricao_em_linhas(palavras: list[tuple[float, str]], passo: float = 15.0) -> str:
    """Uma linha a cada ~`passo` segundos: [H:MM:SS] texto."""
    linhas: list[str] = []
    ini, buf = None, []
    for t, w in sorted(palavras, key=lambda x: x[0]):
        if ini is None or t - ini >= passo:
            if buf:
                linhas.append(f"[{_hms(ini)}] {' '.join(buf)}")
            ini, buf = t, []
        buf.append(w)
    if buf:
        linhas.append(f"[{_hms(ini)}] {' '.join(buf)}")
    return "\n".join(linhas)


def _prompt(linhas: str, turmas: list[tuple[str, str]], duracao_s: float, pedido: str | None) -> str:
    partes = "\n".join(f"- {c}: {n}" for c, n in PARTES_PADRAO)
    tl = "\n".join(f"- {c} — {t}" for c, t in turmas) or "- (não informadas)"
    out = [
        "Você é assistente de edição da produtora Fokuss. Abaixo está a transcrição de uma "
        f"cerimônia de colação de grau gravada pela mesa de corte (duração {_hms(duracao_s)}).",
        "Ache onde COMEÇA cada parte da cerimônia (o mestre de cerimônias costuma anunciar). "
        "Devolva uma lista com codigo, inicio_s (segundos desde o começo) e, para a colação de "
        "cada turma, curso e turma exatamente como na lista de turmas. Uma parte que não "
        "aconteceu fica de fora. A colação de cada turma é uma parte separada (codigo colacao).",
        "Partes (codigo: nome), na ordem em que costumam acontecer:", partes,
        "Turmas que se formam nesta cerimônia (curso — turma), na ordem:", tl,
    ]
    if pedido:
        out += ["", f"PEDIDO DE AJUSTE DO EDITOR (siga): {pedido}"]
    out += ["", "TRANSCRIÇÃO:", linhas or "(sem fala transcrita)"]
    return "\n".join(out)


def detectar_partes(c, model: str, linhas: str, turmas: list[tuple[str, str]], duracao_s: float,
                    pedido: str | None = None) -> tuple[list[ParteNomeada], list[str]]:
    """Partes validadas (ordem crescente, dentro da duração, códigos conhecidos) e alertas."""
    try:
        r: RespostaPartes = c.generate_json(model, [], RespostaPartes,
                                            _prompt(linhas, turmas, duracao_s, pedido))
    except QuotaPaused:
        raise
    except Exception as e:  # noqa: BLE001 — sem partes, a íntegra sai inteira
        return ([ParteNomeada(codigo="completa", nome=COMPLETA, inicio_s=0.0)],
                [f"Não consegui separar as partes pelo Gemini ({e}); a íntegra saiu numa "
                 "sequência só."])
    validas = [p for p in r.partes if p.codigo in _NOMES and 0 <= p.inicio_s < duracao_s]
    validas.sort(key=lambda p: p.inicio_s)
    partes = [ParteNomeada(codigo=p.codigo, nome=nome_parte(p.codigo, p.curso, p.turma),
                           inicio_s=p.inicio_s) for p in validas]
    achadas = {(p.curso, p.turma) for p in validas if p.codigo == "colacao"}
    alertas = [f"Não achei a colação da turma {cu} — {tu} na transcrição; confira."
               for cu, tu in turmas if (cu, tu) not in achadas]
    if not partes:
        partes = [ParteNomeada(codigo="completa", nome=COMPLETA, inicio_s=0.0)]
        alertas.append("O Gemini não devolveu nenhuma parte válida; a íntegra saiu numa "
                       "sequência só.")
    elif partes[0].inicio_s > 0:
        partes[0] = partes[0].model_copy(update={"inicio_s": 0.0})  # nada antes da 1ª parte se perde
    return partes, alertas
