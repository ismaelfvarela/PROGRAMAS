import subprocess

import numpy as np

from roteiro_ia.areas.formatura.colacao.defeitos import Amostras, classificar, medir
from roteiro_ia.areas.formatura.colacao.silencio import silencios
from roteiro_ia.media.tools import ffmpeg_bin

FPS = 4.0


def _base(n=80):
    """20 s normais: brilho 120, nitidez 20, pouca diferença."""
    return np.full(n, 120.0), np.full(n, 20.0), np.full(n, 2.0)


def _tipos(a):
    return [(d.tipo, round(d.inicio_s, 2), round(d.fim_s, 2)) for d in classificar(a, FPS)]


def test_normal_sem_defeito():
    assert classificar(Amostras(*_base()), FPS) == []


def test_escuro():
    b, n, d = _base()
    b[20:32] = 10  # 5 s a 8 s
    assert _tipos(Amostras(b, n, d)) == [("escuro", 4.75, 8.25)]


def test_escuro_curto_ignorado():
    b, n, d = _base()
    b[20:22] = 10  # 0,5 s
    assert _tipos(Amostras(b, n, d)) == []


def test_desfocado():
    b, n, d = _base()
    n[40:48] = 5  # 10 s a 12 s
    assert _tipos(Amostras(b, n, d)) == [("desfocado", 9.75, 12.25)]


def test_chicote_e_corte():
    b, n, d = _base()
    d[10] = 60  # corte de câmera: uma amostra só
    d[40:43] = 50  # chicote: 3 amostras
    assert _tipos(Amostras(b, n, d)) == [("chicote", 9.75, 11.0)]


def test_tremido():
    b, n, d = _base()
    d[20:32] = 15
    n[20:32] = 12
    assert [t for t, *_ in _tipos(Amostras(b, n, d))] == ["tremido"]


def test_defeitos_proximos_se_juntam():
    b, n, d = _base()
    b[20:26] = 10
    b[27:33] = 10  # buraco de 0,25 s
    assert _tipos(Amostras(b, n, d)) == [("escuro", 4.75, 8.5)]


def _ff(*args):
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", *args], check=True)


def test_medir_video_metade_preto(tmp_path):
    v = tmp_path / "pgm.mp4"
    _ff("-f", "lavfi", "-i", "color=black:size=320x180:rate=30:duration=2",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2",
        "-filter_complex", "[0][1]concat=n=2:v=1[v]", "-map", "[v]", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(v))
    a = medir(v)
    assert 14 <= len(a.brilho) <= 18
    ds = classificar(a, FPS)
    escuros = [x for x in ds if x.tipo == "escuro"]
    assert len(escuros) == 1 and escuros[0].inicio_s <= 0.5 and 1.5 <= escuros[0].fim_s <= 2.6


def test_silencios(tmp_path):
    w = tmp_path / "a.wav"
    _ff("-f", "lavfi", "-i", "anoisesrc=d=3:c=white:a=0.3:seed=1",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=6",
        "-f", "lavfi", "-i", "anoisesrc=d=3:c=white:a=0.3:seed=2",
        "-filter_complex", "[0]aformat=sample_rates=48000:channel_layouts=mono[a];"
        "[2]aformat=sample_rates=48000:channel_layouts=mono[c];[a][1][c]concat=n=3:v=0:a=1[o]",
        "-map", "[o]", str(w))
    s = silencios(w, limite_db=-45, min_s=4)
    assert len(s) == 1 and abs(s[0][0] - 3) < 0.3 and abs(s[0][1] - 9) < 0.3
    assert silencios(w, limite_db=-45, min_s=7) == []
