"""Aba Estilo: estado de cada vídeo, barra geral e mensagem de cota."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from roteiro_ia.gemini.style import StyleProfile, VideoStyleNotes

U1 = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
U2 = "https://youtu.be/BBBBBBBBBBB"          # na lista como digitado; o progresso usa o canônico
U2C = "https://www.youtube.com/watch?v=BBBBBBBBBBB"
U3 = "https://www.youtube.com/watch?v=CCCCCCCCCCC"
PL = "https://www.youtube.com/playlist?list=PLx"


def _notes(url):
    return VideoStyleNotes(url=url, tipo="episodio", duracao_s=600, ritmo_corte_s=3.0, abertura="a",
                           gancho="g", uso_falas="f", trilha="t", cor="c", observacoes="o")


@pytest.fixture
def aba(qtbot, settings_tmp, tmp_path):
    from roteiro_ia.ui.abas import EstiloTab
    from roteiro_ia.ui.worker import Runner
    s = settings_tmp
    s.style_urls = [U1, U2, U3, PL]
    d = Path(s.system_dir) / "estilo_cache"
    d.mkdir(parents=True)
    (d / "AAAAAAAAAAA.json").write_text(_notes(U1).model_dump_json(), encoding="utf-8")
    runner = Runner()
    w = EstiloTab(s, tmp_path / "SISTEMA" / "config.json", runner)
    qtbot.addWidget(w)
    yield w
    runner.wait_all(5000)


def textos(aba):
    """'<símbolo do estado>  <url>' — o símbolo vem do estado do item (ícone colorido)."""
    from roteiro_ia.ui.abas import ICONES_ESTILO
    out = []
    for i in range(aba.lista.count()):
        it = aba.lista.item(i)
        out.append(f"{ICONES_ESTILO[it.toolTip()]}  {it.text()}")
    return out


def test_icone_feito_verde_e_texto_sem_simbolo(qtbot):
    from roteiro_ia.ui.abas import CORES_ESTILO, _icone_estado
    assert CORES_ESTILO["feito"] == "#5fb37c"
    assert not _icone_estado("feito").isNull()
    img = _icone_estado("feito").pixmap(18, 18).toImage()
    cores = {img.pixelColor(x, y).name() for x in range(18) for y in range(18)
             if img.pixelColor(x, y).alpha() > 200}
    assert "#5fb37c" in cores


def test_ao_abrir_cache_aparece_feito(aba):
    assert textos(aba) == [f"✔  {U1}", f"○  {U2}", f"○  {U3}", f"⚠  {PL}"]
    assert aba._urls() == [U1, U2, U3, PL]  # o ícone não entra na lista salva


def test_slot_atualiza_icone_barra_e_atual(aba):
    aba._on_video(U2C, "analisando", 1, 3)
    assert textos(aba)[1] == f"▶  {U2}"
    assert U2C in aba.lbl_atual.text()
    aba._on_video(U2C, "feito", 2, 3)
    aba._on_video(U3, "erro", 2, 3)
    assert textos(aba)[1:3] == [f"✔  {U2}", f"✖  {U3}"]
    assert (aba.barra.value(), aba.barra.maximum()) == (2, 3)
    assert aba.barra.text() == "2 de 3 vídeos analisados"


def _fake_profile(fontes):
    return StyleProfile(fontes=fontes, duracao_media_episodio_s=600, ritmo_corte_medio_s=3.0,
                        padroes_abertura=["a"], padroes_gancho=["g"], uso_falas="f", trilhas="t",
                        cor="c", estrutura_teaser_trailer="e", resumo="perfil novo")


def test_gerar_atualiza_via_sinais(aba, qtbot, monkeypatch):
    from roteiro_ia.gemini import client as gc
    from roteiro_ia.gemini import style as st

    def fake_build(c, s, model=None, on_progress=None):
        on_progress(PL, "ignorado", 0, 3)
        on_progress(U1, "feito", 1, 3)
        for u in (U2C, U3):
            on_progress(u, "aguardando", 1, 3)
        on_progress(U2C, "analisando", 1, 3)
        on_progress(U2C, "feito", 2, 3)
        on_progress(U3, "analisando", 2, 3)
        on_progress(U3, "feito", 3, 3)
        return _fake_profile([U1, U2C, U3])

    monkeypatch.setattr(gc, "GeminiClient", lambda s: object())
    monkeypatch.setattr(st, "build_style_profile", fake_build)
    aba.gerar()
    qtbot.waitUntil(lambda: aba.btn_gerar.text() == "Gerar perfil", timeout=5000)
    assert textos(aba)[:3] == [f"✔  {U1}", f"✔  {U2}", f"✔  {U3}"]
    assert aba.barra.text() == "3 de 3 vídeos analisados"
    assert not aba.banner.text()


def test_cota_diaria_mostra_hora_e_quantos_faltam(aba, qtbot, monkeypatch):
    from roteiro_ia.gemini import client as gc
    from roteiro_ia.gemini import style as st
    quando = datetime.now(timezone.utc) + timedelta(hours=5)

    def fake_build(c, s, model=None, on_progress=None):
        on_progress(U1, "feito", 1, 3)
        on_progress(U2C, "aguardando", 1, 3)
        on_progress(U3, "aguardando", 1, 3)
        on_progress(U2C, "analisando", 1, 3)
        raise gc.QuotaPaused(quando, daily=True)

    monkeypatch.setattr(gc, "GeminiClient", lambda s: object())
    monkeypatch.setattr(st, "build_style_profile", fake_build)
    aba.gerar()
    qtbot.waitUntil(lambda: aba.btn_gerar.text() == "Gerar perfil", timeout=5000)
    msg = aba.banner.text()
    assert f"{quando.astimezone():%d/%m %H:%M}" in msg and "faltam 2 de 3" in msg
    assert textos(aba)[1] == f"○  {U2}"  # o que estava em análise volta a aguardar


def test_config_maximo_de_video_por_chamada(qtbot, settings_tmp, tmp_path):
    from PySide6.QtWidgets import QLabel
    from roteiro_ia.config import load_settings
    from roteiro_ia.ui.abas import ConfigTab
    w = ConfigTab(settings_tmp, tmp_path / "SISTEMA" / "config.json")
    qtbot.addWidget(w)
    assert any(lb.text() == "Máx. de vídeo por chamada (s)" for lb in w.findChildren(QLabel))
    assert w.sp_pacote.value() == 1800
    w.sp_pacote.setValue(900)
    assert w.salvar()
    assert load_settings(tmp_path / "SISTEMA" / "config.json").gemini_pacote_max_s == 900
