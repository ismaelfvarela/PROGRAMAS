import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir("C:/Windows/Fonts"):  # medidas de texto reais (sem elas, larguras irreais)
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import pytest  # noqa: E402

from roteiro_ia.config import Settings  # noqa: E402


@pytest.fixture
def settings_tmp(tmp_path):
    for d in ("Y", "E", "G", "SISTEMA", "M", "R"):
        (tmp_path / d).mkdir()
    return Settings(protected_roots=[str(tmp_path / "R"), str(tmp_path / "M")],
                    music_root=str(tmp_path / "M"), work_drive=str(tmp_path / "Y"),
                    e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"),
                    system_dir=str(tmp_path / "SISTEMA"))


@pytest.fixture
def oficina(tmp_path):
    """Oficina gravada em dois dias, cada dia numa subpasta."""
    ev = tmp_path / "R" / "2026-03-10 OFICINA ESCOLA X T106"
    for sub in ("2026-03-10/CAM A", "2026-03-10/H4", "2026-03-12/CAM A"):
        (ev / sub).mkdir(parents=True)
    return ev


@pytest.fixture(autouse=True)
def _sem_dialogos_modais(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
