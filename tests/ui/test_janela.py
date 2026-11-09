import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from roteiro_ia.models import Role
from roteiro_ia.ui.textos import ROLE_LABELS, STAGE_NAMES, label_to_role, role_label


def test_papeis_em_portugues_ida_e_volta():
    assert set(ROLE_LABELS) == set(Role)
    assert len(set(ROLE_LABELS.values())) == len(Role)
    for r in Role:
        assert label_to_role(role_label(r)) is r
    assert role_label(Role.outro_dia) == "Outro dia"
    assert role_label(Role.camera) == "Câmera"
    with pytest.raises(ValueError):
        label_to_role("camera")


def test_nomes_das_etapas():
    from roteiro_ia.pipeline import STAGES
    assert list(STAGE_NAMES) == STAGES
    assert STAGE_NAMES["analise"] == "Análise com IA"
    assert STAGE_NAMES["proxies"] == "Proxies 480p"


@pytest.fixture
def janela(qtbot, settings_tmp, tmp_path):
    from roteiro_ia.ui.app import MainWindow
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json")
    qtbot.addWidget(w)
    yield w
    w.runner.wait_all(5000)


def test_icone_do_programa_tem_todos_os_tamanhos(qtbot):
    from roteiro_ia.ui.app import icone_app
    ic = icone_app()
    assert not ic.isNull()
    tamanhos = {s.width() for s in ic.availableSizes()}
    assert {16, 32, 48, 256} <= tamanhos


def test_tema_carrega_do_pacote():
    from roteiro_ia.ui.app import load_theme
    qss = load_theme()
    assert "#d9774a" in qss and "#1b1b1d" in qss
    assert "{ICONES}" not in qss
    import re
    from pathlib import Path
    icones = re.findall(r'url\("([^"]+)"\)', qss)
    assert icones and all(Path(i).is_file() for i in icones)


def test_janela_abre_e_iniciar_espera_pasta_valida(janela, evento, tmp_path):
    pj = janela.projeto
    assert janela.minimumWidth() == 1100 and janela.minimumHeight() == 720
    assert not pj.btn_iniciar.isEnabled()
    ruim = tmp_path / "R" / "CASAMENTO SEM DATA"
    ruim.mkdir()
    pj.set_event_folder(ruim)
    assert not pj.btn_iniciar.isEnabled()
    assert "data" in pj.form.lbl_evento.text().lower()
    assert pj.form.lbl_evento.property("estado") == "erro"
    pj.set_event_folder(evento)
    assert pj.btn_iniciar.isEnabled()
    assert "09/09/2023" in pj.form.lbl_evento.text()


def test_tabela_de_subpastas_sugere_papeis_e_dia(janela, evento):
    pj = janela.projeto
    pj.set_event_folder(evento)
    papeis = {a.folder: a.role for a in pj.form.assignments()}
    assert papeis == {"A": Role.camera, "B": Role.camera, "E - H4": Role.audio_ambiente,
                      "TRILHAS": Role.ignorar}
    linha = pj.form.tabela.row_of("B")
    assert not pj.form.tabela.dia_edit(linha).isEnabled()
    pj.form.tabela.set_role(linha, Role.outro_dia)
    assert pj.form.tabela.dia_edit(linha).isEnabled()
    pj.form.tabela.dia_edit(linha).setText("Pré-wedding")
    b = next(a for a in pj.form.assignments() if a.folder == "B")
    assert (b.role, b.day_label) == (Role.outro_dia, "Pré-wedding")


def test_pedido_reflete_entregas_e_modo(janela, evento):
    pj = janela.projeto
    pj.set_event_folder(evento)
    req = pj.form.build_request()
    assert req.n_episodios is None  # "Livre" marcado por padrão
    assert req.derivados == {"trailer", "teaser", "stories"}
    assert req.gemini_mode == "gratis"
    assert pj.form.lbl_privacidade.isVisibleTo(pj)
    pj.form.chk_livre.setChecked(False)
    pj.form.spin_episodios.setValue(3)
    pj.form.chk_teaser.setChecked(False)
    janela.s.price_usd_per_mtok = 0.3  # o modo pago só fica disponível com preço configurado
    pj.form.atualizar_preco()
    pj.form.btn_pago.click()
    req = pj.form.build_request()
    assert (req.n_episodios, req.derivados, req.gemini_mode) == (3, {"trailer", "stories"}, "pago")
    assert not pj.form.lbl_privacidade.isVisibleTo(pj)


def test_progresso_atualiza_etapas(janela):
    st = janela.projeto.status
    st.on_progresso("inventario", "Iniciando: inventário das mídias", 0.0)
    assert st.etapas.estado("inventario") == "rodando"
    st.on_progresso("inventario", "Concluído: inventário das mídias", 1.0)
    st.on_progresso("proxies", "proxies 480p: 3/10", 0.3)
    assert st.etapas.estado("inventario") == "feito"
    assert st.etapas.estado("proxies") == "rodando"
    assert st.etapas.estado("audio") == "pendente"


def test_pausa_mostra_aviso_e_agenda_retomada(janela, evento):
    pj = janela.projeto
    pj.set_event_folder(evento)
    quando = (datetime.now() + timedelta(hours=2)).astimezone()
    pj._on_retomar_em(quando)
    pj._on_terminou("pausado")
    assert pj.status.banner_pausa.isVisibleTo(pj)
    assert f"Continua automaticamente às {quando:%H:%M}" in pj.status.banner_pausa.text()
    assert pj.timer_retomar.isActive()
    assert pj.timer_retomar.remainingTime() > 60 * 60 * 1000
    pj.timer_retomar.stop()


def test_concluido_mostra_acoes_finais(janela, evento):
    pj = janela.projeto
    pj.set_event_folder(evento)
    pj._on_terminou("concluido")
    assert pj.status.painel_final.isVisibleTo(pj)
    assert "Janela → Extensões → Roteiro IA" in pj.status.lbl_premiere.text()
    assert pj.status.painel_premiere is not None


class _PipeFalso:
    def __init__(self, chamadas, falha=None):
        self.chamadas, self.falha, self.resume_at = chamadas, falha, None

    def prepare(self):
        self.chamadas.append("prepare")
        return None, 3.5

    def run(self, aprovado_custo=False, refazer_falhas=True):
        self.chamadas.append(("run", aprovado_custo))
        if self.falha:
            raise self.falha
        return "concluido"

    def close(self):
        pass


def _janela_com(qtbot, settings_tmp, tmp_path, factory):
    from roteiro_ia.ui.app import MainWindow
    w = MainWindow(settings_tmp, tmp_path / "SISTEMA" / "config.json", factory=factory)
    qtbot.addWidget(w)
    return w


def test_modo_pago_confirma_custo_e_roda_aprovado(qtbot, settings_tmp, tmp_path, evento):
    chamadas, pedidos = [], []

    def factory(req, s, eventos):
        pedidos.append(req)
        return _PipeFalso(chamadas)

    settings_tmp.price_usd_per_mtok = 0.3
    w = _janela_com(qtbot, settings_tmp, tmp_path, factory)
    pj = w.projeto
    custos = []
    pj.confirmar_custo = lambda c: custos.append(c) or True
    pj.set_event_folder(evento)
    pj.form.btn_pago.click()
    pj.btn_iniciar.click()
    qtbot.waitUntil(lambda: pj.status.painel_final.isVisibleTo(pj), timeout=5000)
    w.runner.wait_all(5000)
    assert chamadas == ["prepare", ("run", True)]
    assert custos == [3.5]
    assert pedidos[0].gemini_mode == "pago"
    assert pj.btn_iniciar.isEnabled()


def test_caminho_protegido_mostra_faixa_vermelha(qtbot, settings_tmp, tmp_path, evento):
    from roteiro_ia.safety import ProtectedPathError
    w = _janela_com(qtbot, settings_tmp, tmp_path, lambda req, s, ev: _PipeFalso(
        [], falha=ProtectedPathError("Escrita bloqueada em caminho protegido: R:\\x")))
    pj = w.projeto
    pj.set_event_folder(evento)
    pj.btn_iniciar.click()
    qtbot.waitUntil(lambda: pj.status.banner_erro.isVisibleTo(pj), timeout=5000)
    w.runner.wait_all(5000)
    assert pj.status.banner_erro.text().startswith("Bloqueado por segurança: ")
    assert "Bloqueado por segurança" in pj.status.log.toPlainText()
    qtbot.waitUntil(lambda: pj.btn_iniciar.isEnabled(), timeout=5000)


# ------------------------------------------------------------------ revisão final


def test_pago_desabilitado_sem_preco(janela):
    form = janela.projeto.form
    assert janela.s.price_usd_per_mtok == 0
    assert not form.btn_pago.isEnabled()
    assert "preço por milhão de tokens" in form.btn_pago.toolTip()
    assert form.modo() == "gratis"
    janela.s.price_usd_per_mtok = 0.5
    janela._config_salva()
    assert form.btn_pago.isEnabled()


def test_retomada_automatica_nao_refaz_falhas(janela, evento):
    pj = janela.projeto
    pj.set_event_folder(evento)
    pj._req = pj.form.build_request()
    pj._ultima = ("run", False, None)
    visto = []
    pj._start = lambda *a, **k: visto.append((a, k))
    pj._retomar()
    assert visto == [(("run", False, None), {"refazer_falhas": False})]


def test_fechar_com_tarefa_auxiliar_pergunta(janela, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    perguntas = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: perguntas.append(a) or QMessageBox.No)
    monkeypatch.setattr(janela.runner, "ativo", lambda: True)  # ex.: índice de trilhas rodando
    e = QCloseEvent()
    janela.closeEvent(e)
    assert perguntas and not e.isAccepted()


def test_continuar_lista_recentes_e_abre_sem_pedir_pasta(qtbot, settings_tmp, tmp_path, evento,
                                                        monkeypatch):
    # "Continuar projeto existente" mostra os projetos recentes; um clique abre e retoma
    chamadas, pedidos = [], []

    def factory(req, s, eventos):
        pedidos.append(req)
        return _PipeFalso(chamadas)

    w = _janela_com(qtbot, settings_tmp, tmp_path, factory)
    pj = w.projeto
    pj.set_event_folder(evento)
    pj.btn_iniciar.click()  # cria o projeto e entra na lista
    qtbot.waitUntil(lambda: pj.status.painel_final.isVisibleTo(pj), timeout=5000)
    w.runner.wait_all(5000)
    from roteiro_ia.pipeline import ProjectRequest
    from roteiro_ia.paths import build_event_paths
    an = Path(build_event_paths(evento, settings_tmp).analysis_dir)
    an.mkdir(parents=True, exist_ok=True)
    pedidos[0].save(an / "projeto.json", settings_tmp)

    monkeypatch.setattr(pj.form, "escolher_pasta",
                        lambda *a: (_ for _ in ()).throw(AssertionError("pediu a pasta")))
    menu = pj.menu_recentes()
    acoes = [a for a in menu.actions() if a.text() and not a.isSeparator()]
    assert acoes[0].text().startswith("2023-09-09 CASAMENTO TESTE\talterado hoje ")
    assert acoes[-1].text() == "Outra pasta…"
    pj.form.set_event_folder(tmp_path)  # outra pasta selecionada antes
    acoes[0].trigger()
    qtbot.waitUntil(lambda: len(pedidos) == 2, timeout=5000)
    w.runner.wait_all(5000)
    assert pedidos[1].source_dir == evento and isinstance(pedidos[1], ProjectRequest)


def test_premiere_desde_o_comeco_pede_ao_painel(janela, evento, monkeypatch, tmp_path):
    import json

    from roteiro_ia.paths import build_event_paths
    from roteiro_ia.ui import projeto as mod
    abertos, lancados = [], []
    monkeypatch.setattr(mod.os, "startfile", abertos.append, raising=False)
    monkeypatch.setattr(mod.subprocess, "Popen", lambda args, **k: lancados.append(args))
    exe = tmp_path / "Premiere.exe"
    monkeypatch.setattr(mod, "premiere_exe", lambda: exe)
    rodando = {"sim": False}
    monkeypatch.setattr(mod, "premiere_aberto", lambda: rodando["sim"])
    pj = janela.projeto
    pj.set_event_folder(evento)
    pj._req = pj.form.build_request()
    p = build_event_paths(evento, janela.s, pj._req.work_drive)
    pedido = Path(janela.s.system_dir) / "pedido_premiere.json"

    # começo do trabalho: o Premiere abre e o painel cria o projeto no padrão
    pj.status.btn_premiere.click()
    assert lancados == [[str(exe)]]
    ped = json.loads(pedido.read_text(encoding="utf-8"))
    assert ped["acao"] == "abrir" and ped["job"] == str(p.analysis_dir / "job.json")
    job = json.loads((p.analysis_dir / "job.json").read_text(encoding="utf-8"))
    assert job["prproj"] == str(p.prproj_path) and job["pastas"]["pecas"] == "EPS"
    assert "Roteiro IA" in pj.status.banner_ok.text()

    # roteiro ainda não gerado: puxar avisa e não pede nada
    pedido.unlink()
    pj.status.btn_puxar.click()
    assert not pedido.exists() and "ainda não foi gerado" in pj.status.banner_erro.text()

    # com o XML e o Premiere já aberto: só o pedido (não abre outro Premiere)
    xml = p.analysis_dir / f"{p.event_name} - PREMIERE.xml"
    xml.write_text("<xmeml/>", encoding="utf-8")
    rodando["sim"] = True
    pj.status.btn_puxar.click()
    assert json.loads(pedido.read_text(encoding="utf-8"))["acao"] == "puxar"
    assert len(lancados) == 1
    assert json.loads((p.analysis_dir / "job.json").read_text(encoding="utf-8"))["xml"] == str(xml)

    # projeto já criado: o Premiere abre direto nele
    rodando["sim"] = False
    Path(p.prproj_path).parent.mkdir(parents=True, exist_ok=True)
    Path(p.prproj_path).write_text("x")
    pj.status.btn_premiere.click()
    assert lancados[-1] == [str(exe), str(p.prproj_path)]

    # pastas: só abre se existe; senão avisa
    pj.status.btn_pasta_videos.click()
    assert abertos == [] and pj.status.banner_erro.isVisibleTo(pj)
    Path(p.export_dir).mkdir(parents=True)
    pj.status.btn_pasta_videos.click()
    pj.status.btn_pasta_projeto.click()
    assert abertos == [str(p.export_dir), str(p.work_dir)]
