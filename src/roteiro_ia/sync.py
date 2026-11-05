"""Sincronização: coloca cada mídia numa linha do tempo real por dia do evento.

A posição (``timeline_start_s``) vem da correlação de áudio (GCC-PHAT) contra uma
referência já sincronizada; sem áudio confiável usa a data/hora de criação.
O áudio dos vídeos é lido dos proxies locais (mesmo tempo, mesmo áudio) quando existem;
os originais só são lidos para mídias só-de-áudio ou vídeos ainda sem proxy.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.fft import irfft, next_fast_len, rfft

from roteiro_ia.db import ProjectDB
from roteiro_ia.media.audio import load_mono
from roteiro_ia.models import MediaInfo, Role, SyncResult

SR = 8000
WINDOW_S = 60.0          # trecho do meio da mídia que é correlacionado
SEARCH_S = 300.0         # busca na referência: estimativa ± SEARCH_S
SCAN_S = 600.0           # janela da varredura quando não há estimativa (≤ ~11 min)
MAX_CANDIDATES = 3       # referências tentadas por estimativa
HOUR_SHIFTS = [k * 3600.0 for k in (-3, -2, -1, 1, 2, 3)]
REFERENCE_CONFIDENCE = 1000.0   # confiança gravada para a referência raiz do dia
CACHE_ITEMS = 16                # trechos de áudio guardados por execução (≈ 20 MB cada no máximo)
_EXCL_S = 0.1
_PRIORITY = {
    Role.mesa: 0, Role.audio_ambiente: 1, Role.lapela_noivo: 2, Role.lapela_noiva: 2,
    Role.camera: 3, Role.pocket: 3, Role.outro_dia: 3,
}


def xcorr_offset(ref: np.ndarray, other: np.ndarray, sr: int) -> tuple[float, float]:
    """GCC-PHAT. Retorna (posição do início de ``other`` dentro de ``ref`` em s, confiança).

    Offset positivo = ``other`` começa depois do início de ``ref``. Confiança = pico
    principal / maior pico fora de ±0.1 s dele (0 para entradas vazias ou silenciosas).
    """
    a = np.asarray(ref, dtype=np.float64).ravel()
    b = np.asarray(other, dtype=np.float64).ravel()
    if a.size == 0 or b.size == 0:
        return 0.0, 0.0
    a = a - a.mean()
    b = b - b.mean()
    if np.max(np.abs(a)) < 1e-9 or np.max(np.abs(b)) < 1e-9:
        return 0.0, 0.0
    n = next_fast_len(a.size + b.size - 1)
    spec = rfft(a, n) * np.conj(rfft(b, n))
    mag = np.abs(spec)
    spec /= mag + 1e-3 * mag.mean() + 1e-20
    cc = irfft(spec, n)
    # lags -(len(b)-1) .. len(a)-1
    c = np.abs(np.concatenate([cc[n - (b.size - 1):], cc[: a.size]])) if b.size > 1 \
        else np.abs(cc[: a.size])
    i = int(np.argmax(c))
    peak = float(c[i])
    offset = (i - (b.size - 1)) / sr
    if peak <= 0:
        return offset, 0.0
    excl = max(1, int(_EXCL_S * sr))
    outside = np.concatenate([c[: max(0, i - excl)], c[i + excl + 1:]])
    second = float(outside.max()) if outside.size else 0.0
    conf = peak / second if second > 0 else REFERENCE_CONFIDENCE
    return float(offset), float(min(conf, REFERENCE_CONFIDENCE))


def _has_audio(m: MediaInfo) -> bool:
    return m.audio_channels > 0 and m.role != Role.drone


def _diff_s(a: datetime, b: datetime) -> float:
    if (a.tzinfo is None) != (b.tzinfo is None):
        a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
    return (a - b).total_seconds()


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


class _Day:
    def __init__(self, db: ProjectDB, source_root: Path, medias: list[MediaInfo],
                 min_conf: float, window_s: float, search_s: float):
        self.db, self.root_dir = db, Path(source_root)
        self.min_conf, self.window_s, self.search_s = min_conf, window_s, search_s
        self.order = sorted(medias, key=lambda m: (
            _PRIORITY.get(m.role, 4) if _has_audio(m) else 5, -m.duration_s, m.rel_path))
        self.by_id = {m.id: m for m in medias}
        self.pos: dict[int, SyncResult] = {}
        self._cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        for m in medias:
            r = db.get_sync(m.id)
            if r is not None:
                self.pos[m.id] = r

    # --- estimativas pela hora de criação
    def _anchor(self) -> MediaInfo | None:
        if self.root.created_at is not None:
            return self.root
        for mid in self.pos:
            m = self.by_id[mid]
            if m.created_at is not None:
                return m
        return None

    def estimate(self, m: MediaInfo) -> float | None:
        a = self._anchor()
        if m.created_at is None or a is None:
            return None
        return self.pos[a.id].timeline_start_s + _diff_s(m.created_at, a.created_at)

    # --- correlação
    def _path(self, m: MediaInfo) -> Path:
        if m.kind == "video":
            prx = self.db.proxy_for(m.id)
            if prx and Path(prx).is_file():
                return Path(prx)  # proxy local: leitura rápida, sem tocar no NAS
        return self.root_dir / m.rel_path

    def _load(self, m: MediaInfo, start_s: float, dur_s: float) -> np.ndarray:
        key = (m.id, round(start_s, 3), round(dur_s, 3))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        x = load_mono(self._path(m), sr=SR, start_s=start_s, dur_s=dur_s)
        self._cache[key] = x
        while len(self._cache) > CACHE_ITEMS:
            self._cache.popitem(last=False)
        return x

    def _excerpt(self, m: MediaInfo) -> tuple[np.ndarray, float]:
        length = min(self.window_s, m.duration_s) if m.duration_s > 0 else self.window_s
        off = max(0.0, (m.duration_s - length) / 2)
        return self._load(m, off, length), off

    def _against(self, ref: MediaInfo, ws: float, we: float, ex: np.ndarray,
                 off_m: float) -> tuple[float, float]:
        refx = self._load(ref, ws, we - ws)
        off, conf = xcorr_offset(refx, ex, SR)
        return self.pos[ref.id].timeline_start_s + ws + off - off_m, conf

    def _try_at(self, m: MediaInfo, est: float, ex: np.ndarray,
                off_m: float) -> tuple[float | None, float]:
        cands = []
        for mid, r in self.pos.items():
            c = self.by_id[mid]
            if not _has_audio(c):
                continue
            c0, c1 = r.timeline_start_s, r.timeline_start_s + c.duration_s
            real = _overlap(est, est + m.duration_s, c0, c1)
            margin = _overlap(est - self.search_s, est + m.duration_s + self.search_s, c0, c1)
            if margin > 0:
                # referência sincronizada pelo áudio e só-de-áudio (mesa/ambiente) primeiro
                pref = (0 if r.method == "audio" else 1) + (0 if c.kind == "audio" else 2)
                cands.append((pref, real, margin, c))
        cands.sort(key=lambda t: (t[0], -t[1], -t[2], t[3].rel_path))
        best: tuple[float | None, float] = (None, 0.0)
        for _, _, _, c in cands[:MAX_CANDIDATES]:
            p = est + off_m - self.pos[c.id].timeline_start_s
            ws = max(0.0, p - self.search_s)
            we = min(c.duration_s, p + ex.size / SR + self.search_s)
            if we - ws < 1.0:
                continue
            tl, conf = self._against(c, ws, we, ex, off_m)
            if conf > best[1]:
                best = (tl, conf)
            if conf >= self.min_conf:
                break
        return best

    def _scan_root(self, ex: np.ndarray, off_m: float) -> tuple[float | None, float]:
        if not _has_audio(self.root) or self.root.duration_s <= 0:
            return None, 0.0
        best: tuple[float | None, float] = (None, 0.0)
        step = SCAN_S - self.window_s
        ws = 0.0
        while ws < self.root.duration_s:
            we = min(self.root.duration_s, ws + SCAN_S)
            tl, conf = self._against(self.root, ws, we, ex, off_m)
            if conf > best[1]:
                best = (tl, conf)
            if conf >= self.min_conf:
                break
            ws += step
        return best

    def correlate(self, m: MediaInfo, est: float | None) -> tuple[float | None, float]:
        """(timeline_start_s ou None se nenhuma correlação confiável, melhor confiança)."""
        ex, off_m = self._excerpt(m)
        if ex.size == 0:
            return None, 0.0
        if est is None:
            tl, conf = self._scan_root(ex, off_m)
            return (tl if conf >= self.min_conf else None), conf
        tl, conf = self._try_at(m, est, ex, off_m)
        if conf >= self.min_conf:
            return tl, conf
        best_tl, best_conf = None, conf
        for shift in HOUR_SHIFTS:  # guarda contra fuso horário errado na câmera
            t, c = self._try_at(m, est + shift, ex, off_m)
            if c >= self.min_conf and (best_tl is None or c > best_conf):
                best_tl, best_conf = t, c
            elif best_tl is None:
                best_conf = max(best_conf, c)
        return best_tl, best_conf

    # --- fluxo do dia
    def run(self, day: str) -> None:
        synced_audio = [m for m in self.order if m.id in self.pos and _has_audio(m)]
        synced = [m for m in self.order if m.id in self.pos]
        self.root = (synced_audio or synced or self.order)[0]
        if self.root.id not in self.pos:
            self.pos[self.root.id] = SyncResult(
                media_id=self.root.id, day_label=day, timeline_start_s=0.0,
                confidence=REFERENCE_CONFIDENCE if _has_audio(self.root) else 0.0,
                method="audio" if _has_audio(self.root) else "hora")
            new = {self.root.id}
            self.db.set_sync(self.pos[self.root.id])
        else:
            new = set()
        sequential: list[MediaInfo] = []
        for m in self.order:
            if m.id in self.pos:
                continue
            est = self.estimate(m)
            tl, conf = None, 0.0
            if _has_audio(m):
                try:
                    tl, conf = self.correlate(m, est)
                except Exception as e:  # noqa: BLE001 - um arquivo ruim não derruba o dia
                    self.db.add_falha("sync", m.rel_path,
                                      f"Falha ao sincronizar pelo áudio: {e}")
            if tl is not None:
                r = SyncResult(media_id=m.id, day_label=day, timeline_start_s=tl,
                               confidence=conf, method="audio")
            elif est is not None:
                r = SyncResult(media_id=m.id, day_label=day, timeline_start_s=est,
                               confidence=conf, method="hora")
            else:
                sequential.append(m)
                continue
            self.pos[m.id] = r
            new.add(m.id)
            self.db.set_sync(r)  # gravado na hora: uma queda no meio do dia não perde o feito

        shift = -min(r.timeline_start_s for r in self.pos.values())
        for mid, r in self.pos.items():
            if shift != 0:  # normalização do dia: o deslocamento vale para todos
                self.db.set_sync(r.model_copy(
                    update={"timeline_start_s": r.timeline_start_s + shift}))

        for m in sequential:
            prev = sum(o.duration_s for o in self.order
                       if o.folder == m.folder and o.rel_path < m.rel_path)
            self.db.set_sync(SyncResult(media_id=m.id, day_label=day, timeline_start_s=prev,
                                        confidence=0.0, method="hora"))
            self.db.add_falha(
                "sync", m.rel_path,
                "Sem data/hora de criação e sem correlação de áudio: posicionado em "
                "sequência na pasta. Confira a posição na linha do tempo.")


def sync_event(db: ProjectDB, source_root: Path, min_confidence: float = 3.0,
               window_s: float = WINDOW_S, search_s: float = SEARCH_S) -> None:
    """Sincroniza todas as mídias do evento, um dia (``day_label``) por vez."""
    days: dict[str, list[MediaInfo]] = {}
    for m in db.list_media():
        if m.id is None or m.role == Role.ignorar:
            continue
        days.setdefault(m.day_label, []).append(m)
    for day, medias in days.items():
        if all(db.get_sync(m.id) is not None for m in medias):
            continue
        _Day(db, source_root, medias, min_confidence, window_s, search_s).run(day)
