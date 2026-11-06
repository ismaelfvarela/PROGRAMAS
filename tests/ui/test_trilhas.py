"""Aba Trilhas: total do índice com a contagem de análises completas."""
from pathlib import Path

import pytest

from roteiro_ia.models import TrackInfo


def _t(path, **kw):
    return TrackInfo(path=path, bpm=80, beats_s=[], downbeats_s=[], energy=[], duration_s=100,
                     has_vocals=False, perfil="calma", mtime=0, **kw)


@pytest.fixture
def aba(qtbot, settings_tmp):
    from roteiro_ia.music_index import MusicIndex
    from roteiro_ia.ui.abas import TrilhasTab
    from roteiro_ia.ui.worker import Runner
    s = settings_tmp
    with MusicIndex(Path(s.system_dir) / "trilhas.db", s) as idx:
        idx.upsert(_t("M:/a.mp3"))  # registro antigo (versão 1)
        idx.upsert(_t("M:/b.mp3", versao_analise=2))
        idx.upsert(_t("M:/c.mp3", versao_analise=2, analise_parcial=True))
    runner = Runner()
    w = TrilhasTab(s, runner)
    qtbot.addWidget(w)
    yield w
    runner.wait_all(5000)


def test_total_mostra_analises_completas(qtbot, aba):
    aba.contar()
    qtbot.waitUntil(lambda: aba.lbl_total.text() != "—", timeout=5000)
    assert aba.lbl_total.text() == "3 trilhas no índice (1 com análise completa)"


def test_texto_explica_voz_e_melodia(aba):
    assert "voz" in aba.lbl_info.text() and "melodia" in aba.lbl_info.text()
