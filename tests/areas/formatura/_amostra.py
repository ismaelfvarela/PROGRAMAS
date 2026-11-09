"""Mídia e segmentos fixos para comparar prompts (snapshot do Casamento)."""
from roteiro_ia.models import MediaInfo, Role, Segment


def amostra():
    m = MediaInfo(id=1, rel_path=r"A\C1.MP4", folder="A", role=Role.camera, day_label="principal",
                  kind="video", duration_s=100.0, fps_num=30, fps_den=1, width=1920, height=1080,
                  rotation=0, audio_channels=2)
    segs = [Segment(id=1, media_id=1, start_s=0, end_s=10),
            Segment(id=2, media_id=1, start_s=10, end_s=20)]
    return m, segs, {1: "sim", 2: ""}
