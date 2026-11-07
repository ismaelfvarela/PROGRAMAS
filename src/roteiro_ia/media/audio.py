"""Medidas de áudio: PCM mono, loudness/pico/piso de ruído e ganho para o mix."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from roteiro_ia import controle, proc
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.models import AudioStats, Role

TARGET_DB: dict[str, float] = {
    "mesa": -3.0,
    "lapela_noivo": -3.0,
    "lapela_noiva": -3.0,
    "audio_ambiente": -18.0,
    "camera": -18.0,
    "pocket": -18.0,
    "drone": -18.0,
}
MAX_GAIN_DB = 20.0
_FLOOR_DB = -120.0
_LONG_S = 30 * 60
_EXCERPT_S = 60.0
_N_EXCERPTS = 10
_NF_SR = 16000
_WIN_S = 0.05


def load_mono(path: Path, sr: int = 8000, start_s: float = 0,
              dur_s: float | None = None) -> np.ndarray:
    """Decodifica o áudio em mono float32 via pipe (nada é gravado em disco)."""
    cmd = [ffmpeg_bin(), "-v", "error", "-nostdin"]
    if start_s:
        cmd += ["-ss", f"{start_s:.3f}"]
    if dur_s is not None:
        cmd += ["-t", f"{dur_s:.3f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    try:
        r = proc.run(cmd, timeout=3600)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"O ffmpeg demorou demais ao ler o áudio de '{Path(path).name}'.") from e
    if r.returncode != 0:
        msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(
            f"O ffmpeg não conseguiu ler o áudio de '{Path(path).name}': "
            f"{msg[-1] if msg else 'erro desconhecido'}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def _duration_s(path: Path) -> float:
    r = proc.run([ffmpeg_bin(), "-nostdin", "-i", str(path)], timeout=120)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr.decode("utf-8", "replace"))
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def _window_rms_db(x: np.ndarray, sr: int) -> np.ndarray:
    n = int(sr * _WIN_S)
    k = len(x) // n
    if k == 0:
        return np.array([], dtype=np.float64)
    w = x[: k * n].astype(np.float64).reshape(k, n)
    rms = np.sqrt((w ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))  # 1e-6 = -120 dB


def _noise_floor(path: Path) -> float:
    dur = _duration_s(path)
    if dur > _LONG_S:
        step = (dur - _EXCERPT_S) / (_N_EXCERPTS - 1)
        parts = [_window_rms_db(load_mono(path, _NF_SR, i * step, _EXCERPT_S), _NF_SR)
                 for i in range(_N_EXCERPTS)]
        db = np.concatenate(parts)
    else:
        db = _window_rms_db(load_mono(path, _NF_SR), _NF_SR)
    if db.size == 0:
        return _FLOOR_DB
    return float(max(np.percentile(db, 10), _FLOOR_DB))


def measure(path: Path) -> tuple[float, float, float]:
    """(mean_db, peak_db, noise_floor_db) do primeiro fluxo de áudio."""
    r = proc.run([ffmpeg_bin(), "-nostdin", "-i", str(path), "-vn", "-af", "volumedetect",
                  "-f", "null", "-"], timeout=3600)
    err = r.stderr.decode("utf-8", "replace")
    mean = re.search(r"mean_volume:\s*(-?[\d.]+|-inf)", err)
    peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf)", err)
    if r.returncode != 0 or not mean or not peak:
        raise RuntimeError(f"Não consegui medir o volume de '{Path(path).name}'.")
    mean_db = max(float(mean[1]), _FLOOR_DB)
    peak_db = max(float(peak[1]), _FLOOR_DB)
    return mean_db, peak_db, _noise_floor(path)


def gain_for(role: Role, mean_db: float) -> float:
    target = TARGET_DB.get(str(role.value if isinstance(role, Role) else role))
    if target is None:
        return 0.0
    return max(-MAX_GAIN_DB, min(MAX_GAIN_DB, target - mean_db))


def analyze_audio(db: ProjectDB, s: Settings, source_root: Path) -> None:
    for m in db.list_media():
        controle.atual().checkpoint()  # Pausar/Parar entre arquivos
        if m.audio_channels <= 0 or m.id is None:
            continue
        if db.get_audio_stats(m.id) is not None:
            continue
        try:
            mean, peak, nf = measure(Path(source_root) / m.rel_path)
            db.set_audio_stats(AudioStats(media_id=m.id, mean_db=mean, peak_db=peak,
                                          noise_floor_db=nf,
                                          noisy=nf > s.noise_floor_threshold_db))
        except Exception as e:  # noqa: BLE001 - segue para o próximo arquivo
            db.add_falha("audio", m.rel_path, f"Falha ao medir o áudio: {e}")
