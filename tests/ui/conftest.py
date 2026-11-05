import os

# a janela é testada sem tela (antes de qualquer QApplication ser criada pelo pytest-qt)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
def evento(tmp_path):
    ev = tmp_path / "R" / "2023-09-09 CASAMENTO TESTE"
    for sub in ("A", "B", "E - H4", "TRILHAS"):
        (ev / sub).mkdir(parents=True)
    return ev


@pytest.fixture(autouse=True)
def _sem_dialogos_modais(monkeypatch):
    """Um QMessageBox.question real trava o teste sem tela (ex.: o fechamento da janela com uma
    tarefa auxiliar ainda ativa); responde "Sim" por padrão. Testes que precisam de outra
    resposta fazem o próprio monkeypatch."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
