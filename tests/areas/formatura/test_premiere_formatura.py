"""Pedido ao Premiere na Formatura: pasta das peças certa e projeto vazio modelo."""
import json
from pathlib import Path

from roteiro_ia.config import Settings
from roteiro_ia.paths import build_event_paths
from roteiro_ia.premiere.job import MODELO_VAZIO, write_job


def _p(tmp_path):
    s = Settings(protected_roots=[str(tmp_path / "R")], work_drive=str(tmp_path / "Y"),
                 e_root=str(tmp_path / "E"), g_root=str(tmp_path / "G"), system_dir=str(tmp_path / "S"))
    src = tmp_path / "R" / "2026-09-09 - SENAI MECATRONICA - COSTURA"
    src.mkdir(parents=True)
    p = build_event_paths(src, s, s.work_drive)
    Path(p.analysis_dir).mkdir(parents=True)
    return p, s


def test_clipe_usa_pasta_clipes_e_colacao_partes(tmp_path):
    p, s = _p(tmp_path)
    job = json.loads(write_job(p, s, None, area="formatura").read_text(encoding="utf-8"))
    assert job["pastas"]["pecas"] == "CLIPES"
    job = json.loads(write_job(p, s, None, area="formatura", pecas="PARTES DA COLAÇÃO")
                     .read_text(encoding="utf-8"))
    assert job["pastas"]["pecas"] == "PARTES DA COLAÇÃO"
    job = json.loads(write_job(p, s, None, area="casamento").read_text(encoding="utf-8"))
    assert job["pastas"]["pecas"] == "EPS"


def test_job_aponta_o_projeto_vazio_modelo(tmp_path):
    p, s = _p(tmp_path)
    job = json.loads(write_job(p, s, None, area="formatura").read_text(encoding="utf-8"))
    assert job["modelo_vazio"] == str(MODELO_VAZIO) and MODELO_VAZIO.is_file()
    assert MODELO_VAZIO.read_bytes()[:2] == b"\x1f\x8b"  # .prproj é gzip


def test_formulario_diz_a_pasta_das_pecas(qtbot, settings_tmp):
    from roteiro_ia.areas.formatura.formulario import FormularioFormatura
    from roteiro_ia.ui.worker import Runner
    f = FormularioFormatura(settings_tmp, Runner())
    qtbot.addWidget(f)
    assert f.pasta_pecas() == "CLIPES"
    f.seg_colacao.click()
    assert f.pasta_pecas() == "PARTES DA COLAÇÃO"


def test_janela_cabe_na_tela(qtbot, settings_tmp, tmp_path):
    from roteiro_ia.ui.app import MainWindow
    w = MainWindow(settings_tmp, tmp_path / "SIS" / "config.json")
    qtbot.addWidget(w)
    tela = w.screen().availableGeometry()
    assert w.minimumWidth() <= tela.width() and w.minimumHeight() <= tela.height()
    assert w.width() <= max(tela.width(), w.minimumSizeHint().width())
