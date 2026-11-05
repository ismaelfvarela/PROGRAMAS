import subprocess
from pathlib import Path

import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.media import audio as au
from roteiro_ia.media.audio import analyze_audio, gain_for, load_mono, measure
from roteiro_ia.media.tools import ffmpeg_bin
from roteiro_ia.models import MediaInfo, Role


def _ff(*args):
    subprocess.run([ffmpeg_bin(), "-y", "-v", "error", *args], check=True)


def _sine(path, sec=3, vol_db=6):
    _ff("-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={sec}",
        "-af", f"volume={vol_db}dB", str(path))


def _fala(path, noise_amp=None, sec=6):
    expr = "0.3*sin(2*PI*300*t)*lt(mod(t,1),0.5)"
    if noise_amp is None:
        _ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={sec}", str(path))
    else:
        _ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={sec}",
            "-f", "lavfi", "-i", f"anoisesrc=a={noise_amp}:r=48000:d={sec}:c=white",
            "-filter_complex", "amix=inputs=2:duration=first:normalize=0", str(path))


def test_measure_seno_volume_conhecido(tmp_path):
    f = tmp_path / "s.wav"
    _sine(f)
    mean, peak, _ = measure(f)
    assert mean == pytest.approx(-15, abs=1)
    assert peak == pytest.approx(-12, abs=0.5)


def test_noise_floor_detecta_chiado(tmp_path):
    s = Settings()
    limpo, ruidoso = tmp_path / "l.wav", tmp_path / "r.wav"
    _fala(limpo)
    _fala(ruidoso, noise_amp=0.02)
    nf_l = measure(limpo)[2]
    nf_r = measure(ruidoso)[2]
    assert nf_r > s.noise_floor_threshold_db
    assert nf_l <= s.noise_floor_threshold_db
    assert nf_r > nf_l


def test_load_mono_formato(tmp_path):
    f = tmp_path / "s.wav"
    _sine(f, sec=2)
    x = load_mono(f, sr=8000)
    assert x.dtype.name == "float32" and x.ndim == 1
    assert len(x) == pytest.approx(16000, abs=200)
    y = load_mono(f, sr=8000, start_s=0.5, dur_s=1.0)
    assert len(y) == pytest.approx(8000, abs=200)


def test_load_mono_erro_em_portugues(tmp_path):
    with pytest.raises(RuntimeError, match="ffmpeg"):
        load_mono(tmp_path / "nao_existe.wav")


def test_gain_limitado():
    assert gain_for(Role.mesa, -40) == 20
    assert gain_for(Role.mesa, 40) == -20


def test_gain_ambiente():
    assert gain_for(Role.audio_ambiente, -24) == 6
    assert gain_for(Role.lapela_noiva, -10) == 7
    assert gain_for(Role.camera, -20) == 2
    assert gain_for(Role.outro_dia, -20) == 0.0


def _m(rel, ch=1):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=Role.mesa, day_label="D1",
                     kind="audio", duration_s=3.0, fps_num=0, fps_den=1, width=0, height=0,
                     rotation=0, audio_channels=ch)


def test_analyze_audio_grava_resume_e_falha(tmp_path, monkeypatch):
    s = Settings(work_drive=str(tmp_path / "work"), system_dir=str(tmp_path / "sys"))
    src = tmp_path / "src"
    (src / "A").mkdir(parents=True)
    _sine(src / "A" / "a.wav")
    with ProjectDB(tmp_path / "p.db", s) as db:
        ok = db.add_media(_m("A\\a.wav"))
        db.add_media(_m("A\\falta.wav"))
        db.add_media(_m("A\\mudo.mp4", ch=0))
        analyze_audio(db, s, src)
        st = db.get_audio_stats(ok)
        assert st is not None and st.mean_db == pytest.approx(-15, abs=1)
        assert len(db.list_falhas()) == 1
        assert db.list_falhas()[0].rel_path == "A\\falta.wav"
        # resume: não mede de novo
        vistos = []
        monkeypatch.setattr(au, "measure", lambda p: vistos.append(p.name) or (_ for _ in ()).throw(OSError("x")))
        analyze_audio(db, s, src)
        assert vistos == ["falta.wav"]
