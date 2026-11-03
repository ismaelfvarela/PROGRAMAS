"""Gera mídia sintética minúscula para testes. Escreve só nos caminhos recebidos."""
from __future__ import annotations

import subprocess
from pathlib import Path

from roteiro_ia.media.tools import ffmpeg_bin


def _run(args: list[str]) -> None:
    r = subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr}")


def make_video(path: Path, seconds: float, fps: str = "30000/1001",
               size: str = "1920x1080", channels: int = 2, tone_hz: int = 440) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={seconds}"]
    if channels > 0:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone_hz}:duration={seconds}",
                 "-ac", str(channels)]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if channels > 0:
        args += ["-c:a", "aac"]
    args += ["-t", str(seconds), str(path)]
    _run(args)
    return path


def make_audio(path: Path, seconds: float, noise_seed: int, delay_s: float = 0.0) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    total = seconds + delay_s
    af = f"adelay={int(delay_s * 1000)}:all=1," if delay_s > 0 else ""
    af += "aformat=sample_rates=48000:channel_layouts=mono"
    args = ["-f", "lavfi", "-i",
            f"anoisesrc=d={total}:c=white:r=48000:seed={noise_seed}:a=0.3",
            "-af", af, "-t", str(total)]
    if path.suffix.lower() == ".wav":
        args += ["-c:a", "pcm_s16le"]
    args.append(str(path))
    _run(args)
    return path
