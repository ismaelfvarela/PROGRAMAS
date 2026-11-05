"""Geração de proxies 480p H.264 na unidade de trabalho (a origem nunca é alterada).

O Premiere só troca proxy <-> original quando fps, proporção e número de canais de
áudio batem; por isso esses três valores são preservados exatamente.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.media.probe import _rotation, _video_fps, probe
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.models import MediaInfo
from roteiro_ia.paths import EventPaths
from roteiro_ia.safety import ProtectedPathError, assert_writable, safe_copy, safe_mkdir

TARGET = 480
MIN_FREE_GB = 2.0  # abaixo disso a etapa pausa/repete em vez de virar falha por arquivo


def _free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1024**3
_FORCE_CPU = False  # gancho de teste: força libx264


def proxy_path(m: MediaInfo, p: EventPaths) -> Path:
    rel = Path(m.rel_path.replace("\\", "/"))
    return p.proxies_dir / rel.parent / f"{rel.stem}_Proxy.mp4"


def _part_path(final: Path) -> Path:
    return final.with_name(final.stem + ".part.mp4")


def _displayed(m: MediaInfo) -> tuple[int, int]:
    if m.rotation in (90, 270):
        return m.height, m.width
    return m.width, m.height


def ffmpeg_proxy_cmd(src: Path, dst: Path, m: MediaInfo, gpu: bool = True) -> list[str]:
    w, h = _displayed(m)
    scale = f"scale={TARGET}:-2" if h > w else f"scale=-2:{TARGET}"
    cmd = [ffmpeg_bin(), "-y", "-nostdin", "-v", "error", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?"]
    cmd += ["-c:v", "h264_nvenc" if gpu else "libx264"]
    if not gpu:
        cmd += ["-preset", "veryfast"]
    cmd += ["-vf", scale, "-pix_fmt", "yuv420p"]
    if m.fps_num > 0:
        cmd += ["-r", f"{m.fps_num}/{m.fps_den or 1}"]
    cmd += ["-b:v", "2M"]
    if m.audio_channels > 0:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", str(m.audio_channels)]
    else:
        cmd += ["-an"]
    cmd.append(str(dst))
    return cmd


def lrf_compatible(lrf: Path, m: MediaInfo) -> bool:
    try:
        info = probe(lrf)
        streams = info["streams"]
        v = next(s for s in streams if s.get("codec_type") == "video")
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        dur = float(info.get("format", {}).get("duration") or 0)
    except Exception:  # noqa: BLE001 - arquivo ilegível = incompatível
        return False
    num, den = _video_fps(v)  # mesma regra de FPS do inventário
    if num * (m.fps_den or 1) != m.fps_num * den:
        return False
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    if _rotation(v) in (90, 270):
        w, h = h, w
    mw, mh = _displayed(m)
    if not (w and h and mw and mh):
        return False
    if abs((w / h) / (mw / mh) - 1) > 0.01:
        return False
    if abs(dur - m.duration_s) > 0.5:
        return False
    return (int(a.get("channels", 0)) if a else 0) == m.audio_channels


def _find_lrf(m: MediaInfo, source_root: Path) -> Path | None:
    rel = Path(m.rel_path.replace("\\", "/"))
    for ext in (".LRF", ".lrf"):
        cand = Path(source_root) / rel.parent / f"{rel.stem}{ext}"
        if cand.is_file():
            return cand
    return None


def _run(cmd: list[str], timeout: float) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "tempo esgotado"
    return r.returncode == 0, (r.stderr or "").strip()[-300:]


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def make_proxies(db: ProjectDB, p: EventPaths, s: Settings, source_root: Path,
                 on_progress: Callable[[int, int], None] | None = None) -> None:
    safe_mkdir(p.proxies_dir, s)
    todo = [m for m in db.list_media() if m.kind == "video"]
    total = len(todo)
    for i, m in enumerate(todo, 1):
        final = proxy_path(m, p)
        existing = db.proxy_for(m.id)
        if existing and Path(existing).is_file():
            if on_progress:
                on_progress(i, total)
            continue
        livre = _free_gb(p.proxies_dir)
        if livre < MIN_FREE_GB:
            raise OSError(f"Disco de trabalho cheio: só {livre:.1f} GB livres em {p.proxies_dir} "
                          f"(mínimo {MIN_FREE_GB:.0f} GB). Libere espaço; a etapa será repetida.")
        try:
            assert_writable(final, s)
            safe_mkdir(final.parent, s)
            src = Path(source_root) / m.rel_path.replace("\\", "/")
            lrf = _find_lrf(m, source_root)
            if lrf is not None and lrf_compatible(lrf, m):
                safe_copy(lrf, final, s)
                db.set_proxy(m.id, str(final), "lrf")
                continue
            part = _part_path(final)
            assert_writable(part, s)
            timeout = max(600.0, 3 * m.duration_s)
            ok, err = False, ""
            for gpu in ((False,) if _FORCE_CPU else (True, False)):
                _discard(part)
                ok, err = _run(ffmpeg_proxy_cmd(src, part, m, gpu=gpu), timeout)
                if ok and part.is_file():
                    break
                ok = False
            if not ok:
                _discard(part)
                db.add_falha("proxies", m.rel_path,
                             f"Não foi possível gerar o proxy: {err or 'erro no ffmpeg'}")
                continue
            os.replace(part, final)
            db.set_proxy(m.id, str(final), "gerado")
        except ProtectedPathError:
            raise
        except Exception as e:  # noqa: BLE001 - segue com os demais arquivos
            db.add_falha("proxies", m.rel_path, f"Não foi possível gerar o proxy: {e}")
        finally:
            if on_progress:
                on_progress(i, total)
