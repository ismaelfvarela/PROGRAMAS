"""Plano da íntegra: partes, trechos mantidos (sem os espaços mortos) e trocas de imagem.

Todos os tempos estão na linha do tempo da mesa de corte (segundos)."""
from __future__ import annotations

from pydantic import BaseModel

from roteiro_ia.areas.formatura.colacao.defeitos import Defeito
from roteiro_ia.areas.formatura.colacao.frias import BancoFrias
from roteiro_ia.areas.formatura.colacao.partes import ParteNomeada

MARGEM_CORTE_S = 0.5
JUNTAR_S = 0.5
_EPS = 1e-6


class Troca(BaseModel):
    inicio_s: float
    fim_s: float
    motivo: str
    fonte: str  # "iso:<rel>", "fria:<rel>@<ini>-<fim>" ou "sem"


class ParteIntegra(BaseModel):
    numero: int
    codigo: str
    nome: str
    inicio_s: float
    fim_s: float
    trechos: list[tuple[float, float]]
    trocas: list[Troca]
    cortes: list[tuple[float, float]]


class PlanoIntegra(BaseModel):
    partes: list[ParteIntegra]
    alertas: list[str] = []


def assunto(codigo: str) -> str:
    if codigo in ("hino", "encerramento"):
        return "hino"
    return "colacao" if codigo == "colacao" else "outro"


def _menos(base: list[tuple[float, float]], tira: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = list(base)
    for a, b in tira:
        novo = []
        for x, y in out:
            if b <= x or a >= y:
                novo.append((x, y))
                continue
            if a > x:
                novo.append((x, a))
            if b < y:
                novo.append((b, y))
        out = novo
    return [(x, y) for x, y in out if y - x > _EPS]


def _juntar(ds: list[Defeito]) -> list[Defeito]:
    out: list[Defeito] = []
    for d in sorted(ds, key=lambda d: d.inicio_s):
        if out and d.inicio_s - out[-1].fim_s < JUNTAR_S:
            out[-1] = out[-1].model_copy(update={"fim_s": max(out[-1].fim_s, d.fim_s)})
        else:
            out.append(d)
    return out


def _cobrir(x: float, y: float, isos: list[tuple[str, float, float]]) -> tuple[list[tuple[float, float, str]], list[tuple[float, float]]]:
    """(pedaços cobertos por ISO, pedaços que sobraram), a ISO de maior sobreposição primeiro."""
    if y - x <= _EPS:
        return [], []
    melhor = None
    for rel, i0, i1 in isos:
        a, b = max(x, i0), min(y, i1)
        if b - a > _EPS and (melhor is None or b - a > melhor[2] - melhor[1]):
            melhor = (rel, a, b)
    if melhor is None:
        return [], [(x, y)]
    rel, a, b = melhor
    c1, s1 = _cobrir(x, a, isos)
    c2, s2 = _cobrir(b, y, isos)
    return c1 + [(a, b, rel)] + c2, s1 + s2


def montar_plano(partes: list[ParteNomeada], fim_s: float, defeitos_tl: list[Defeito],
                 mortos_tl: list[tuple[float, float]], isos: list[tuple[str, float, float]],
                 frias: BancoFrias) -> PlanoIntegra:
    alertas: list[str] = []
    defeitos = _juntar(defeitos_tl)
    out: list[ParteIntegra] = []
    for n, p in enumerate(partes):
        ini = p.inicio_s
        fim = partes[n + 1].inicio_s if n + 1 < len(partes) else fim_s
        if fim - ini <= _EPS:
            continue
        cortes = []
        for a, b in mortos_tl:
            a, b = max(a + MARGEM_CORTE_S, ini), min(b - MARGEM_CORTE_S, fim)
            if b - a > _EPS:
                cortes.append((a, b))
        trechos = _menos([(ini, fim)], cortes)
        trocas: list[Troca] = []
        for d in defeitos:
            for x, y in trechos:
                a, b = max(d.inicio_s, x), min(d.fim_s, y)
                if b - a <= _EPS:
                    continue
                cobertos, sobras = _cobrir(a, b, isos)
                pedacos = [(c0, c1, f"iso:{rel}") for c0, c1, rel in cobertos]
                for s0, s1 in sobras:
                    t = s0
                    for rel, f0, f1 in frias.escolher(assunto(p.codigo), s1 - s0):
                        pedacos.append((t, t + (f1 - f0), f"fria:{rel}@{f0:.3f}-{f1:.3f}"))
                        t += f1 - f0
                    if s1 - t > _EPS:
                        pedacos.append((t, s1, "sem"))
                        alertas.append(f"{p.nome}: {s1 - t:.1f} s com {d.tipo} sem cobertura "
                                       "(nenhuma câmera ISO nem imagem fria).")
                for c0, c1, fonte in sorted(pedacos):
                    trocas.append(Troca(inicio_s=round(c0, 3), fim_s=round(c1, 3), motivo=d.tipo,
                                        fonte=fonte))
        out.append(ParteIntegra(numero=len(out) + 1, codigo=p.codigo, nome=p.nome, inicio_s=ini,
                                fim_s=fim, trechos=trechos, trocas=trocas, cortes=cortes))
    return PlanoIntegra(partes=out, alertas=alertas)
