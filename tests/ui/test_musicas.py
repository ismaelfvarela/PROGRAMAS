import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from roteiro_ia.db import ProjectDB
from roteiro_ia.paths import build_event_paths
from roteiro_ia.script.generate import MusicSuggestion, Piece, Roteiro, SceneRef


def _roteiro():
    cena = SceneRef(rel_path="A\\a.MP4", start_s=0, end_s=5, descricao="d", fala=None, motivo=None)
    pop = MusicSuggestion(origem="popular", path=None, titulo="Perfect - Ed Sheeran", bpm=None,
                          clima="romântico", motivo="m", padrao_corte="1-3", exige_licenca=True)
    bib = MusicSuggestion(origem="biblioteca", path="M:\\Trilhas\\lenta.mp3", titulo="Lenta",
                          bpm=80, clima="emotivo", motivo="m", padrao_corte="1-3",
                          exige_licenca=False)
    ep = Piece(tipo="episodio", numero=1, titulo="O começo", tema="t", abertura=cena,
               desenvolvimento=[], gancho=None, gancho_resolve_em=None, curva_emocao=[5],
               duracao_estimada_s=5, misturas=[], trilhas=[bib, pop],
               termos_musicbed=["emotional piano build", "uplifting wedding"])
    return Roteiro(arco="a", pecas=[ep], alertas=[])


@pytest.fixture
def aba(qtbot, settings_tmp, tmp_path, evento, monkeypatch):
    from roteiro_ia.ui import musicas as mod
    from roteiro_ia.ui.app import MainWindow
    down = tmp_path / "Downloads"
    down.mkdir()
    monkeypatch.setattr(mod, "pasta_downloads", lambda: down)
    abertos = []
    monkeypatch.setattr(mod, "_abrir_url", abertos.append)
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json")
    qtbot.addWidget(w)
    pj = w.projeto
    pj.set_event_folder(evento)
    pj._req = pj.form.build_request()
    p = build_event_paths(evento, settings_tmp, pj._req.work_drive)
    Path(p.analysis_dir).mkdir(parents=True)
    with ProjectDB(p.db_path, settings_tmp) as db:
        db.add_roteiro(_roteiro().model_dump_json())
    tab = next(w.tabs.widget(i) for i in range(w.tabs.count())
               if w.tabs.tabText(i) == "Músicas a baixar")
    yield tab, pj, down, abertos, p
    w.runner.wait_all(5000)


def _botoes(w):
    return [b.text() for b in w.findChildren(QPushButton)]


def test_mostra_buscas_do_artlist_e_sugestoes_populares(aba):
    tab, pj, down, abertos, p = aba
    tab.atualizar()
    textos = _botoes(tab.card_pecas)
    assert "Artlist: emotional piano build" in textos and "Ouvir: Perfect - Ed Sheeran" in textos
    assert "Musicbed: uplifting wedding" in textos
    b = next(b for b in tab.card_pecas.findChildren(QPushButton)
             if b.text() == "Artlist: emotional piano build")
    b.click()
    assert abertos == ["https://artlist.io/royalty-free-music/search?terms=emotional+piano+build"]


def test_traz_downloads_para_o_m_e_refaz_o_roteiro(aba, monkeypatch):
    tab, pj, down, abertos, p = aba
    (down / "Unbreakable Spirit.mp3").write_bytes(b"x")
    (down / "Nao e deste evento.mp3").write_bytes(b"y")
    tab.atualizar()
    for i in range(tab.lista.count()):
        it = tab.lista.item(i)
        if "Unbreakable" in it.text():
            it.setCheckState(Qt.Checked)
    tab.btn_trazer.click()
    mes = next((Path(tab.s.music_root)).glob("*/*"))
    assert [f.name for f in mes.iterdir()] == ["01 - Unbreakable Spirit.mp3"]
    assert (down / "Nao e deste evento.mp3").exists()  # só as marcadas
    salvo = json.loads((Path(p.analysis_dir) / "projeto.json").read_text(encoding="utf-8"))
    assert salvo["observacoes"]["baixadas"] == [str(mes / "01 - Unbreakable Spirit.mp3")]
    assert "01 - Unbreakable Spirit.mp3" in tab.banner_ok.text()
    assert tab.btn_refazer.isEnabled()
    pedidos = []
    monkeypatch.setattr(pj, "ajustar", pedidos.append)
    tab.btn_refazer.click()
    assert pedidos and "baixadas" in pedidos[0]


def test_sem_marcar_nada_avisa(aba):
    tab, pj, down, abertos, p = aba
    (down / "a.mp3").write_bytes(b"x")
    tab.atualizar()
    tab.btn_trazer.click()
    assert "Marque" in tab.banner_erro.text() and (down / "a.mp3").exists()
