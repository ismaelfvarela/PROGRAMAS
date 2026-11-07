"""Transcrição local (faster-whisper) da melhor fonte de áudio de cada momento."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Protocol

from . import controle
from .db import ProjectDB
from .models import Role, Transcript, Word

log = logging.getLogger(__name__)

SOURCE_PRIORITY = [Role.mesa, Role.lapela_noivo, Role.lapela_noiva,
                   Role.audio_ambiente, Role.camera, Role.pocket]
_BETTER = {Role.mesa, Role.lapela_noivo, Role.lapela_noiva, Role.audio_ambiente}
_WEAK = {Role.camera, Role.pocket}
_COVERAGE = 0.90


def _union(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _covered_fraction(a: float, b: float, union: list[tuple[float, float]]) -> float:
    if b <= a:
        return 1.0
    tot = sum(max(0.0, min(b, y) - max(a, x)) for x, y in union)
    return tot / (b - a)


def plan_sources(db: ProjectDB) -> list[int]:
    medias = [m for m in db.list_media() if m.audio_channels > 0]
    better: dict[str, list[tuple[float, float]]] = {}
    for m in medias:
        if m.role in _BETTER:
            sr = db.get_sync(m.id)
            if sr is not None:
                better.setdefault(m.day_label, []).append(
                    (sr.timeline_start_s, sr.timeline_start_s + m.duration_s))
    better = {k: _union(v) for k, v in better.items()}

    chosen: list[tuple[int, int]] = []
    for m in medias:
        if m.role in _BETTER:
            chosen.append((SOURCE_PRIORITY.index(m.role), m.id))
        elif m.role in _WEAK:
            sr = db.get_sync(m.id)
            if sr is not None:
                a = sr.timeline_start_s
                frac = _covered_fraction(a, a + m.duration_s, better.get(sr.day_label, []))
                if frac >= _COVERAGE:
                    continue
            chosen.append((SOURCE_PRIORITY.index(m.role), m.id))
    chosen.sort()
    return [mid for _, mid in chosen]


_GPU_ERR = ("cuda", "cudnn", "cublas")  # inclui CUDA_ERROR_*


def is_gpu_error(e: BaseException) -> bool:
    """Só erros da GPU (CUDA/cuDNN/cuBLAS) fazem a transcrição cair para a CPU."""
    return any(k in str(e).lower() for k in _GPU_ERR)


class Transcriber(Protocol):
    def transcribe(self, path: Path) -> list[Word]: ...


class WhisperTranscriber:
    def __init__(self, model: str = "large-v3", device: str = "cuda",
                 compute_type: str = "int8_float16"):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        from faster_whisper import WhisperModel
        try:
            return WhisperModel(self.model_name, device=self.device,
                                compute_type=self.compute_type)
        except Exception as e:
            if self.device == "cpu" or not is_gpu_error(e):
                raise
            log.warning("GPU (CUDA) indisponível para a transcrição (%s). "
                        "Usando a CPU, que é mais lenta.", e)
            self.device, self.compute_type = "cpu", "int8"
            return WhisperModel(self.model_name, device="cpu", compute_type="int8")

    def transcribe(self, path: Path) -> list[Word]:
        if self._model is None:
            self._model = self._load()
        try:
            segs, _ = self._model.transcribe(
                str(path), language="pt", word_timestamps=True, vad_filter=True)
            segs = list(segs)  # gerador: erros de CUDA/cuDNN podem surgir aqui
        except Exception as e:
            if self.device == "cpu" or not is_gpu_error(e):
                raise  # erro do arquivo: vira falha dele e a GPU continua para os próximos
            log.warning("Falha ao usar a GPU na transcrição (%s). Usando a CPU.", e)
            from faster_whisper import WhisperModel
            self.device, self.compute_type = "cpu", "int8"
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            segs, _ = self._model.transcribe(
                str(path), language="pt", word_timestamps=True, vad_filter=True)
            segs = list(segs)
        words: list[Word] = []
        for seg in segs:
            for w in seg.words or []:
                text = w.word.strip()
                if text:
                    words.append(Word(text=text, start_s=float(w.start), end_s=float(w.end)))
        return words


def transcribe_event(db: ProjectDB, source_root: Path, t: Transcriber,
                     on_progress: Callable[[int, int, str], None] | None = None) -> None:
    ids = plan_sources(db)
    total = len(ids)
    for i, mid in enumerate(ids, 1):
        controle.atual().checkpoint()  # Pausar/Parar entre mídias
        m = db.get_media(mid)
        if on_progress:
            on_progress(i, total, m.rel_path)
        if db.get_transcript(mid) is not None:
            continue
        try:
            words = t.transcribe(Path(source_root) / m.rel_path)
            db.set_transcript(Transcript(media_id=mid, words=words, source_role=m.role))
        except Exception as e:
            db.add_falha("transcricao", m.rel_path, f"Falha ao transcrever o áudio: {e}")


def words_between(t: Transcript, start_s: float, end_s: float) -> str:
    return " ".join(w.text for w in t.words
                    if start_s <= (w.start_s + w.end_s) / 2 < end_s).strip()
