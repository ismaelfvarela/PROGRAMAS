"""Defeitos de imagem da gravação da mesa de corte, medidos no computador (sem Gemini).

O vídeo é lido em fluxo, poucos quadros por segundo, em cinza e pequeno; cada amostra dá
brilho, nitidez e diferença para a amostra anterior. A classificação é feita só com números."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel

from roteiro_ia import controle
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.proc import _sem_console

FPS = 4.0
LARGURA, ALTURA = 96, 54
BRILHO_ESCURO = 28.0
NITIDEZ_DESFOCADO = 0.4   # fração da mediana do arquivo
NITIDEZ_TREMIDO = 0.7
DIF_CHICOTE = 30.0
DIF_TREMIDO = 12.0
JANELA_TREMIDO_S = 2.0
MIN_S = 1.0               # escuro, desfocado e tremido precisam durar pelo menos isto
FOLGA_S = 0.25
JUNTAR_S = 0.5

Tipo = Literal["escuro", "desfocado", "chicote", "tremido"]


class Defeito(BaseModel):
    inicio_s: float
    fim_s: float
    tipo: Tipo


@dataclass
class Amostras:
    brilho: np.ndarray
    nitidez: np.ndarray
    diferenca: np.ndarray


def _corridas(mask: np.ndarray) -> list[tuple[int, int]]:
    """Trechos [início, fim) em que a máscara é verdadeira."""
    out, ini = [], None
    for i, v in enumerate(mask):
        if v and ini is None:
            ini = i
        elif not v and ini is not None:
            out.append((ini, i))
            ini = None
    if ini is not None:
        out.append((ini, len(mask)))
    return out


def _intervalos(mask: np.ndarray, fps: float, min_amostras: int, tipo: Tipo) -> list[Defeito]:
    return [Defeito(inicio_s=max(0.0, a / fps - FOLGA_S), fim_s=b / fps + FOLGA_S, tipo=tipo)
            for a, b in _corridas(mask) if b - a >= min_amostras]


def _juntar(ds: list[Defeito]) -> list[Defeito]:
    out: list[Defeito] = []
    for d in sorted(ds, key=lambda d: (d.tipo, d.inicio_s)):
        if out and out[-1].tipo == d.tipo and d.inicio_s - out[-1].fim_s < JUNTAR_S:
            out[-1] = out[-1].model_copy(update={"fim_s": max(out[-1].fim_s, d.fim_s)})
        else:
            out.append(d)
    return sorted(out, key=lambda d: d.inicio_s)


def classificar(a: Amostras, fps: float = FPS) -> list[Defeito]:
    n = len(a.brilho)
    if n == 0:
        return []
    min_n = max(1, int(round(MIN_S * fps)))
    mediana = float(np.median(a.nitidez)) or 1.0
    escuro = a.brilho < BRILHO_ESCURO
    desfocado = (a.nitidez < NITIDEZ_DESFOCADO * mediana) & ~escuro
    alto = a.diferenca > DIF_CHICOTE
    chicote = np.zeros(n, dtype=bool)
    for i, j in _corridas(alto):
        if j - i >= 2:  # uma amostra só é corte de câmera
            chicote[i:j] = True
    janela = max(1, int(round(JANELA_TREMIDO_S * fps)))
    media = np.convolve(a.diferenca, np.ones(janela) / janela, mode="same")
    tremido = ((media > DIF_TREMIDO) & (a.nitidez < NITIDEZ_TREMIDO * mediana)
               & ~chicote & ~escuro & ~desfocado)
    ds = (_intervalos(escuro, fps, min_n, "escuro") + _intervalos(desfocado, fps, min_n, "desfocado")
          + _intervalos(chicote, fps, 2, "chicote") + _intervalos(tremido, fps, min_n, "tremido"))
    return _juntar(ds)


def medir(video: Path, fps: float = FPS) -> Amostras:
    """Lê o vídeo pelo ffmpeg em fluxo (nada fica inteiro na memória)."""
    cmd = [ffmpeg_bin(), "-v", "error", "-nostdin", "-i", str(video), "-an",
           "-vf", f"fps={fps},scale={LARGURA}:{ALTURA},format=gray", "-f", "rawvideo", "-"]
    tam = LARGURA * ALTURA
    brilho, nitidez, dif = [], [], []
    ant = None
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_sem_console())
    try:
        k = 0
        while True:
            buf = p.stdout.read(tam)
            if len(buf) < tam:
                break
            f = np.frombuffer(buf, dtype=np.uint8).reshape(ALTURA, LARGURA).astype(np.float32)
            brilho.append(float(f.mean()))
            nitidez.append(float(np.abs(np.diff(f, axis=1)).mean() + np.abs(np.diff(f, axis=0)).mean()))
            dif.append(0.0 if ant is None else float(np.abs(f - ant).mean()))
            ant = f
            k += 1
            if k % 400 == 0:
                controle.atual().checkpoint()
        p.wait(timeout=60)
    finally:
        if p.poll() is None:
            p.kill()
    if p.returncode not in (0, None) and not brilho:
        erro = p.stderr.read().decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"O ffmpeg não conseguiu ler '{Path(video).name}': "
                           f"{erro[-1] if erro else 'erro desconhecido'}")
    return Amostras(np.array(brilho), np.array(nitidez), np.array(dif))
