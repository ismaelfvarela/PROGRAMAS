"""Guarda de escrita: nada é gravado em unidades/pastas protegidas (somente leitura)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import Settings


class ProtectedPathError(Exception):
    """Tentativa de escrita em caminho protegido."""


_unc_cache: dict[str, list[str]] = {}


def _net_use_output() -> str:
    return subprocess.run(
        ["net", "use"], capture_output=True, text=True, timeout=15, check=False
    ).stdout


def _norm(p: str) -> str:
    return os.path.abspath(p).casefold()


def _unc_for_letters(letters: set[str]) -> list[str]:
    key = ",".join(sorted(letters))
    if key not in _unc_cache:
        found: list[str] = []
        try:
            for line in _net_use_output().splitlines():
                m = re.search(r"\b([A-Za-z]:)\s+(\\\\\S.*?)(?:\s{2,}|$)", line)
                if m and m.group(1)[0].casefold() in letters:
                    found.append(m.group(2).strip().rstrip("\\").casefold())
        except Exception:
            found = []
        _unc_cache[key] = found
    return _unc_cache[key]


def protected_paths(s: Settings) -> list[str]:
    roots = [_norm(r) for r in s.protected_roots]
    letters = {r[0] for r in roots if len(r) >= 2 and r[1] == ":"}
    return roots + _unc_for_letters(letters)


def _is_under(path: str, root: str) -> bool:
    root = root.rstrip("\\/")
    return path == root or path.startswith(root + "\\")


def assert_writable(path: Path, s: Settings) -> Path:
    norm = _norm(str(path))
    for root in protected_paths(s):
        if _is_under(norm, _norm(root)):
            raise ProtectedPathError(f"Escrita bloqueada em caminho protegido: {path}")
    return path


def safe_mkdir(path: Path, s: Settings) -> Path:
    assert_writable(path, s)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_write_text(path: Path, text: str, s: Settings) -> None:
    assert_writable(path, s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_write_bytes(path: Path, data: bytes, s: Settings) -> None:
    assert_writable(path, s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def safe_copy(src: Path, dst: Path, s: Settings) -> Path:
    assert_writable(dst, s)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst