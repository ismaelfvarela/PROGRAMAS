"""Localiza os executáveis ffmpeg/ffprobe."""
from __future__ import annotations

import shutil
from pathlib import Path

_WINGET_BIN = Path(
    r"C:\Users\FOKUSS-TAYCAN\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin")


def _find(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    cand = _WINGET_BIN / f"{name}.exe"
    if cand.is_file():
        return str(cand)
    raise RuntimeError(
        f"Não encontrei o '{name}'. Instale o FFmpeg e coloque-o no PATH do Windows.")


def ffmpeg_bin() -> str:
    return _find("ffmpeg")


def ffprobe_bin() -> str:
    return _find("ffprobe")
