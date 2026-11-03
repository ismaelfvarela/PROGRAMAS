import pytest

from roteiro_ia.media import tools


def test_fallback_winget_glob_pega_o_mais_novo(tmp_path, monkeypatch):
    base = tmp_path / "AppData/Local/Microsoft/WinGet/Packages"
    for ver in ("ffmpeg-8.0-full_build", "ffmpeg-9.0.2-full_build"):
        b = base / "Gyan.FFmpeg_X" / ver / "bin"
        b.mkdir(parents=True)
        (b / "ffprobe.exe").write_bytes(b"")
    monkeypatch.setattr(tools.shutil, "which", lambda n: None)
    monkeypatch.setattr(tools.Path, "home", classmethod(lambda cls: tmp_path))
    assert "9.0.2" in tools.ffprobe_bin()


def test_sem_ffmpeg_erro_em_portugues(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", lambda n: None)
    monkeypatch.setattr(tools.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(RuntimeError, match="Instale o FFmpeg"):
        tools.ffmpeg_bin()
