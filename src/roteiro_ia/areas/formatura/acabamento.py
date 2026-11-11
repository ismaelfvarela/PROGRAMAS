"""Acabamento dos clipes da Formatura, depois do roteiro do Gemini e antes da montagem:

- cada corte cai no compasso da música: tempos 1 e 3 (padrão "1-3", também usado no "misto"),
  2 e 4 ("2-4") ou só o tempo 1 ("1") — nunca em qualquer batida;
- cada cena é deslizada, dentro do mesmo vídeo, para o trecho mais limpo: sem tremor de câmera
  na mão, chicote, escuro ou desfoque, e com a câmera parada no começo e no fim do plano. Se o
  vídeo inteiro está ruim, a cena é trocada pelo trecho limpo de um vídeo VIZINHO (gravado logo
  antes ou depois: mesmo assunto);
- fala do aluno: a frase inteira (pelas palavras da transcrição, sem cortar no meio). O aluno
  aparece falando no começo e no fim da fala; no meio, outras cenas cobrem a imagem e a voz
  continua por baixo (a voz vai para a lista `vozes`, montada à parte no XML);
- nada de "lembrança" (flashback) num clipe.

As medidas de imagem vêm do proxy (movimento.medir_camera), no computador, sem Gemini."""
from __future__ import annotations

from collections import deque
from typing import Callable

import numpy as np
from pydantic import BaseModel

from roteiro_ia.areas.formatura.movimento import Medidas
from roteiro_ia.models import TrackInfo, Word
from roteiro_ia.script.generate import Piece, SceneRef

MIN_CENA_S = 1.0
BORDA_S = 0.5          # começo e fim do plano: a câmera precisa estar parada
BUSCA_S = 3.0          # até onde a cena pode deslizar dentro do vídeo
BUSCA_LONGE_S = 8.0    # se perto não há trecho limpo, procura mais longe no mesmo vídeo
MAX_SEM_FALA_S = 5.0   # plano sem fala: montagem dinâmica (os modelos cortam a cada ~2 s)
MAX_COM_FALA_S = 14.0  # sem transcrição: quanto a fala pode durar
MAX_VOZ_S = 20.0       # com transcrição: a frase pode crescer até aqui para não ser cortada
PAUSA_S = 0.5          # silêncio entre palavras que separa uma frase da outra
RECUAR_S = 2.5         # a frase pode começar até aqui antes do que o roteiro marcou
AVANCAR_S = 4.0        # e terminar até aqui depois
MIN_VOZ_S = 1.0        # sobra de fala menor que isto (o resto já foi usado) sai do clipe
SEG_COBERTURA_S = 3.5  # uma cena de cobertura a cada tantos segundos de fala coberta
VOZ_ANTES_S = 0.15
VOZ_DEPOIS_S = 0.3
VOZ_COBERTA_S = 4.0    # fala a partir desta duração ganha imagens por cima no meio (B-roll)
CABECA_S = 1.5         # aluno na tela no começo da fala
RABO_S = 1.5           # e no fim
SOBREPOR_S = 0.2       # repetição de imagem tolerada entre duas cenas do mesmo vídeo
PESO_DISTANCIA = 0.3   # preferir ficar perto do trecho que o roteiro escolheu
PESO_RUIM = 50.0
PESO_TREMOR = 10.0
PESO_BORDA = 3.0
PESO_MOVIMENTO = 1.0
BRILHO_ESCURO = 28.0
NITIDEZ_DESFOCADO = 0.4
CHICOTE_PX = 6.0       # deslocamento por amostra (160 px de largura, 10 por segundo)
TREMOR_OK = 0.8
BORDA_OK = 1.5


class Voz(BaseModel):
    """Áudio de fala que corre por baixo das cenas: começa em `inicio_s` na linha do tempo e
    toca `dur_s` segundos do arquivo a partir de `in_s`."""
    inicio_s: float
    rel_path: str
    in_s: float
    dur_s: float


# ------------------------------------------------------------------ qualidade da janela

def _idx(m: Medidas, ini: float, dur: float) -> tuple[int, int, int]:
    n = len(m.brilho)
    i0 = min(n - 1, max(0, int(round(ini * m.fps))))
    i1 = min(n, max(i0 + 1, int(round((ini + dur) * m.fps))))
    k = max(1, int(round(BORDA_S * m.fps)))
    return i0, i1, k


def _partes(m: Medidas, ini: float, dur: float) -> tuple[float, float, float, float, float]:
    """(fração ruim, fração chicote, tremor médio, movimento nas bordas, movimento médio)."""
    i0, i1, k = _idx(m, ini, dur)
    med = float(np.median(m.nitidez)) if len(m.nitidez) else 1.0
    b, nt = m.brilho[i0:i1], m.nitidez[i0:i1]
    ruim = float(((b < BRILHO_ESCURO) | (nt < NITIDEZ_DESFOCADO * (med or 1.0))).mean())
    d = m.desloc[i0:i1]
    chicote = float((d > CHICOTE_PX).mean())
    trem = float(m.tremor[i0:i1].mean())
    bordas = (float(m.desloc[i0:min(i1, i0 + k)].mean())
              + float(m.desloc[max(i0, i1 - k):i1].mean())) / 2
    return ruim, chicote, trem, bordas, float(d.mean())


def custo_janela(m: Medidas, ini: float, dur: float) -> float:
    if len(m.brilho) == 0:
        return 0.0
    ruim, chicote, trem, bordas, mov = _partes(m, ini, dur)
    return ((ruim + chicote) * PESO_RUIM + PESO_TREMOR * trem + PESO_BORDA * bordas
            + PESO_MOVIMENTO * mov)


def limpa(m: Medidas, ini: float, dur: float) -> bool:
    if len(m.brilho) == 0:
        return True
    ruim, chicote, trem, bordas, _ = _partes(m, ini, dur)
    return ruim == 0 and chicote == 0 and trem <= TREMOR_OK and bordas <= BORDA_OK


def melhor_janela(m: Medidas, ref_ini: float, dur: float, lim0: float, lim1: float,
                  busca_s: float = BUSCA_S, peso_distancia: float = PESO_DISTANCIA) -> float:
    """Início da janela de `dur` segundos mais limpa perto de `ref_ini`, dentro de [lim0, lim1]."""
    hi = lim1 - dur
    if hi <= lim0:
        return max(0.0, lim0)
    a0, a1 = max(lim0, ref_ini - busca_s), min(hi, ref_ini + busca_s)
    if a1 < a0:
        return min(max(ref_ini, lim0), hi)
    passo = 1.0 / m.fps
    melhor, custo_min = a0, float("inf")
    for k in range(int((a1 - a0) / passo + 1e-6) + 1):
        c = round(a0 + k * passo, 6)
        custo = custo_janela(m, c, dur) + peso_distancia * abs(c - ref_ini)
        if custo < custo_min:
            melhor, custo_min = c, custo
    return melhor


def _janela(m: Medidas, ref: float, dur: float, dur_midia: float) -> float:
    """Melhor janela perto do trecho escolhido; se perto não há trecho limpo, olha mais longe."""
    ini = melhor_janela(m, ref, dur, 0.0, dur_midia)
    if not limpa(m, ini, dur):
        longe = melhor_janela(m, ref, dur, 0.0, dur_midia, busca_s=BUSCA_LONGE_S)
        if custo_janela(m, longe, dur) < custo_janela(m, ini, dur):
            return longe
    return ini


# ------------------------------------------------------------------ batidas

def batidas_permitidas(track: TrackInfo, inicio: float, padrao: str) -> list[float]:
    """Batidas na linha do tempo (a música começa no segundo `inicio` dela), no compasso:
    "1" = só o tempo 1; "2-4" = tempos 2 e 4; qualquer outro ("1-3", "misto") = tempos 1 e 3."""
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
        if padrao == "1":
            ok = pos % 4 == 0
        elif padrao == "2-4":
            ok = pos % 2 == 1
        else:
            ok = pos % 2 == 0
        if ok and b >= inicio - 1e-6:
            escolhidas.append(round(b - inicio, 4))
    return escolhidas


# ------------------------------------------------------------------ fala

def _fim_de_frase(w: Word) -> bool:
    return w.text.rstrip().endswith((".", "!", "?", "…"))


def trecho_da_fala(palavras: list[Word], a: float, b: float, dur_midia: float | None,
                   ja_usado: list[tuple[float, float]] = ()) -> tuple[float, float] | None:
    """Frase inteira que toca o trecho [a, b]: começa no início da frase (pontuação ou pausa,
    até RECUAR_S antes) e termina no fim dela (até AVANCAR_S depois), sem cortar palavra.
    Trechos `ja_usado` (falas já montadas do mesmo vídeo) não se repetem."""
    ws = sorted((w for w in palavras
                 if not any(u0 - 0.05 < w.start_s < u1 - 0.05 for u0, u1 in ja_usado)),
                key=lambda w: w.start_s)
    dentro = [i for i, w in enumerate(ws) if w.end_s > a and w.start_s < b]
    if not dentro:
        return None
    i, j = dentro[0], dentro[-1]
    while (i > 0 and not _fim_de_frase(ws[i - 1]) and ws[i].start_s - ws[i - 1].end_s < PAUSA_S
           and a - ws[i - 1].start_s <= RECUAR_S):
        i -= 1
    while (j + 1 < len(ws) and not _fim_de_frase(ws[j]) and ws[j + 1].start_s - ws[j].end_s < PAUSA_S
           and ws[j + 1].end_s - b <= AVANCAR_S):
        j += 1
    while ws[j].end_s - ws[i].start_s > MAX_VOZ_S and j > i:
        j -= 1
    a0 = max(0.0, ws[i].start_s - VOZ_ANTES_S)
    a1 = ws[j].end_s + VOZ_DEPOIS_S
    if dur_midia:
        a1 = min(a1, dur_midia)
    return (a0, a1) if a1 > a0 else None


# ------------------------------------------------------------------ montagem

class _Montagem:
    def __init__(self, perm: list[float], fps_seq: float, medir: Callable[[str], Medidas | None],
                 duracoes: dict[str, float], vizinhos: Callable[[str], list[str]], usados: set[str]):
        self.perm = perm
        self.fps = fps_seq
        self.medir = medir
        self.duracoes = duracoes
        self.vizinhos = vizinhos
        self.usados = usados
        self.alertas: list[str] = []
        self.trechos: dict[str, list[tuple[float, float]]] = {}  # já no clipe, por vídeo

    def q(self, x: float) -> float:
        return round(x * self.fps) / self.fps

    def batida(self, alvo: float, lo: float, hi: float) -> float:
        """Batida permitida mais perto de `alvo` dentro de [lo, hi]; sem nenhuma, o próprio alvo."""
        cands = [b for b in self.perm if lo - 1e-6 <= b <= hi + 1e-6]
        x = min(cands, key=lambda b: abs(b - alvo)) if cands else min(max(alvo, lo), hi)
        return self.q(x)

    def fim_da_cena(self, s: SceneRef, t: float, limite: float | None) -> float:
        """Onde a cena sem fala que começa em `t` termina (numa batida)."""
        m = self.medir(s.rel_path)
        dm = self.duracoes.get(s.rel_path)
        desejada = min(max(MIN_CENA_S, s.end_s - s.start_s), MAX_SEM_FALA_S)
        maxima = min(dm or desejada * 3, MAX_SEM_FALA_S + 1.0)
        hi = t + maxima if limite is None else min(t + maxima, limite)
        alvo = t + desejada
        if limite is not None and limite - t <= min(maxima, desejada + MIN_CENA_S) + 1e-6:
            return self.q(limite)  # o que sobra cabe nesta cena: vai até o limite
        cands = [b for b in self.perm if t + MIN_CENA_S - 1e-6 <= b <= hi + 1e-6
                 and (limite is None or limite - b >= MIN_CENA_S - 1e-6)]
        if not cands:
            return self.q(min(alvo, hi))
        perto = sorted(cands, key=lambda b: abs(b - alvo))[:3]

        def nota(b: float) -> float:
            d = b - t
            if m is None or not dm:
                return abs(b - alvo)
            return abs(b - alvo) * 2 + custo_janela(m, _janela(m, s.start_s, d, dm), d)
        return self.q(min(perto, key=nota))

    def usar(self, rel: str, ini: float, fim: float) -> None:
        self.trechos.setdefault(rel, []).append((ini, fim))

    def livre(self, rel: str, ini: float, dur: float) -> bool:
        """O trecho não repete imagem que já está no clipe (tolerância de SOBREPOR_S)."""
        return all(min(b, ini + dur) - max(a, ini) <= SOBREPOR_S
                   for a, b in self.trechos.get(rel, []))

    def _janela_livre(self, rel: str, m: Medidas | None, ref: float, dur: float,
                      dm: float) -> float | None:
        """Melhor trecho do vídeo que ainda não foi usado; None se não sobra nenhum."""
        ini = (_janela(m, ref, dur, dm) if m is not None
               else min(max(0.0, ref), max(0.0, dm - dur)))
        if self.livre(rel, ini, dur):
            return ini
        cands = [round(k * 0.25, 6) for k in range(int(max(0.0, dm - dur) / 0.25) + 1)]
        cands = [c for c in cands if self.livre(rel, c, dur)]
        if not cands:
            return None
        if m is None:
            return min(cands, key=lambda c: abs(c - ref))
        return min(cands, key=lambda c: custo_janela(m, c, dur) + PESO_DISTANCIA * abs(c - ref))

    def limpar(self, s: SceneRef, dur: float) -> SceneRef | None:
        """Põe a cena (sem fala) no trecho limpo e ainda não usado; se o vídeo todo é ruim, usa
        um vizinho. None quando o vídeo já foi todo usado (a cena sai, para não repetir imagem)."""
        m = self.medir(s.rel_path)
        dm = self.duracoes.get(s.rel_path)
        if not dm:
            ini = max(0.0, s.start_s)
            self.usar(s.rel_path, ini, ini + dur)
            return s.model_copy(update={"start_s": ini, "end_s": ini + dur, "lembranca": False})
        ini = self._janela_livre(s.rel_path, m, s.start_s, dur, dm)
        rel = s.rel_path
        if m is None:
            if ini is None:
                return None
        elif ini is None or not limpa(m, ini, dur):
            custo = custo_janela(m, ini, dur) if ini is not None else float("inf")
            troca = None
            for v in self.vizinhos(s.rel_path):
                if v in self.usados:
                    continue
                mv, dv = self.medir(v), self.duracoes.get(v)
                if mv is None or not dv or dv < dur:
                    continue
                iv = melhor_janela(mv, dv / 2, dur, 0.0, dv, busca_s=dv, peso_distancia=0.0)
                cv = custo_janela(mv, iv, dur)
                if limpa(mv, iv, dur) and cv < custo and (troca is None or cv < troca[2]):
                    troca = (v, iv, cv)
            if troca is not None:
                self.alertas.append(f"{s.rel_path}: imagem tremida/com movimento; troquei pelo "
                                    f"vídeo vizinho {troca[0]} ({troca[1]:.1f} s).")
                rel, ini = troca[0], troca[1]
                self.usados.add(rel)
            elif ini is None:
                return None
            else:
                self.alertas.append(f"{s.rel_path}: sem trecho totalmente limpo perto de "
                                    f"{s.start_s:.1f} s nem em vídeo vizinho; confira a cena.")
        self.usar(rel, ini, ini + dur)
        return s.model_copy(update={"rel_path": rel, "start_s": ini, "end_s": ini + dur,
                                    "lembranca": False})


def _por_perto(lista: list[SceneRef], rel: str) -> list[SceneRef]:
    """Cenas extras na ordem de gravação mais perto do vídeo `rel` (mesmo momento primeiro)."""
    nomes = sorted({x.rel_path for x in lista} | {rel})
    pos = {n: i for i, n in enumerate(nomes)}
    return sorted(lista, key=lambda x: (abs(pos[x.rel_path] - pos[rel]), x.rel_path, x.start_s))


def acabar_peca(p: Piece, track: TrackInfo | None, inicio: float, padrao: str,
                medir: Callable[[str], Medidas | None], duracoes: dict[str, float],
                rate: tuple[int, int], palavras: Callable[[str], list[Word]] = lambda _r: [],
                vizinhos: Callable[[str], list[str]] = lambda _r: [],
                extras: list[SceneRef] = ()) -> tuple[list[str], list[Voz]]:
    """Refaz as cenas da peça (no lugar). Devolve (avisos para o editor, vozes por baixo).
    `extras`: cenas sem fala do material (fora do roteiro) para cobrir falas quando as do
    roteiro não bastam."""
    fps_seq = rate[0] / rate[1]
    perm = batidas_permitidas(track, inicio, padrao) if track is not None else []
    cenas = [p.abertura, *p.desenvolvimento] + ([p.gancho] if p.gancho is not None else [])
    usados = {s.rel_path for s in cenas}
    mt = _Montagem(perm, fps_seq, medir, duracoes, vizinhos, usados)
    fila = deque(cenas)
    saida: list[SceneRef] = []
    vozes: list[Voz] = []
    falado: dict[str, list[tuple[float, float]]] = {}
    t = 0.0
    while fila:
        s = fila.popleft()
        dm = duracoes.get(s.rel_path)
        if not s.fala:
            fim = mt.fim_da_cena(s, t, None)
            if fim - t < 1 / fps_seq:
                fim = mt.q(t + MIN_CENA_S)
            c = mt.limpar(s, fim - t)
            if c is None:
                mt.alertas.append(f"{s.rel_path}: trecho já usado no clipe; cena tirada.")
                continue
            saida.append(c)
            t = fim
            continue
        # ---- fala do aluno
        ja = falado.setdefault(s.rel_path, [])
        ws = palavras(s.rel_path)
        tr = trecho_da_fala(ws, s.start_s, s.end_s, dm, ja)
        if tr is None and ws and any(u0 < s.end_s and s.start_s < u1 for u0, u1 in ja):
            mt.alertas.append(f"{s.rel_path}: fala repetida ({s.start_s:.1f} s) tirada do clipe.")
            continue
        if tr is None:
            a0 = s.start_s
            a1 = min(s.end_s, a0 + MAX_COM_FALA_S, dm or s.end_s)
        else:
            a0, a1 = tr
        for u0, u1 in ja:  # nunca volta para um pedaço do aluno que já passou na tela
            if u0 <= a0 < u1:
                a0 = u1
        if a1 - a0 < MIN_VOZ_S:
            continue
        dur_voz = a1 - a0
        vend = t + dur_voz
        teto = t + ((dm - a0) if dm else dur_voz + 1.5)  # o vídeo do aluno acaba aqui
        c3 = mt.batida(vend, vend - 0.05, min(vend + 1.5, teto))
        c3 = max(c3, mt.q(t + MIN_CENA_S))
        cobre: list[SceneRef] = []
        if dur_voz >= VOZ_COBERTA_S:
            c1 = mt.batida(t + CABECA_S, t + 1.0, t + 2.5)
            c2 = mt.batida(c3 - RABO_S, c3 - 2.5, c3 - 1.0)
            if c2 - c1 >= MIN_CENA_S - 1e-6:
                # sobram candidatas: uma cena curta ou repetida não deixa o aluno na tela
                precisa = max(1, int(np.ceil((c2 - c1) / SEG_COBERTURA_S))) + 2
                # 1º as cenas sem fala que o roteiro pôs logo depois desta fala (a cobertura dela)
                for x in fila:
                    if x.fala or len(cobre) >= precisa:
                        break
                    cobre.append(x)
                # 2º imagens do material gravadas perto do aluno (fora do roteiro)
                livres = [x for x in extras if x.rel_path not in mt.usados]
                for x in _por_perto(livres, s.rel_path):
                    if len(cobre) >= precisa:
                        break
                    if x.rel_path not in {c.rel_path for c in cobre}:
                        cobre.append(x)
                # 3º, se ainda falta, outras cenas sem fala do roteiro (deixa 2 por fala seguinte)
                sem_fala = [x for x in fila if not x.fala and x not in cobre]
                reserva = 2 * sum(1 for x in fila if x.fala)
                for x in sem_fala[:max(0, len(sem_fala) - reserva)]:
                    if len(cobre) >= precisa:
                        break
                    cobre.append(x)
        if cobre:
            saida.append(s.model_copy(update={"start_s": a0, "end_s": a0 + (c1 - t),
                                              "lembranca": False}))
            x = c1
            for prox in cobre:
                if c2 - x < MIN_CENA_S - 1e-6:
                    break
                if prox in fila:
                    fila.remove(prox)
                elif prox.rel_path in mt.usados:
                    continue  # extra que virou troca de outra cena: não repete o vídeo
                mt.usados.add(prox.rel_path)
                fim = mt.fim_da_cena(prox, x, c2)
                c = mt.limpar(prox, fim - x)
                if c is None:
                    continue
                saida.append(c)
                x = fim
            saida.append(s.model_copy(update={"start_s": a0 + (x - t), "end_s": a0 + (c3 - t),
                                              "lembranca": False}))
        else:
            saida.append(s.model_copy(update={"start_s": a0, "end_s": a0 + (c3 - t),
                                              "lembranca": False}))
        vozes.append(Voz(inicio_s=t, rel_path=s.rel_path, in_s=a0, dur_s=dur_voz))
        ja.append((a0, max(a1, a0 + (c3 - t))))  # fala e imagem do aluno já usadas
        mt.usar(s.rel_path, a0, max(a1, a0 + (c3 - t)))  # o B-roll não mostra este pedaço
        t = c3
    p.abertura = saida[0]
    if p.gancho is not None and len(saida) > 1:
        p.desenvolvimento, p.gancho = saida[1:-1], saida[-1]
    else:
        p.desenvolvimento = saida[1:]
    return mt.alertas, vozes
