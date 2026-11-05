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


STATIC_UNC_ROOTS = [
    r"\\192.168.168.2\fokuss\r - editar time",
    r"\\192.168.168.2\fokuss\m - musicas",
]


def _strip_win_prefix(p: str) -> str:
    p = p.replace("/", "\\")
    low = p.casefold()
    if low.startswith("\\\\?\\unc\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\") or p.startswith("\\\\.\\"):
        return p[4:]
    return p


def _clean_segments(p: str) -> str:
    """Win32 descarta espaços/pontos finais de cada segmento."""
    unc = p.startswith("\\\\")
    segs = [s.rstrip(" .") for s in p.split("\\")]
    segs = [s for s in segs if s]
    out = ("\\\\" if unc else "") + "\\".join(segs)
    if not unc and len(out) == 2 and out[1] == ":":
        out += "\\"  # "r:" puro é relativo ao diretório atual do drive; a raiz é "r:\"
    return out


def _norm(p: str) -> str:
    return _clean_segments(os.path.abspath(_strip_win_prefix(p))).casefold()


def _resolved(p: str) -> str:
    """realpath do destino, via ancestral existente mais próximo."""
    p = os.path.abspath(_strip_win_prefix(p))
    tail: list[str] = []
    cur = p
    while not os.path.exists(cur):
        parent, name = os.path.split(cur)
        if parent == cur:
            break
        tail.insert(0, name)
        cur = parent
    return _norm(os.path.join(os.path.realpath(cur), *tail))


def _unc_for_letters(letters: set[str]) -> list[str]:
    key = ",".join(sorted(letters))
    if key in _unc_cache:
        return _unc_cache[key]
    found: list[str] = []
    try:
        for line in _net_use_output().splitlines():
            m = re.search(r"\b([A-Za-z]:)\s+(\\\\\S.*?)(?:\s{2,}|$)", line)
            if m and m.group(1)[0].casefold() in letters:
                found.append(_norm(m.group(2)))
    except Exception:
        return []  # falha não é cacheada: tenta de novo na próxima chamada
    _unc_cache[key] = found
    return found


def protected_paths(s: Settings) -> list[str]:
    roots = [_norm(r) for r in s.protected_roots]
    letters = {r[0] for r in roots if len(r) >= 2 and r[1] == ":"}
    out = roots + _unc_for_letters(letters)
    out += [u for u in STATIC_UNC_ROOTS if u not in out]
    return out


def _is_under(path: str, root: str) -> bool:
    root = root.rstrip("\\/")
    return path == root or path.startswith(root + "\\")


def assert_writable(path: Path, s: Settings) -> Path:
    candidates = {_norm(str(path)), _resolved(str(path))}
    # as raízes de protected_paths já vêm normalizadas: re-normalizar "r:\" com
    # abspath dependeria do diretório atual do processo
    for root in protected_paths(s):
        if any(_is_under(c, root) for c in candidates):
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
    part = dst.with_name(dst.name + ".part")
    assert_writable(part, s)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, part)
        os.replace(part, dst)
    except BaseException:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return dst