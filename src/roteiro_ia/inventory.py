"""Inventário da pasta do evento (somente leitura)."""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path

from roteiro_ia import controle
from roteiro_ia.db import ProjectDB
from roteiro_ia.media import probe as _probe
from roteiro_ia.media.tools import ffprobe_bin
from roteiro_ia.models import FolderAssignment, Role

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".mts", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a"}
IGNORED_EXTS = {".pek", ".cfa", ".pkf", ".prv", ".lrf"}


def suggest_role(folder_name: str) -> Role:
    n = folder_name.upper().strip()
    if re.fullmatch(r"[A-D]", n):
        return Role.camera
    if re.search(r"H4|ZOOM|TASCAM|GRAVADOR", n):
        return Role.audio_ambiente
    if "MESA" in n:
        return Role.mesa
    if "LAPELA" in n and "NOIVO" in n:
        return Role.lapela_noivo
    if "LAPELA" in n and "NOIVA" in n:
        return Role.lapela_noiva
    if re.search(r"DRONE|DJI|MAVIC", n):
        return Role.drone
    if re.search(r"POCKET|OSMO|CELULAR", n):
        return Role.pocket
    if re.search(r"TRILHA|MUSICA|MÚSICA|PROXIES", n):
        return Role.ignorar
    if re.search(r"DESPEDIDA|PRE|LUA DE MEL|MAKING|PADRINHOS", n):
        return Role.outro_dia
    return Role.camera


def list_subfolders(source_dir: Path) -> list[str]:
    return sorted(p.name for p in Path(source_dir).iterdir() if p.is_dir())


def _dir_ignored(name: str) -> bool:
    n = name.lower()
    return n == "proxies" or n.startswith("adobe premiere pro")


def _iter_media(folder: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not _dir_ignored(d))
        for f in sorted(filenames):
            ext = os.path.splitext(f)[1].lower()
            if ext in IGNORED_EXTS:
                continue
            if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
                yield Path(dirpath) / f


def scan(source_dir: Path, assignments: list[FolderAssignment], db: ProjectDB,
         on_progress: Callable[[int, int], None] | None = None) -> int:
    ffprobe_bin()  # falha cedo, com uma única mensagem clara, se não houver ffprobe
    source_dir = Path(source_dir)
    files: list[tuple[Path, FolderAssignment]] = []
    for a in assignments:
        if a.role == Role.ignorar or not (source_dir / a.folder).is_dir():
            continue
        files.extend((p, a) for p in _iter_media(source_dir / a.folder))
    total, ok = len(files), 0
    for i, (path, a) in enumerate(files, 1):
        controle.atual().checkpoint()  # Pausar/Parar entre arquivos
        try:
            db.add_media(_probe.media_info_from_probe(path, source_dir, a))
            ok += 1
        except Exception as e:  # noqa: BLE001 - segue com os demais arquivos
            rel = str(path.relative_to(source_dir)).replace("/", "\\")
            db.add_falha("inventario", rel, f"Não foi possível ler o arquivo: {e}")
        if on_progress:
            on_progress(i, total)
    return ok
