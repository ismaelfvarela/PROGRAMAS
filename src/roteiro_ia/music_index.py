"""Índice incremental das trilhas da biblioteca (BPM, tempos 1-4, energia, perfil)."""
from __future__ import annotations

import bisect
import logging
import math
import os
import sqlite3
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from .config import Settings
from .models import TrackInfo
from .safety import assert_writable, safe_mkdir

log = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".wav", ".m4a"}
INTENSE_BPM = 110.0
# Energia (RMS médio, amostras em [-1, 1]) a partir da qual a trilha é considerada intensa.
INTENSE_RMS = 0.15
CRESCENDO_RATIO = 1.3
# Heurística grosseira de voz: fração da energia harmônica (HPSS) entre 300 e 3400 Hz.
# Instrumentos melódicos também caem nessa faixa; serve só como sugestão, não como verdade.
VOCAL_RATIO = 0.55
VOCAL_BAND_HZ = (300.0, 3400.0)
_SR = 22050
_HOP = 128  # resolução fina (~6 ms) para o BPM não oscilar entre quadros


class BeatTracker(Protocol):
    def track(self, path: Path) -> tuple[list[float], list[float]]:
        """Retorna (beats_s, downbeats_s)."""


class BeatThisTracker:
    """beat_this (GPU se possível, senão CPU). O modelo só é carregado no primeiro uso."""

    def __init__(self, device: str = "cuda"):
        self.device = device
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        from beat_this.inference import File2Beats

        try:
            self._model = File2Beats(checkpoint_path="final0", device=self.device, dbn=False)
        except Exception as e:
            if self.device == "cpu":
                raise
            log.warning("Não foi possível usar a GPU para os tempos das trilhas (%s); usando CPU.", e)
            self.device = "cpu"
            self._model = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
        return self._model

    def track(self, path: Path) -> tuple[list[float], list[float]]:
        beats, downbeats = self._load()(str(path))
        return [float(b) for b in beats], [float(d) for d in downbeats]


class LibrosaTracker:
    """Alternativa sem modelo: beats do librosa; tempo 1 = fase de 4 em 4 com mais ataque."""

    def track(self, path: Path) -> tuple[list[float], list[float]]:
        return self.track_signal(_load_audio(path))

    def track_signal(self, y: np.ndarray) -> tuple[list[float], list[float]]:
        import librosa

        env = librosa.onset.onset_strength(y=y, sr=_SR, hop_length=_HOP)
        _, frames = librosa.beat.beat_track(onset_envelope=env, sr=_SR, hop_length=_HOP,
                                            tightness=300)
        frames = np.asarray(frames, dtype=int)
        if len(frames) == 0:
            return [], []
        beats = librosa.frames_to_time(frames, sr=_SR, hop_length=_HOP)
        strength = env[np.clip(frames, 0, len(env) - 1)]
        best = max(range(min(4, len(beats))),
                   key=lambda ph: float(np.mean(strength[ph::4])))
        return [float(b) for b in beats], [float(b) for b in beats[best::4]]


def _load_audio(path: Path) -> np.ndarray:
    import librosa

    try:
        y, _ = librosa.load(str(path), sr=_SR, mono=True)
        return y
    except Exception:
        from .media.audio import load_mono

        return load_mono(Path(path), sr=_SR)


def _default_tracker() -> BeatTracker:
    t = BeatThisTracker()
    try:
        t._load()
    except Exception as e:
        log.warning("Não foi possível carregar o modelo de tempos (beat_this): %s. "
                    "Usando o método alternativo (librosa), menos preciso.", e)
        return LibrosaTracker()
    return t


def _bpm(beats: list[float]) -> float:
    if len(beats) < 2:
        return 0.0
    return float(60.0 / np.median(np.diff(beats)))


def _energy_per_second(y: np.ndarray) -> list[float]:
    n = math.ceil(len(y) / _SR)
    out = []
    for i in range(n):
        seg = y[i * _SR:(i + 1) * _SR]
        out.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    return out


def _perfil(bpm: float, energy: list[float]) -> str:
    if len(energy) >= 3:
        k = len(energy) // 3
        first, last = float(np.mean(energy[:k])), float(np.mean(energy[-k:]))
        if first > 0 and last > CRESCENDO_RATIO * first:
            return "crescente"
    mean = float(np.mean(energy)) if energy else 0.0
    if bpm >= INTENSE_BPM or mean >= INTENSE_RMS:
        return "intensa"
    return "calma"


def _has_vocals(y: np.ndarray) -> bool:
    import librosa

    if len(y) < 2048:
        return False
    harm = librosa.effects.harmonic(y)
    spec = np.abs(librosa.stft(harm, n_fft=2048)) ** 2
    freqs = librosa.fft_frequencies(sr=_SR, n_fft=2048)
    total = float(spec.sum())
    if total <= 0:
        return False
    band = (freqs >= VOCAL_BAND_HZ[0]) & (freqs <= VOCAL_BAND_HZ[1])
    return float(spec[band].sum()) / total >= VOCAL_RATIO


def analyze_track(path: Path, tracker: BeatTracker | None = None) -> TrackInfo:
    path = Path(path)
    if tracker is None:
        tracker = _default_tracker()
    y = _load_audio(path)
    if isinstance(tracker, LibrosaTracker):
        beats, downbeats = tracker.track_signal(y)
    else:
        beats, downbeats = tracker.track(path)
    bpm = _bpm(beats)
    energy = _energy_per_second(y)
    return TrackInfo(
        path=str(path.resolve()), bpm=bpm, beats_s=beats, downbeats_s=downbeats,
        energy=energy, duration_s=len(y) / _SR, has_vocals=_has_vocals(y),
        perfil=_perfil(bpm, energy), mtime=path.stat().st_mtime,
    )


def beat_positions(t: TrackInfo) -> list[tuple[float, int]]:
    """(tempo_s, nº 1-4) de cada beat, contando a partir do último tempo 1 (downbeat).

    Beats antes do primeiro downbeat são numerados para trás, mantendo o ciclo.
    """
    beats = t.beats_s
    if not beats:
        return []
    downs = sorted(t.downbeats_s)
    if not downs:
        return [(b, i % 4 + 1) for i, b in enumerate(beats)]
    d_idx = sorted({min(range(len(beats)), key=lambda i: abs(beats[i] - d)) for d in downs})
    out: list[tuple[float, int]] = []
    for i, b in enumerate(beats):
        if i < d_idx[0]:
            out.append((b, (i - d_idx[0]) % 4 + 1))
        else:
            last = d_idx[bisect.bisect_right(d_idx, i) - 1]
            out.append((b, (i - last) % 4 + 1))
    return out


class MusicIndex:
    def __init__(self, path: Path, s: Settings):
        path = Path(path)
        assert_writable(path, s)
        safe_mkdir(path.parent, s)
        self.path = path
        self._c = sqlite3.connect(str(path), check_same_thread=False)
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.execute("CREATE TABLE IF NOT EXISTS tracks("
                        "path TEXT PRIMARY KEY, mtime REAL NOT NULL, data TEXT NOT NULL)")
        self._c.commit()

    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> "MusicIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def upsert(self, t: TrackInfo) -> None:
        self._c.execute("INSERT INTO tracks(path, mtime, data) VALUES(?,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, data=excluded.data",
                        (t.path, t.mtime, t.model_dump_json()))
        self._c.commit()

    def get(self, path: str) -> TrackInfo | None:
        r = self._c.execute("SELECT data FROM tracks WHERE path=?", (str(path),)).fetchone()
        return TrackInfo.model_validate_json(r[0]) if r else None

    def all(self) -> list[TrackInfo]:
        rows = self._c.execute("SELECT data FROM tracks ORDER BY path").fetchall()
        return [TrackInfo.model_validate_json(r[0]) for r in rows]

    def remove_missing(self, existing: set[str]) -> None:
        for (p,) in self._c.execute("SELECT path FROM tracks").fetchall():
            if p not in existing:
                self._c.execute("DELETE FROM tracks WHERE path=?", (p,))
        self._c.commit()


def update_index(s: Settings, idx: MusicIndex,
                 on_progress: Callable[[int, int, str], None] | None = None,
                 tracker: BeatTracker | None = None) -> int:
    """Varre music_root (somente leitura) e analisa só o que é novo ou foi alterado."""
    files: list[Path] = []
    for dirpath, _dirs, names in os.walk(s.music_root):
        for n in names:
            if Path(n).suffix.lower() in AUDIO_EXTS:
                files.append(Path(dirpath) / n)
    existing = {str(f.resolve()) for f in files}
    done = 0
    for i, f in enumerate(files, 1):
        if on_progress:
            on_progress(i, len(files), f.name)
        try:
            old = idx.get(str(f.resolve()))
            if old is not None and old.mtime == f.stat().st_mtime:
                continue
            if tracker is None:
                tracker = _default_tracker()
            idx.upsert(analyze_track(f, tracker))
            done += 1
        except Exception as e:
            log.warning("Não foi possível analisar a trilha '%s': %s", f.name, e)
    idx.remove_missing(existing)
    return done
