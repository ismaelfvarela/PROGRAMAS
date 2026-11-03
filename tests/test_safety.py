import subprocess
from pathlib import Path

import pytest

from roteiro_ia import safety
from roteiro_ia.config import Settings
from roteiro_ia.safety import (
    ProtectedPathError,
    assert_writable,
    protected_paths,
    safe_copy,
    safe_mkdir,
    safe_write_bytes,
    safe_write_text,
)


def test_bloqueia_escrita_em_R(settings):
    with pytest.raises(ProtectedPathError):
        safe_write_text(Path(r"R:\2023\x.txt"), "a", settings)


def test_bloqueia_unc_equivalente(settings_unc):
    with pytest.raises(ProtectedPathError):
        assert_writable(Path(r"\\192.168.168.2\fokuss\M - MUSICAS\a.mp3"), settings_unc)


def test_bloqueia_letra_minuscula(settings):
    with pytest.raises(ProtectedPathError):
        assert_writable(Path(r"r:\2023\x.txt"), settings)


def test_permite_escrita_no_trabalho(tmp_path, settings):
    safe_write_text(tmp_path / "ok.txt", "ç", settings)
    assert (tmp_path / "ok.txt").read_text(encoding="utf-8") == "ç"


def test_safe_copy_destino_protegido_falha(tmp_path, settings):
    src = tmp_path / "a.txt"
    src.write_text("x")
    with pytest.raises(ProtectedPathError):
        safe_copy(src, Path(r"M:\a.txt"), settings)


def test_safe_mkdir_e_bytes_e_copy_ok(tmp_path, settings):
    d = safe_mkdir(tmp_path / "a" / "b", settings)
    assert d.is_dir()
    safe_write_bytes(d / "f.bin", b"\x00\x01", settings)
    out = safe_copy(d / "f.bin", tmp_path / "g.bin", settings)
    assert out.read_bytes() == b"\x00\x01"


def test_mkdir_e_bytes_bloqueados(settings):
    with pytest.raises(ProtectedPathError):
        safe_mkdir(Path(r"R:\novo"), settings)
    with pytest.raises(ProtectedPathError):
        safe_write_bytes(Path(r"M:\x.bin"), b"1", settings)


def test_prefixo_nao_casa_pasta_irma(tmp_path, settings):
    # "r:\" protegido não deve bloquear caminhos que apenas comecem com "r"
    assert assert_writable(tmp_path / "rx" / "a.txt", settings)


def test_protected_paths_mapeia_net_use(monkeypatch, settings):
    saida = (
        "OK           R:        \\\\192.168.168.2\\fokuss\\R - EDITAR TIME  Microsoft Windows Network\n"
        "OK           M:        \\\\192.168.168.2\\fokuss\\M - MUSICAS  Microsoft Windows Network\n"
    )
    monkeypatch.setattr(safety, "_net_use_output", lambda: saida)
    safety._unc_cache.clear()
    try:
        paths = protected_paths(settings)
    finally:
        safety._unc_cache.clear()
    assert r"\\192.168.168.2\fokuss\m - musicas" in paths
    assert r"\\192.168.168.2\fokuss\r - editar time" in paths
    assert "r:\\" in paths


def test_net_use_falha_so_letras(monkeypatch, settings):
    def boom():
        raise OSError("sem net")

    monkeypatch.setattr(safety, "_net_use_output", boom)
    safety._unc_cache.clear()
    try:
        assert protected_paths(settings) == ["r:\\", "m:\\"]
    finally:
        safety._unc_cache.clear()
