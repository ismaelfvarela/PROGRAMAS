"""Acabamento dos clipes da Formatura, depois do roteiro do Gemini e antes da montagem:

- cada corte cai numa batida da música escolhida (padrão 1-3, 2-4 ou todas as batidas);
- cada cena é deslizada, dentro do mesmo vídeo, para a janela mais estável: sem chicote,
  escuro, desfoque ou tremido, e com a câmera parada no começo e no fim (plano que "termina o
  enquadramento");
- nada de "lembrança" (flashback) num clipe.

As medidas de imagem vêm do proxy (colacao.defeitos.medir), no computador, sem Gemini."""
from __future__ import annotations

import numpy as np

from roteiro_ia.areas.formatura.colacao.defeitos import FPS, Amostras, classificar
from roteiro_ia.models import TrackInfo
from roteiro_ia.script.generate import Piece

MIN_CENA_S = 1.0
BORDA_S = 0.5          # começo e fim do plano: a câmera precisa estar parada
BUSCA_S = 3.0          # até onde a cena pode deslizar dentro do vídeo
PESO_DISTANCIA = 0.5   # preferir ficar perto do trecho que o roteiro escolheu
PESO_RUIM = 50.0
PESO_MOVIMENTO = 0.3

def _mascara(a: Amostras, fps: float) -> np.ndarray:
    """Amostras com defeito (escuro, desfocado, chicote, tremido), calculadas uma vez por vídeo."""
    m = getattr(a, "_mascara_defeitos", None)
    if m is None:
        m = np.zeros(len(a.brilho), dtype=bool)
        for d in classificar(a, fps):
            m[max(0, int(d.inicio_s * fps)):int(np.ceil(d.fim_s * fps))] = True
        a._mascara_defeitos = m
    return m


def custo_janela(a: Amostras, fps: float, ini: float, dur: float) -> float:
    n = len(a.brilho)
    if n == 0:
        return 0.0
    i0 = min(n - 1, max(0, int(round(ini * fps))))
    i1 = min(n, max(i0 + 1, int(round((ini + dur) * fps))))
    k = max(1, int(round(BORDA_S * fps)))
    dif = a.diferenca
    ruim = float(_mascara(a, fps)[i0:i1].mean()) * PESO_RUIM
    entrada = float(dif[i0:min(i1, i0 + k)].mean())
    saida = float(dif[max(i0, i1 - k):i1].mean())
    meio = float(dif[i0:i1].mean()) * PESO_MOVIMENTO
    return ruim + entrada + saida + meio


def melhor_janela(a: Amostras, fps: float, ref_ini: float, dur: float, lim0: float,
                  lim1: float, busca_s: float = BUSCA_S) -> float:
    """Início da janela de `dur` segundos mais estável perto de `ref_ini`, dentro de [lim0, lim1]."""
    hi = lim1 - dur
    if hi <= lim0:
        return max(0.0, lim0)
    a0, a1 = max(lim0, ref_ini - busca_s), min(hi, ref_ini + busca_s)
    if a1 < a0:
        return min(max(ref_ini, lim0), hi)
    passo = 1.0 / fps
    melhor, custo_min = a0, float("inf")
    c = a0
    while c <= a1 + 1e-9:
        custo = custo_janela(a, fps, c, dur) + PESO_DISTANCIA * abs(c - ref_ini)
        if custo < custo_min:
            melhor, custo_min = c, custo
        c += passo
    return melhor


def batidas_permitidas(track: TrackInfo, inicio: float, padrao: str) -> list[float]:
    """Batidas na linha do tempo (a música começa no segundo `inicio` dela). 1-3: 1º e 3º
    tempos do compasso; 2-4: 2º e 4º; senão, todas."""
    beats = sorted(track.beats_s)
    downs = sorted(track.downbeats_s)
    escolhidas = []
    pos = -1
    j = 0
    for b in beats:
        while j < len(downs) and downs[j] <= b + 0.02:
            if abs(downs[j] - b) <= 0.02:
                pos = -1
            j += 1
        pos += 1
        if padrao in ("1-3", "2-4") and downs:
            if (padrao == "1-3") != (pos % 2 == 0):
                continue
        if b >= inicio - 1e-6:
            escolhidas.append(round(b - inicio, 4))
    return escolhidas


def acabar_peca(p: Piece, track: TrackInfo | None, inicio: float, padrao: str,
                medidas: dict[str, Amostras | None], duracoes: dict[str, float],
                rate: tuple[int, int], fps_medida: float = FPS) -> list[str]:
    """Ajusta as cenas da peça (no lugar). Devolve avisos para o editor."""
    fps_seq = rate[0] / rate[1]
    perm = batidas_permitidas(track, inicio, padrao) if track is not None else []
    cenas = [p.abertura, *p.desenvolvimento] + ([p.gancho] if p.gancho is not None else [])
    alertas: list[str] = []
    t = 0.0
    for s in cenas:
        s.lembranca = False
        a = medidas.get(s.rel_path)
        dur_midia = duracoes.get(s.rel_path)
        desejada = max(MIN_CENA_S, s.end_s - s.start_s)
        maxima = dur_midia if dur_midia else desejada * 3
        alvo = t + desejada
        cands = [b for b in perm if b >= t + MIN_CENA_S - 1e-6 and b - t <= maxima + 1e-6]
        if cands:
            perto = sorted(cands, key=lambda b: abs(b - alvo))[:3]

            def nota(b: float) -> float:
                d = b - t
                if a is None or not dur_midia:
                    return abs(b - alvo)
                ini = melhor_janela(a, fps_medida, s.start_s, d, 0.0, dur_midia)
                return abs(b - alvo) * 2 + custo_janela(a, fps_medida, ini, d)
            fim = min(perto, key=nota)
        else:
            fim = t + min(desejada, maxima)
        f0, f1 = round(t * fps_seq), round(fim * fps_seq)
        if f1 <= f0:
            f1 = f0 + 1
        dur = (f1 - f0) / fps_seq
        if a is not None and dur_midia:
            ini = melhor_janela(a, fps_medida, s.start_s, dur, 0.0, dur_midia)
            if custo_janela(a, fps_medida, ini, dur) > PESO_RUIM / 2:
                alertas.append(f"{s.rel_path}: sem trecho totalmente limpo perto de "
                               f"{s.start_s:.1f} s; confira a cena.")
        else:
            ini = s.start_s if not dur_midia else min(max(0.0, s.start_s), max(0.0, dur_midia - dur))
        s.start_s = ini
        s.end_s = ini + dur
        t = f1 / fps_seq
    return alertas
