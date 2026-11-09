import json
from pathlib import Path

import pytest

from roteiro_ia.areas.formatura.cadastro import Curso, Formatura, listar, salvar
from roteiro_ia.areas.formatura.formulario import FormularioFormatura
from roteiro_ia.areas.formatura.projeto import (ProjetoFormatura, RequestFormatura,
                                                carregar_projeto, salvar_projeto)
from roteiro_ia.areas.formatura.ui_cadastro import DialogoFormatura
from roteiro_ia.models import Role
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import PROJECT_FILE, ProjectRequest
from roteiro_ia.ui.projeto import ProjetoTab
from roteiro_ia.ui.worker import Runner


@pytest.fixture
def ficha(settings_tmp):
    return salvar(settings_tmp, Formatura(instituicao="Escola X", ano=2026, semestre=2,
                                          cursos=[Curso(nome="Eletrônica", turmas=["T106", "T107"]),
                                                  Curso(nome="Mecânica", turmas=["Manhã"])]))


@pytest.fixture
def form(qtbot, settings_tmp):
    f = FormularioFormatura(settings_tmp, Runner())
    qtbot.addWidget(f)
    return f


def _escolher(combo, data):
    i = combo.findData(data)
    assert i >= 0, data
    combo.setCurrentIndex(i)


def test_oficina_liga_iniciar(form, ficha, oficina):
    assert form.set_event_folder(oficina)
    assert form.lbl_aviso.text() == "Escolha a formatura."
    assert not form.btn_iniciar.isEnabled()
    _escolher(form.combo_formatura, ficha.id)
    assert form.lbl_aviso.text() == "Escolha a turma."
    _escolher(form.combo_curso, "Eletrônica")
    _escolher(form.combo_turma, "T106")
    assert form.lbl_aviso.text() == "" and form.btn_iniciar.isEnabled()
    req = form.build_request()
    assert isinstance(req, RequestFormatura) and req.area == "formatura"
    assert (req.formatura.tipo, req.formatura.turma, req.formatura.curso) == ("oficina", "T106", "Eletrônica")
    assert req.formatura.duracao_min == 4 and req.n_episodios == 1 and req.derivados == set()
    assert [(a.folder, a.role, a.day_label) for a in req.assignments] == [
        ("2026-03-10\\CAM A", Role.camera, "2026-03-10"),
        ("2026-03-10\\H4", Role.audio_ambiente, "2026-03-10"),
        ("2026-03-12\\CAM A", Role.camera, "2026-03-12")]
    assert req.formatura.funcoes["2026-03-10\\H4"] == "gravador"


def test_tabela_com_dias(form, oficina):
    form.set_event_folder(oficina)
    t = form.tabela_f
    assert [t.item(r, 0).text() for r in range(t.rowCount())] == [
        "2026-03-10\\CAM A", "2026-03-10\\H4", "2026-03-12\\CAM A"]
    assert [t.cellWidget(r, 1).currentText() for r in range(t.rowCount())] == [
        "Câmera", "Gravador / lapela", "Câmera"]


def test_feira_sem_turma_inicia(form, ficha, oficina):
    form.set_event_folder(oficina)
    _escolher(form.combo_tipo, "feira")
    _escolher(form.combo_formatura, ficha.id)
    assert form.combo_turma.isHidden()
    assert form.btn_iniciar.isEnabled()
    pf = form.projeto_formatura()
    assert pf.tipo == "feira" and pf.turma is None and pf.duracao_min == 8


def test_colacao_avisa(form, ficha, tmp_path):
    ev = tmp_path / "R" / "2026-12-10 COLACAO ESCOLA X"
    for d in ("PGM", "CAM A", "H4", "FRIAS"):
        (ev / d).mkdir(parents=True)
    form.set_event_folder(ev)
    form.seg_colacao.click()
    _escolher(form.combo_formatura, ficha.id)
    assert form.lbl_aviso.text() == "Marque as turmas da colação."
    form.lista_turmas.item(0).setCheckState(Qt_Checked())
    assert form.lbl_aviso.text() == "A colação chega na próxima etapa (2.3)."
    assert not form.btn_iniciar.isEnabled()
    t = form.tabela_f
    assert [t.cellWidget(r, 1).currentText() for r in range(t.rowCount())] == [
        "Câmera ISO", "Imagens extras / frias", "Gravador / lapela", "Mesa de corte (programa)"]
    pf = form.projeto_formatura()
    assert pf.tipo == "colacao" and pf.turmas_colacao == [("Eletrônica", "T106")]


def Qt_Checked():
    from PySide6.QtCore import Qt
    return Qt.Checked


def _gravar_projeto(settings_tmp, ev, pf):
    req = ProjectRequest(source_dir=ev, work_drive=settings_tmp.work_drive, assignments=[],
                         n_episodios=1, derivados=set(), gemini_mode="gratis", area="formatura")
    ad = Path(build_event_paths(ev, settings_tmp, settings_tmp.work_drive).analysis_dir)
    ad.mkdir(parents=True, exist_ok=True)
    (ad / PROJECT_FILE).write_text(json.dumps(req.to_dict()), encoding="utf-8")
    salvar_projeto(ad, pf, settings_tmp)
    return ad


def test_reabrir_projeto_preenche(qtbot, settings_tmp, ficha, oficina, tmp_path):
    _gravar_projeto(settings_tmp, oficina, ProjetoFormatura(
        tipo="oficina", formatura_id=ficha.id, curso="Eletrônica", turma="T107", duracao_min=5,
        funcoes={"2026-03-10\\H4": "ignorar"}))
    recebidos = []

    class _Pipe:
        def __init__(self, req):
            recebidos.append(req)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def run(self, **k):
            return "concluido"

    tab = ProjetoTab(settings_tmp, tmp_path / "cfg.json", Runner(),
                     factory=lambda req, s, e: _Pipe(req), area="formatura")
    qtbot.addWidget(tab)
    tab.set_event_folder(oficina)
    assert tab.abrir_existente(oficina)
    f = tab.form
    assert f.combo_formatura.currentData() == ficha.id
    assert f.combo_turma.currentData() == "T107" and f.spin_duracao.value() == 5
    assert f.tabela_f.cellWidget(1, 1).currentText() == "Ignorar"
    qtbot.waitUntil(lambda: bool(recebidos), timeout=3000)
    assert isinstance(recebidos[0], RequestFormatura) and recebidos[0].formatura.turma == "T107"


def test_reabrir_com_ficha_apagada(form, settings_tmp, oficina):
    _gravar_projeto(settings_tmp, oficina, ProjetoFormatura(tipo="oficina", formatura_id="sumiu",
                                                            turma="T1"))
    form.set_event_folder(oficina)
    req = ProjectRequest.load(Path(build_event_paths(oficina, settings_tmp,
                                                     settings_tmp.work_drive).analysis_dir) / PROJECT_FILE)
    form.load_request(req)
    assert form.lbl_aviso.text() == "Formatura não encontrada. Escolha outra."
    assert not form.btn_iniciar.isEnabled()


def test_turma_fora_da_ficha_continua(form, settings_tmp, ficha, oficina):
    _gravar_projeto(settings_tmp, oficina, ProjetoFormatura(
        tipo="oficina", formatura_id=ficha.id, curso="Eletrônica", turma="T999"))
    form.set_event_folder(oficina)
    form.load_request(ProjectRequest.load(Path(build_event_paths(
        oficina, settings_tmp, settings_tmp.work_drive).analysis_dir) / PROJECT_FILE))
    assert form.combo_turma.currentData() == "T999"
    assert "turma não está mais na ficha" in form.combo_turma.currentText()
    assert form.btn_iniciar.isEnabled()


def test_duplicar(form, settings_tmp, ficha, oficina, tmp_path):
    ad = _gravar_projeto(settings_tmp, oficina, ProjetoFormatura(
        tipo="oficina", formatura_id=ficha.id, curso="Eletrônica", turma="T106", duracao_min=4.5))
    req = ProjectRequest.load(ad / PROJECT_FILE)
    req.pasta_musicas = str(tmp_path / "M" / "POP")
    (ad / PROJECT_FILE).write_text(json.dumps(req.to_dict()), encoding="utf-8")
    assert form.duplicar_de(oficina)
    assert form.combo_formatura.currentData() == ficha.id
    assert form.combo_curso.currentData() == "Eletrônica" and form.combo_turma.currentData() is None
    assert form.spin_duracao.value() == 4.5 and form.chk_seguir.isChecked()
    assert form.campo_musicas.pasta() == str(tmp_path / "M" / "POP")
    assert form.set_event_folder(oficina) is False
    assert form.lbl_evento.text() == "Escolha a pasta da nova turma."
    nova = tmp_path / "R" / "2026-03-20 OFICINA ESCOLA X T107"
    (nova / "CAM A").mkdir(parents=True)
    assert form.set_event_folder(nova)
    _escolher(form.combo_turma, "T107")
    pf = form.projeto_formatura()
    assert pf.duplicado_de == str(oficina) and pf.seguir_ideia and pf.turma == "T107"


def test_duplicar_recusa_o_que_nao_e_oficina(form, settings_tmp, ficha, oficina):
    _gravar_projeto(settings_tmp, oficina, ProjetoFormatura(tipo="feira", formatura_id=ficha.id))
    assert form.duplicar_de(oficina) is False


def test_dialogo_formatura_salva(qtbot, settings_tmp):
    d = DialogoFormatura(settings_tmp)
    qtbot.addWidget(d)
    d.edit_instituicao.setText("Escola Y")
    d.spin_ano.setValue(2027)
    d.combo_semestre.setCurrentIndex(0)
    d.adicionar_curso("Química", "T1, T2")
    d.aceitar()
    assert d.resultado is not None and d.resultado.semestre == 1
    assert [(f.instituicao, f.cursos[0].turmas) for f in listar(settings_tmp)] == [
        ("Escola Y", ["T1", "T2"])]


def test_dialogo_formatura_mostra_erro(qtbot, settings_tmp):
    d = DialogoFormatura(settings_tmp)
    qtbot.addWidget(d)
    d.edit_instituicao.setText("Escola Y")
    d.aceitar()
    assert d.resultado is None
    assert d.banner.text() == "Cadastre pelo menos um curso."
    assert listar(settings_tmp) == []


def test_dialogo_edita_existente(qtbot, settings_tmp, ficha):
    d = DialogoFormatura(settings_tmp, ficha)
    qtbot.addWidget(d)
    assert d.edit_instituicao.text() == "Escola X" and d.tabela.rowCount() == 2
    d.edit_instituicao.setText("Escola X2")
    d.aceitar()
    assert [f.instituicao for f in listar(settings_tmp)] == ["Escola X2"]
    assert d.resultado.id == ficha.id
