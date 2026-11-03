"""Leitura de metadados com ffprobe (somente leitura)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from roteiro_ia.media.tools import ffprobe_bin
from roteiro_ia.models import FolderAssignment, MediaInfo, Role


def probe(path: Path) -> dict:
    r = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe falhou: {r.stderr.strip() or 'arquivo ilegível'}")
    data = json.loads(r.stdout or "{}")
    if not data.get("streams"):
        raise RuntimeError("ffprobe não encontrou nenhum fluxo de mídia no arquivo")
    return data


def _fraction(s: str | None) -> tuple[int, int]:
    try:
        a, _, b = (s or "").partition("/")
        num, den = int(a), int(b or 1)
        if num > 0 and den > 0:
            return num, den
    except ValueError:
        pass
    return 0, 1


def _rotation(stream: dict) -> int:
    rot = None
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            rot = sd["rotation"]
            break
    if rot is None:
        rot = (stream.get("tags") or {}).get("rotate")
    try:
        return (int(round(float(rot) / 90)) * 90) % 360 if rot is not None else 0
    except (TypeError, ValueError):
        return 0


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _tag(info: dict, key: str) -> str | None:
    v = (info.get("format", {}).get("tags") or {}).get(key)
    if v:
        return v
    for st in info.get("streams", []):
        v = (st.get("tags") or {}).get(key)
        if v:
            return v
    return None


def media_info_from_probe(path: Path, root: Path, a: FolderAssignment) -> MediaInfo:
    """Monta o MediaInfo. Com rotação 90/270, width/height ficam como armazenados
    (sem trocar); a orientação é tratada na etapa de proxies."""
    info = probe(path)
    streams = info["streams"]
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise RuntimeError("o arquivo não tem vídeo nem áudio")
    rel = str(path.relative_to(root)).replace("/", "\\")
    folder = rel.split("\\")[0]
    if a.role == Role.outro_dia:
        role = Role.camera if video else Role.audio_ambiente
        day = a.folder
    else:
        role, day = a.role, a.day_label
    dur = info.get("format", {}).get("duration") or (video or audio).get("duration") or 0
    if video:
        num, den = _fraction(video.get("r_frame_rate"))
        if num == 0:
            num, den = _fraction(video.get("avg_frame_rate"))
        w, h, rot = int(video.get("width", 0)), int(video.get("height", 0)), _rotation(video)
    else:
        num, den, w, h, rot = 0, 1, 0, 0, 0
    return MediaInfo(
        rel_path=rel, folder=folder, role=role, day_label=day,
        kind="video" if video else "audio", duration_s=float(dur),
        fps_num=num, fps_den=den, width=w, height=h, rotation=rot,
        audio_channels=int(audio.get("channels", 0)) if audio else 0,
        created_at=_parse_time(_tag(info, "creation_time")),
        timecode=_tag(info, "timecode"))
