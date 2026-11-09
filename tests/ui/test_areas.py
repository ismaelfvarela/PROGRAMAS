"""Áreas de trabalho: registro, pasta de músicas no formulário e a Formatura (ainda sem processar)."""
from __future__ import annotations

import dataclasses
import json

from roteiro_ia.areas import AREAS, area_por_id
from roteiro_ia.areas.formatura.momentos import MOMENTOS_FORMATURA
from roteiro_ia.models import FolderAssignment, Role
from roteiro_ia.pipeline import PROJECT_FILE, ProjectRequest
from roteiro_ia.paths import build_event_paths
from roteiro_ia.ui.formulario import FormularioEvento
from roteiro_ia.ui.projeto import ProjetoTab
from roteiro_ia.ui.widgets import CampoPastaMusicas
from roteiro_ia.ui.worker import Runner


def test_areas_registradas_em_ordem():
    assert [a.id for a in AREAS] == ["casamento", "formatura"]
    assert area_por_id("xyz").id == "casamento"
    assert area_por_id("formatura").nome == "Formatura"
    assert not area_por_id("formatura").pode_iniciar
    assert area_por_id("casamento").pode_iniciar


def test_momentos_da_formatura():
    assert MOMENTOS_FORMATURA[0] == "Oficina"
    assert MOMENTOS_FORMATURA[-1] == "Hino e encerramento"
    assert len(MOMENTOS_FORMATURA) == 14


def test_formulario_casamento_manda_pasta_de_musicas(qtbot, settings_tmp, evento):
    form = FormularioEvento(settings_tmp, Runner())
    qtbot.addWidget(form)
    assert form.set_event_folder(evento)
    form.campo_musicas.set_pasta(r"R:\2023-09-09 X\MUSICAS")
    req = form.build_request()
    assert req.area == "casamento" and req.pasta_musicas.endswith("MUSICAS")
    form.campo_musicas.set_pasta(None)
    assert form.build_request().pasta_musicas is None
    assert form.card_musicas in form.cards


def test_formulario_aplica_pasta_de_musicas_do_projeto(qtbot, settings_tmp, evento):
    form = FormularioEvento(settings_tmp, Runner())
    qtbot.addWidget(form)
    form.set_event_folder(evento)
    req = dataclasses.replace(form.build_request(), pasta_musicas=r"R:\OUTRA")
    form.load_request(req)
    assert form.campo_musicas.pasta() == r"R:\OUTRA"


def test_campo_musicas_avisa_pasta_inexistente(qtbot, tmp_path):
    c = CampoPastaMusicas()
    qtbot.addWidget(c)
    c.set_padrao(str(tmp_path))
    assert c.aviso.isHidden()
    assert c.pasta() is None
    c.set_pasta(str(tmp_path / "SUMIU"))
    assert not c.aviso.isHidden()
    assert "Pasta de músicas não encontrada. O roteiro segue sem músicas dela." in c.aviso.text()
    c.set_pasta(None)
    assert c.aviso.isHidden()


def test_formatura_nao_inicia(qtbot, settings_tmp, evento, tmp_path):
    tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", Runner(), area="formatura")
    qtbot.addWidget(tab)
    assert tab.set_event_folder(evento)
    assert not tab.btn_iniciar.isEnabled()
    assert tab.btn_iniciar.toolTip() == "A Formatura chega na próxima etapa."
    tab.form.set_rodando(False)
    assert not tab.btn_iniciar.isEnabled()


def test_formatura_recusa_pasta_fora_do_padrao(qtbot, settings_tmp, tmp_path):
    tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", Runner(), area="formatura")
    qtbot.addWidget(tab)
    pasta = tmp_path / "R" / "FORMATURA SEM DATA"
    pasta.mkdir(parents=True)
    assert tab.set_event_folder(pasta) is False


def test_abrir_projeto_de_outra_area_recusa(qtbot, settings_tmp, evento, tmp_path):
    req = ProjectRequest(source_dir=evento, work_drive=settings_tmp.work_drive,
                         assignments=[FolderAssignment(folder="A", role=Role.camera)],
                         n_episodios=None, derivados=set(), gemini_mode="gratis",
                         area="formatura")
    f = build_event_paths(evento, settings_tmp, settings_tmp.work_drive).analysis_dir / PROJECT_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(req.to_dict()), encoding="utf-8")
    tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", Runner(), area="casamento")
    qtbot.addWidget(tab)
    assert tab.set_event_folder(evento)
    assert tab.abrir_existente(evento) is False
    assert "Este projeto é de Formatura. Abra pela área Formatura." in tab.status.banner_erro.text()


def test_card_musicas_ao_lado_do_disco_e_tabela_sem_aperto(qtbot, settings_tmp, tmp_path):
    tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", Runner(), area="casamento")
    qtbot.addWidget(tab)
    tab.resize(1280, 860)
    tab.show()
    qtbot.waitExposed(tab)
    form = tab.form
    assert form.tabela.height() >= form.tabela.minimumHeight() == 150
    assert form.card_musicas.mapTo(form, form.card_musicas.rect().topLeft()).y() == \
        form.cards[1].mapTo(form, form.cards[1].rect().topLeft()).y()


def test_formatura_numera_gemini_como_5(qtbot, settings_tmp, tmp_path):
    tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", Runner(), area="formatura")
    qtbot.addWidget(tab)
    assert tab.form.card_gemini.lbl_numero.text() == "5"
    cas = ProjetoTab(settings_tmp, tmp_path / "cfg.json", Runner(), area="casamento")
    qtbot.addWidget(cas)
    assert cas.form.card_gemini.lbl_numero.text() == "6"
