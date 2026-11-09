"""Roteiro dos clipes de abertura (com o grande final) e encerramento (com o logo) da colação."""
from __future__ import annotations

from datetime import date
from typing import Callable

from roteiro_ia.areas.formatura.cadastro import Formatura
from roteiro_ia.areas.formatura.colacao.partes import ParteNomeada
from roteiro_ia.areas.formatura.projeto import ProjetoFormatura
from roteiro_ia.script.generate import _FORMATO, _style_text, build_catalog, music_shortlist

ABERTURA_MAX_S = 180
CARTELA_S = 5
LOGO_S = 4


def nomes_clipes(n_partes: int) -> tuple[str, str]:
    return "00 - Abertura", f"{n_partes + 1:02d} - Encerramento"


def _hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def _data(d: str | None) -> str:
    try:
        return date.fromisoformat(d).strftime("%d/%m/%Y") if d else ""
    except ValueError:
        return d or ""


def _dados(pf: ProjetoFormatura, ficha: Formatura | None, data_evento: str | None) -> str:
    linhas = []
    if ficha is not None:
        linhas += [f"- instituição: {ficha.instituicao}", f"- formatura: {ficha.ano}/{ficha.semestre}"]
    if pf.turmas_colacao:
        linhas.append("- turmas: " + "; ".join(f"{c} — {t}" for c, t in pf.turmas_colacao))
    for rot, v in (("data", _data(data_evento)), ("local", pf.local), ("cidade", pf.cidade)):
        if v:
            linhas.append(f"- {rot}: {v}")
    return "\n".join(linhas) or "- (sem dados cadastrados)"


def contexto_abertura_encerramento(pf: ProjetoFormatura, ficha: Formatura | None,
                                   partes: list[ParteNomeada],
                                   data_evento: str | None) -> Callable[..., str]:
    """Contexto (assinatura de generate._context) para as duas peças: abertura e encerramento."""
    def ctx(db, idx, style, n_episodios, derivados, compact: bool = False) -> str:
        regras = f"""Regras de edição da Fokuss para os clipes da colação de grau (siga todas):
1. Devolva EXATAMENTE duas peças, nenhum episódio: tipo "trailer" (numero null) = ABERTURA; tipo "teaser" (numero null) = ENCERRAMENTO. Sem gancho (gancho null, gancho_resolve_em null).
2. ABERTURA, até {ABERTURA_MAX_S} s, nesta ordem: (a) os primeiros {CARTELA_S} s ficam reservados para a cartela com os dados do evento (abaixo) — a cena de abertura é o fundo dela, imagem bonita e estável; (b) vídeo da decoração; (c) bastidores; (d) o grande final: os melhores momentos da formatura inteira, com trechos curtos de falas marcantes de alunos e paraninfos (coloque a fala em 'fala').
3. ENCERRAMENTO, 60–90 s, bem animado: comemoração, beca jogada, abraços, alegria; cortes no ritmo da música. Ele termina com o logo da produtora: deixe livres os últimos {LOGO_S} s (o logo entra na montagem).
4. Qualidade de imagem: nada de chicote, imagem desfocada ou cena mal enquadrada. O assunto vale mais que a técnica: um momento importante que só existe numa imagem imperfeita entra pelo menor tempo possível, com alerta.
5. Música comercial, popular e o mais moderna possível (público jovem): 2–3 opções da biblioteca para cada peça (só as da lista abaixo) e sugestões pelo nome com origem "popular". A abertura pode ser épica ou emocionante; o encerramento, animado.
6. Mídias [só áudio] servem só como 'fala' sobre uma cena de vídeo do mesmo momento."""
        tl = "\n".join(f"[{_hms(p.inicio_s)}] {p.nome}" for p in partes) or "(sem partes)"
        out = [
            "Você é o roteirista da produtora Fokuss e vai escrever o PRÉ-ROTEIRO dos clipes de "
            "abertura e encerramento de uma colação de grau.",
            "Dados do evento (vão na cartela de abertura):", _dados(pf, ficha, data_evento), "",
            regras, "", _FORMATO, "",
            "PARTES DA CERIMÔNIA (horário na gravação da mesa de corte — ajuda a achar as "
            "colações, os paraninfos, os oradores e o fim da festa):", tl,
        ]
        if style is not None:
            out += ["", _style_text(style)]
        trilhas = music_shortlist(idx)
        out += [
            "", "CATÁLOGO DO MATERIAL (rel_path | início–fim do segmento | dia | momento | emoção | "
            "qualidade | descrição | falas | gancho):",
            build_catalog(db, compact=compact) or "(vazio)",
            "", "TRILHAS DA BIBLIOTECA (path | BPM | perfil | duração | instrumental ou cantada | "
            "clima | instrumentos | tipo de voz | intro instrumental | tonalidade):",
            trilhas or "(nenhuma trilha disponível; sugira só pelo nome, com origem \"popular\")",
        ]
        return "\n".join(out)
    return ctx
