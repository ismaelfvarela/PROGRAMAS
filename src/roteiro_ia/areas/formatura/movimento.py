"""Movimento da câmera nos vídeos dos clipes, medido no computador (sem Gemini).

O proxy é lido em fluxo, a FPS quadros por segundo, pequeno e em cinza. Para cada amostra:
- brilho e nitidez (como na colação);
- deslocamento da imagem INTEIRA em relação à amostra anterior (correlação de fase): é o
  movimento da câmera, e não o de quem está na cena (a mão costurando não move o quadro todo);
- tremor: quanto o caminho da câmera foge do caminho suavizado — a câmera na mão tremendo.
  Uma panorâmica lisa tem deslocamento constante e tremor perto de zero."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from roteiro_ia import controle
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.proc import _sem_console

FPS = 10.0
LARGURA, ALTURA = 160, 90
SUAVIZAR_S = 0.7      # janela do caminho "liso" da câmera
VERSAO = 2            # muda quando a medida muda (o cache antigo é refeito)


@dataclass
class Medidas:
    fps: float
    brilho: np.ndarray
    nitidez: np.ndarray
    desloc: np.ndarray   # pixels (na largura LARGURA) por amostra
    tremor: np.ndarray   # pixels fora do caminho suavizado

    def para_dict(self) -> dict:
        r = lambda a: [round(float(x), 2) for x in a]  # noqa: E731
        return {"versao": VERSAO, "fps": self.fps, "brilho": r(self.brilho),
                "nitidez": r(self.nitidez), "desloc": r(self.desloc), "tremor": r(self.tremor)}

    @staticmethod
    def de_dict(d: dict) -> "Medidas | None":
        if not isinstance(d, dict) or d.get("versao") != VERSAO:
            return None
        return Medidas(float(d["fps"]), np.array(d["brilho"], float), np.array(d["nitidez"], float),
                       np.array(d["desloc"], float), np.array(d["tremor"], float))


def _subpixel(r: np.ndarray, i: int, j: int) -> tuple[float, float]:
    """Pico da correlação refinado por parábola (meio pixel faz diferença no tremor)."""
    h, w = r.shape

    def par(a: float, b: float, c: float) -> float:
        den = a - 2 * b + c
        return 0.0 if abs(den) < 1e-9 else 0.5 * (a - c) / den
    dy = par(r[(i - 1) % h, j], r[i, j], r[(i + 1) % h, j])
    dx = par(r[i, (j - 1) % w], r[i, j], r[i, (j + 1) % w])
    y = (i if i <= h // 2 else i - h) + dy
    x = (j if j <= w // 2 else j - w) + dx
    return x, y


def deslocamentos(quadros: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """(dx, dy) de cada quadro em relação ao anterior (o primeiro é 0)."""
    if not quadros:
        return np.zeros(0), np.zeros(0)
    h, w = quadros[0].shape
    jan = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    dx, dy, ant = [], [], None
    for f in quadros:
        F = np.fft.fft2((f - f.mean()) * jan)
        if ant is None:
            dx.append(0.0)
            dy.append(0.0)
        else:
            R = F * np.conj(ant)
            R /= np.abs(R) + 1e-6
            r = np.fft.ifft2(R).real
            i, j = np.unravel_index(int(np.argmax(r)), r.shape)
            x, y = _subpixel(r, int(i), int(j))
            dx.append(x)  # quanto o conteúdo andou do quadro anterior para este
            dy.append(y)
        ant = F
    return np.array(dx), np.array(dy)


def tremor(dx: np.ndarray, dy: np.ndarray, fps: float) -> np.ndarray:
    if len(dx) == 0:
        return np.zeros(0)
    cx, cy = np.cumsum(dx), np.cumsum(dy)
    k = max(3, int(round(SUAVIZAR_S * fps)) | 1)
    pad = k // 2
    nucleo = np.ones(k) / k
    sx = np.convolve(np.pad(cx, pad, mode="edge"), nucleo, mode="valid")
    sy = np.convolve(np.pad(cy, pad, mode="edge"), nucleo, mode="valid")
    return np.hypot(cx - sx, cy - sy)


def de_quadros(quadros: list[np.ndarray], fps: float = FPS) -> Medidas:
    brilho = np.array([float(f.mean()) for f in quadros])
    nitidez = np.array([float(np.abs(np.diff(f, axis=1)).mean() + np.abs(np.diff(f, axis=0)).mean())
                        for f in quadros])
    dx, dy = deslocamentos(quadros)
    return Medidas(fps, brilho, nitidez, np.hypot(dx, dy), tremor(dx, dy, fps))


def medir_camera(video: Path, fps: float = FPS) -> Medidas:
    cmd = [ffmpeg_bin(), "-v", "error", "-nostdin", "-i", str(video), "-an",
           "-vf", f"fps={fps},scale={LARGURA}:{ALTURA},format=gray", "-f", "rawvideo", "-"]
    tam = LARGURA * ALTURA
    quadros: list[np.ndarray] = []
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_sem_console())
    try:
        while True:
            buf = p.stdout.read(tam)
            if len(buf) < tam:
                break
            quadros.append(np.frombuffer(buf, dtype=np.uint8).reshape(ALTURA, LARGURA)
                           .astype(np.float32))
            if len(quadros) % 400 == 0:
                controle.atual().checkpoint()
        p.wait(timeout=60)
    finally:
        if p.poll() is None:
            p.kill()
    if p.returncode not in (0, None) and not quadros:
        erro = p.stderr.read().decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"O ffmpeg não conseguiu ler '{Path(video).name}': "
                           f"{erro[-1] if erro else 'erro desconhecido'}")
    return de_quadros(quadros, fps)
