"""Localiza os executáveis ffmpeg/ffprobe."""
from __future__ import annotations

import shutil
from pathlib import Path

_WINGET_REL = Path("AppData/Local/Microsoft/WinGet/Packages")


def _find(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    base = Path.home() / _WINGET_REL
    matches = [c for c in base.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe") if c.is_file()]
    if matches:
        return str(max(matches, key=lambda c: (c.stat().st_mtime, str(c))))
    raise RuntimeError(
        f"Não encontrei o '{name}'. Instale o FFmpeg e coloque-o no PATH do Windows.")


def ffmpeg_bin() -> str:
    return _find("ffmpeg")


def ffprobe_bin() -> str:
    return _find("ffprobe")
