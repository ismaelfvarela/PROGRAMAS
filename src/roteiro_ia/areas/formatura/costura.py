"""Montagem do clipe com a fala costurada dos alunos (narrativa.py):

- a voz corre por quase todo o clipe, em blocos; entre um bloco e outro a música respira;
- por cima da voz vão imagens de cobertura (B-roll), cortadas no compasso e limpas (as mesmas
  regras do acabamento); às vezes a imagem volta no rosto de quem fala, em sincronia com a voz:
  no começo e no fim de cada bloco e na primeira vez que cada aluno aparece;
- as cenas de fala do roteiro saem (a fala agora vem da narrativa); as sem fala viram cobertura,
  completadas pelas imagens do material gravadas perto de quem fala."""
from __future__ import annotations

from typing import Callable

from roteiro_ia.areas.formatura.acabamento import (MIN_CENA_S, Voz, _Montagem, _por_perto,
                                                   batidas_permitidas)
from roteiro_ia.areas.formatura.movimento import Medidas
from roteiro_ia.areas.formatura.narrativa import Pedaco
from roteiro_ia.models import TrackInfo
from roteiro_ia.script.generate import Piece, SceneRef

COLA_S = 0.04          # entre dois pedaços da mesma frase (respiro já tirado)
ENTRE_FRASES_S = 0.35  # entre frases do mesmo bloco
INTRO_MIN_S = 4.0      # música sozinha antes da primeira fala
FIM_MIN_S = 4.0        # e depois da última
ENTRE_BLOCOS_MIN_S = 3.0
INTRO_MAX_S = 12.0
ROSTO_MIN_S = 1.0
ROSTO_ALVO_S = 2.5
ROSTO_MAX_S = 3.5
ROSTO_DE_NOVO_S = 6.0  # rosto não volta antes disto desde o último


def _layout(blocos: list[list[list[Pedaco]]], alvo_s: float
            ) -> tuple[list[list[list[tuple[float, Pedaco]]]], float]:
    """Posição de cada pedaço na timeline e a duração total do clipe."""
    durs = []
    for b in blocos:
        d = 0.0
        for k, tr in enumerate(b):
            d += sum(pc.dur for pc in tr) + COLA_S * (len(tr) - 1)
            d += ENTRE_FRASES_S if k < len(b) - 1 else 0.0
        durs.append(d)
    voz = sum(durs)
    n = len(blocos)
    minimo = INTRO_MIN_S + FIM_MIN_S + ENTRE_BLOCOS_MIN_S * max(0, n - 1)
    total = max(alvo_s, voz + minimo)
    livre = total - voz
    intro = min(INTRO_MAX_S, max(INTRO_MIN_S, livre * 0.15))
    fim = min(INTRO_MAX_S, max(FIM_MIN_S, livre * 0.15))
    if n > 1:
        entre = max(ENTRE_BLOCOS_MIN_S, (livre - intro - fim) / (n - 1))
    else:
        entre = 0.0
        intro = fim = max(INTRO_MIN_S, livre / 2)
    total = intro + voz + entre * max(0, n - 1) + fim
    t = intro
    out = []
    for b, d in zip(blocos, durs):
        bl = []
        x = t
        for k, tr in enumerate(b):
            lst = []
            for j, pc in enumerate(tr):
                lst.append((x, pc))
                x += pc.dur + (COLA_S if j < len(tr) - 1 else 0.0)
            bl.append(lst)
            x += ENTRE_FRASES_S
        out.append(bl)
        t += d + entre
    return out, total


def _rosto(mt: _Montagem, trecho: list[tuple[float, Pedaco]], desde: float
           ) -> SceneRef | None:
    """Janela no compasso, dentro de um pedaço, com o rosto de quem fala em sincronia."""
    for x0, pc in trecho:
        x1 = x0 + pc.dur
        cands = [b for b in mt.perm if max(x0 - 0.2, desde) - 1e-6 <= b <= x1 - ROSTO_MIN_S]
        for b1 in cands[:3]:
            fins = [b for b in mt.perm if b1 + ROSTO_MIN_S - 1e-6 <= b <= min(x1 + 0.1,
                                                                              b1 + ROSTO_MAX_S)]
            if not fins:
                continue
            b2 = min(fins, key=lambda b: abs(b - (b1 + ROSTO_ALVO_S)))
            b1q, b2q = mt.q(b1), mt.q(b2)
            ini = pc.in_s + (b1q - x0)
            if ini < 0:
                continue
            return SceneRef(rel_path=pc.rel_path, start_s=ini, end_s=ini + (b2q - b1q),
                            descricao="aluno falando",
                            fala=" ".join(c.texto for _x, c in trecho) or "(fala do aluno)",
                            motivo="rosto",
                            lembranca=False)
    return None


def montar_narrativa(p: Piece, track: TrackInfo | None, inicio: float, padrao: str,
                     medir: Callable[[str], Medidas | None], duracoes: dict[str, float],
                     rate: tuple[int, int], blocos: list[list[list[Pedaco]]], alvo_s: float,
                     vizinhos: Callable[[str], list[str]] = lambda _r: [],
                     extras: list[SceneRef] = ()) -> tuple[list[str], list[Voz]]:
    """Refaz a peça (no lugar) com a voz costurada por baixo. Devolve (avisos, vozes)."""
    fps_seq = rate[0] / rate[1]
    perm = batidas_permitidas(track, inicio, padrao) if track is not None else []
    cenas = [p.abertura, *p.desenvolvimento] + ([p.gancho] if p.gancho is not None else [])
    falantes = {pc.rel_path for b in blocos for tr in b for pc in tr}
    # a cobertura nunca usa o vídeo de quem fala (a boca mexeria com outra voz por cima)
    cobertura = [s for s in cenas if not s.fala and s.rel_path not in falantes]
    extras = [x for x in extras if x.rel_path not in falantes]
    mt = _Montagem(perm, fps_seq, medir, duracoes,
                   lambda r: [v for v in vizinhos(r) if v not in falantes],
                   {s.rel_path for s in cobertura} | falantes)
    pos, total = _layout(blocos, alvo_s)
    total = mt.batida(total, total - 1.0, total + 2.0)
    vozes: list[Voz] = []
    for bl in pos:
        for tr in bl:
            for x0, pc in tr:
                vozes.append(Voz(inicio_s=mt.q(x0), rel_path=pc.rel_path, in_s=pc.in_s,
                                 dur_s=pc.dur))
                mt.usar(pc.rel_path, pc.in_s, pc.out_s)  # a cobertura não mostra o aluno falando
    # rostos: começo de cada bloco e 1ª vez de cada vídeo de aluno
    rostos: list[tuple[float, float, SceneRef]] = []
    vistos: set[str] = set()
    ultimo = -1e9
    for bl in pos:
        for k, tr in enumerate(bl):
            rel = tr[0][1].rel_path
            quer = k == 0 or k == len(bl) - 1 or rel not in vistos  # abre, fecha, aluno novo
            vistos.add(rel)
            if not quer:
                continue
            fim_ant = rostos[-1][1] if rostos else 0.0
            desde = max(fim_ant + MIN_CENA_S, ultimo + ROSTO_DE_NOVO_S, MIN_CENA_S)
            r = _rosto(mt, tr, desde)
            if r is None:
                continue
            x0, pc = next((x, c) for x, c in tr if c.rel_path == r.rel_path
                          and c.in_s - 1e-6 <= r.start_s <= c.out_s)
            a = mt.q(x0 + (r.start_s - pc.in_s))
            b = mt.q(a + (r.end_s - r.start_s))
            if b > total - MIN_CENA_S:
                continue
            rostos.append((a, b, r))
            ultimo = a
    # cobertura entre os rostos
    fonte = list(cobertura)
    falam = [pc.rel_path for bl in pos for tr in bl for _x, pc in tr]
    livres = [x for x in extras if x.rel_path not in mt.usados]
    vistos_ex: set[str] = set()
    for rel in dict.fromkeys(falam):
        for x in _por_perto(livres, rel):
            if id(x) not in vistos_ex:
                vistos_ex.add(id(x))
                fonte.append(x)
    saida: list[SceneRef] = []
    t = 0.0
    i = 0
    tentativas = 0
    for a, b, r in [*rostos, (total, total, None)]:
        while a - t >= MIN_CENA_S - 1e-6 and tentativas < len(fonte) * 2 + 10:
            tentativas += 1
            s = fonte[i % len(fonte)] if fonte else None
            i += 1
            if s is None:
                break
            fim = mt.fim_da_cena(s, t, a)
            c = mt.limpar(s, fim - t)
            if c is None:
                continue
            mt.usados.add(c.rel_path)
            saida.append(c)
            t = fim
        if a - t > 1e-6:  # sobrou um fiapo (ou faltou imagem): a cena anterior estica
            if saida:
                u = saida[-1]
                d = u.end_s - u.start_s + (a - t)
                ini = min(u.start_s, max(0.0, duracoes.get(u.rel_path, u.start_s + d) - d))
                saida[-1] = u.model_copy(update={"start_s": ini, "end_s": ini + d})
            else:
                mt.alertas.append("Faltou imagem de cobertura no começo do clipe.")
            t = a
        if r is not None:
            saida.append(r)
            t = b
    if not saida:
        return mt.alertas, []
    p.abertura = saida[0]
    p.desenvolvimento = saida[1:]
    p.gancho = None
    p.duracao_estimada_s = round(t)
    return mt.alertas, vozes
