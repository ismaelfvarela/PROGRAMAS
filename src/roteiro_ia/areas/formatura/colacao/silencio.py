"""Espaços mortos (silêncio longo) no áudio da mesa de corte, pelo silencedetect do ffmpeg."""
from __future__ import annotations

import re
from pathlib import Path

from roteiro_ia import proc
from roteiro_ia.media.tools import ffmpeg_bin

MIN_S = 4.0


def silencios(audio: Path, limite_db: float, min_s: float = MIN_S) -> list[tuple[float, float]]:
    cmd = [ffmpeg_bin(), "-v", "info", "-nostdin", "-i", str(audio), "-vn",
           "-af", f"silencedetect=n={limite_db:.1f}dB:d={min_s}", "-f", "null", "-"]
    r = proc.run(cmd, timeout=3600)
    txt = r.stderr.decode("utf-8", "replace")
    out: list[tuple[float, float]] = []
    ini = None
    for linha in txt.splitlines():
        if m := re.search(r"silence_start:\s*(-?[\d.]+)", linha):
            ini = max(0.0, float(m[1]))
        elif (m := re.search(r"silence_end:\s*([\d.]+)", linha)) and ini is not None:
            out.append((ini, float(m[1])))
            ini = None
    if ini is not None:  # silêncio até o fim do arquivo
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
        if m:
            out.append((ini, int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])))
    return out
