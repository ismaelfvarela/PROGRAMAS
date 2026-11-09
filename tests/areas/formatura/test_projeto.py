from pathlib import Path

from roteiro_ia import recentes
from roteiro_ia.areas.formatura.momentos import MOMENTOS_POR_TIPO
from roteiro_ia.areas.formatura.analise import TEXTOS_POR_TIPO
from roteiro_ia.areas.formatura.projeto import (ProjetoFormatura, RequestFormatura, caminho,
                                                carregar_projeto, musicas_usadas, salvar_projeto)
from roteiro_ia.areas.formatura.tipos import TipoTrabalho
from roteiro_ia.models import FolderAssignment, Role
from roteiro_ia.paths import build_event_paths
from roteiro_ia.pipeline import ProjectRequest


def test_formatura_json_ida_e_volta(tmp_path, settings_tmp):
    pf = ProjetoFormatura(tipo="oficina", formatura_id="x", curso="A", turma="T106",
                          funcoes={"2026-03-10\\CAM A": "camera"},
                          turmas_colacao=[("A", "T106")])
    salvar_projeto(tmp_path, pf, settings_tmp)
    assert caminho(tmp_path) == tmp_path / "formatura.json"
    assert carregar_projeto(tmp_path) == pf
    assert carregar_projeto(tmp_path / "nada") is None
    (tmp_path / "formatura.json").write_text("{", encoding="utf-8")
    assert carregar_projeto(tmp_path) is None


def test_request_formatura_e_um_project_request(tmp_path):
    pf = ProjetoFormatura(tipo="feira", formatura_id="x")
    r = RequestFormatura(source_dir=tmp_path, work_drive="Y:",
                         assignments=[FolderAssignment(folder="A", role=Role.camera)],
                         n_episodios=1, derivados=set(), gemini_mode="gratis",
                         area="formatura", formatura=pf)
    assert isinstance(r, ProjectRequest) and r.formatura is pf
    assert "formatura" not in r.to_dict()  # o projeto.json é o comum


def _evento(settings_tmp, nome, formatura_id, musica):
    ev = Path(settings_tmp.protected_roots[0]) / nome
    (ev / "CAM A").mkdir(parents=True)
    recentes.registrar(settings_tmp, ev, settings_tmp.work_drive, area="formatura")
    ad = Path(build_event_paths(ev, settings_tmp, settings_tmp.work_drive).analysis_dir)
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "projeto.json").write_text("{}", encoding="utf-8")
    salvar_projeto(ad, ProjetoFormatura(tipo="oficina", formatura_id=formatura_id, musica=musica),
                   settings_tmp)
    return ev


def test_musicas_usadas(settings_tmp):
    a = _evento(settings_tmp, "2026-03-10 OFICINA T106", "x", "M:\\a.mp3")
    _evento(settings_tmp, "2026-03-11 OFICINA T107", "x", None)
    _evento(settings_tmp, "2026-03-12 OFICINA OUTRA", "y", "M:\\b.mp3")
    assert musicas_usadas(settings_tmp, "x", exceto=None) == {"M:\\a.mp3"}
    assert musicas_usadas(settings_tmp, "x", exceto=a) == set()
    assert musicas_usadas(settings_tmp, "z", exceto=None) == set()


def test_textos_por_tipo():
    t = TEXTOS_POR_TIPO[TipoTrabalho.oficina]
    assert "formatura" in t.papel and "Oficina" in t.papel and "casamento" not in t.papel
    assert "chicote" in t.problemas and "mal enquadrado" in t.problemas
    assert t.momentos == MOMENTOS_POR_TIPO["oficina"]
    assert t.evento == "da mesma formatura"
    assert set(TEXTOS_POR_TIPO) == set(TipoTrabalho)
