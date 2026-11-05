from pathlib import Path

import pytest

from roteiro_ia import paths as paths_mod
from roteiro_ia.config import Settings
from roteiro_ia.paths import (
    EventNameError,
    InsufficientSpaceError,
    build_event_paths,
    check_free_space,
    create_event_folders,
    estimate_proxy_gb,
    next_free_prproj,
    parse_event_name,
)

NOME = "2023-09-09 CASAMENTO NICOLE E OSNY"


@pytest.mark.parametrize(
    "nome",
    [
        "2023-09-09 CASAMENTO NICOLE E OSNY",
        "2026-05-08- EVENTO ADHONEP",
        "2026-03-31 IMAGENS SITE",
        "2026-04-15 - PEDRO REIS",
    ],
)
def test_parse_aceita_variacoes(nome):
    assert parse_event_name(nome).year in (2023, 2026)


def test_parse_sem_data_erro_pt():
    with pytest.raises(EventNameError, match="data"):
        parse_event_name("OFICINAS")


def test_parse_data_invalida_erro():
    with pytest.raises(EventNameError, match="data"):
        parse_event_name("2023-13-45 EVENTO")


def test_caminhos_usam_ano_do_evento(settings):
    p = build_event_paths(Path(r"R:\2023\2023-09-09 CASAMENTO NICOLE E OSNY"), settings)
    assert str(p.work_dir) == r"Y:\EDIÇÃO 2023\2023-09-09 CASAMENTO NICOLE E OSNY"
    assert str(p.prproj_path) == (
        r"E:\VÍDEOS 2023\01 - FOKUSS\2023-09-09 CASAMENTO NICOLE E OSNY"
        r"\2023-09-09 CASAMENTO NICOLE E OSNY.prproj"
    )
    assert str(p.export_dir) == r"G:\2023\01 - FOKUSS\2023-09-09 CASAMENTO NICOLE E OSNY"
    assert p.pdf_path.name == "2023-09-09 CASAMENTO NICOLE E OSNY - ROTEIRO.pdf"
    assert p.db_path == p.analysis_dir / "projeto.db"
    assert p.music_dir == p.work_dir / "TRILHAS"
    assert p.backup_dir == p.work_dir / "BACKUP PROJETO"
    assert p.proxies_dir == p.work_dir / "PROXIES"
    assert p.premiere_dir == p.prproj_path.parent


def _tmp_settings(tmp_path):
    return Settings(
        work_drive=str(tmp_path / "Y"),
        e_root=str(tmp_path / "E"),
        g_root=str(tmp_path / "G"),
        system_dir=str(tmp_path / "SISTEMA"),
        music_root=str(tmp_path / "M"),
        protected_roots=[str(tmp_path / "R")],
    )


def test_criar_pastas(tmp_path):
    s = _tmp_settings(tmp_path)
    p = build_event_paths(tmp_path / "R" / "2023" / NOME, s)
    create_event_folders(p, s)
    for d in (p.work_dir, p.proxies_dir, p.analysis_dir, p.music_dir,
              p.backup_dir, p.premiere_dir, p.export_dir):
        assert d.is_dir()
    assert not (tmp_path / "R" / "2023").exists()


def test_next_free_prproj(tmp_path):
    s = _tmp_settings(tmp_path)
    p = build_event_paths(tmp_path / "R" / "2023" / NOME, s)
    create_event_folders(p, s)
    assert next_free_prproj(p) == p.prproj_path
    p.prproj_path.write_bytes(b"")
    (p.premiere_dir / f"{NOME}_v2.prproj").write_bytes(b"")
    assert next_free_prproj(p) == p.premiere_dir / f"{NOME}_v3.prproj"


def test_estimate_proxy_gb():
    assert estimate_proxy_gb(12 * 3600) == pytest.approx(14.0)


class _Usage:
    def __init__(self, free):
        self.free = free


def test_espaco_insuficiente(monkeypatch, tmp_path):
    s = _tmp_settings(tmp_path)
    p = build_event_paths(tmp_path / "R" / "2023" / NOME, s)
    monkeypatch.setattr(paths_mod.shutil, "disk_usage", lambda _p: _Usage(1 * 1024**3))
    with pytest.raises(InsufficientSpaceError, match="GB"):
        check_free_space(p, 14.0)
    monkeypatch.setattr(paths_mod.shutil, "disk_usage", lambda _p: _Usage(50 * 1024**3))
    check_free_space(p, 14.0)
