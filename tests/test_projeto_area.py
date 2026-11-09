from pathlib import Path

from roteiro_ia.pipeline import ProjectRequest


def test_projeto_json_antigo_e_casamento():
    d = {"source_dir": "R:/2023-09-09 X", "work_drive": "Y:", "assignments": [],
         "n_episodios": None, "derivados": [], "gemini_mode": "gratis"}
    r = ProjectRequest.from_dict(d)
    assert r.area == "casamento" and r.pasta_musicas is None


def test_projeto_ida_e_volta_com_area():
    r = ProjectRequest(Path("R:/2026-12-01 F"), "Y:", [], None, set(), "gratis",
                       area="formatura", pasta_musicas=r"M:\COMERCIAIS")
    r2 = ProjectRequest.from_dict(r.to_dict())
    assert (r2.area, r2.pasta_musicas) == ("formatura", r"M:\COMERCIAIS")
