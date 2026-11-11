"""Formato das timelines da Formatura: o da câmera principal (não o da maioria dos vídeos).

Câmera principal, nesta ordem:
1. a pasta "Câmera com áudio principal" (colação);
2. a pasta de câmera chamada CAM A / CÂMERA A / CAM 1 (também "A CAM", "CAMERA 01"…);
3. a pasta de câmera com mais tempo gravado.
Dentro dela vale o formato mais comum dos vídeos. Sem pasta de câmera, fica o da maioria."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from roteiro_ia.areas.formatura.funcoes import FuncaoFormatura
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import MediaInfo, Role
from roteiro_ia.premiere.fcpxml import (AMOSTRA_AUDIO, Formato, _samplerate, _seq_rate,
                                        formato_do_projeto)

_CAMERAS = {FuncaoFormatura.camera, FuncaoFormatura.camera_iso, FuncaoFormatura.camera_audio}
_NOME_A = re.compile(r"\b(?:cam|camera|câmera|c)\s*[-_ ]?\s*(?:a|0*1)\b|\b(?:a|0*1)\s*[-_ ]?\s*cam\b",
                     re.IGNORECASE)


def pasta_principal(funcoes: dict[str, FuncaoFormatura], videos: list[MediaInfo]) -> str | None:
    tempo: Counter[str] = Counter()
    for m in videos:
        tempo[m.folder] += m.duration_s
    cams = [p for p, f in funcoes.items() if f in _CAMERAS and tempo[p] > 0]
    if not cams:
        return None
    audio = [p for p in cams if funcoes[p] == FuncaoFormatura.camera_audio]
    if audio:
        return max(audio, key=lambda p: tempo[p])
    nome_a = [p for p in cams if _NOME_A.search(re.split(r"[\\/]", p)[-1])]
    if nome_a:
        return max(nome_a, key=lambda p: tempo[p])
    return max(cams, key=lambda p: (tempo[p], p))


def formato_da_camera_principal(db: ProjectDB, source_root: Path,
                                funcoes: dict[str, FuncaoFormatura],
                                sondar=_samplerate) -> Formato:
    videos = [m for m in db.list_media()
              if m.kind == "video" and m.role != Role.ignorar and m.width > 0 and m.height > 0]
    pasta = pasta_principal(funcoes, videos)
    if pasta is None:
        return formato_do_projeto(db, source_root, sondar)
    videos = [m for m in videos if m.folder == pasta]
    tam = Counter((m.height, m.width) if m.rotation % 180 == 90 else (m.width, m.height)
                  for m in videos)
    (w, h), _n = tam.most_common(1)[0]
    rate = _seq_rate(videos)
    com_audio = [m for m in videos if m.audio_channels > 0]
    passo = max(1, len(com_audio) // AMOSTRA_AUDIO)
    taxas = Counter(t for t in (sondar(Path(source_root) / m.rel_path)
                                for m in com_audio[::passo][:AMOSTRA_AUDIO]) if t)
    sr = taxas.most_common(1)[0][0] if taxas else 48000
    return Formato(w, h, rate, sr)
