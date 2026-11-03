"""Segmentos de cena: divide clipes longos em trechos de até 60 s."""
from __future__ import annotations

import math

from roteiro_ia.db import ProjectDB
from roteiro_ia.models import Segment
from roteiro_ia.paths import EventPaths


def split_long(cuts: list[tuple[float, float]], max_s: float = 60.0,
               min_s: float = 2.0) -> list[tuple[float, float]]:
    """Junta trechos < min_s ao anterior (o primeiro, ao seguinte) e corta > max_s em partes iguais."""
    merged: list[list[float]] = []
    carry_start: float | None = None
    for a, b in sorted(cuts):
        if carry_start is not None:
            a = carry_start
            carry_start = None
        if b - a < min_s:
            if merged:
                merged[-1][1] = b
            else:
                carry_start = a
            continue
        merged.append([a, b])
    if carry_start is not None and cuts:  # tudo curto: um único trecho
        merged.append([carry_start, max(b for _, b in cuts)])
    out: list[tuple[float, float]] = []
    for a, b in merged:
        n = max(1, math.ceil((b - a) / max_s - 1e-9))
        step = (b - a) / n
        for i in range(n):
            out.append((a + i * step, b if i == n - 1 else a + (i + 1) * step))
    return out


def _audio_chunks(duration: float, chunk: float = 60.0, min_s: float = 2.0):
    cuts, t = [], 0.0
    while t < duration:
        cuts.append((t, min(t + chunk, duration)))
        t += chunk
    return cuts or [(0.0, duration)]


def _video_cuts(proxy: str, duration: float) -> list[tuple[float, float]]:
    from scenedetect import ContentDetector, detect

    scenes = detect(proxy, ContentDetector())
    if not scenes:
        return [(0.0, duration)]
    cuts = []
    for a, b in scenes:
        s, e = max(0.0, a.seconds), min(duration, b.seconds)
        if e > s:
            cuts.append((s, e))
    if not cuts:
        return [(0.0, duration)]
    # cobre todo o intervalo [0, duration]
    cuts[0] = (0.0, cuts[0][1])
    cuts[-1] = (cuts[-1][0], duration)
    return cuts


def detect_segments(db: ProjectDB, p: EventPaths | None = None) -> None:
    """Grava segmentos de cena de cada mídia (vídeo: ContentDetector no proxy)."""
    for m in db.list_media():
        if db.list_segments(m.id):
            continue
        try:
            if m.kind == "audio":
                cuts = _audio_chunks(m.duration_s)
            else:
                proxy = db.proxy_for(m.id)
                if not proxy:
                    db.add_falha("cenas", m.rel_path, "sem proxy")
                    continue
                cuts = _video_cuts(proxy, m.duration_s)
            segs = split_long(cuts)
            db.add_segments([Segment(media_id=m.id, start_s=a, end_s=b) for a, b in segs])
        except Exception as e:  # noqa: BLE001 - continua nos demais arquivos
            db.add_falha("cenas", m.rel_path, f"erro na detecção de cenas: {e}")
