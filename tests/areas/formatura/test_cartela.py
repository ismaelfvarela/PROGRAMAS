import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from roteiro_ia.areas.formatura.cadastro import Curso, Formatura
from roteiro_ia.areas.formatura.cartela import (campos_cartela, colocar_cartela, gerar_cartela_png,
                                                job_cartela, linhas_cartela)
from roteiro_ia.areas.formatura.projeto import ProjetoFormatura
from roteiro_ia.config import Settings
from roteiro_ia.media.tools import ffmpeg_bin, ffprobe_bin

PANEL = Path(__file__).resolve().parents[3] / "premiere_panel"
FICHA = Formatura(id="x", instituicao="Escola X", ano=2026, semestre=2,
                  cursos=[Curso(nome="Eletrônica", turmas=["T106", "T107"])])


def test_campos_do_clipe():
    pf = ProjetoFormatura(tipo="oficina", formatura_id="x", curso="Eletrônica", turma="T106")
    assert campos_cartela(pf, FICHA, None) == {
        "Instituição": "Escola X", "Curso": "Eletrônica", "Turma": "T106", "Formatura": "2026/2",
        "Semestre": "2º semestre", "Ano": "2026"}


def test_campos_da_colacao():
    pf = ProjetoFormatura(tipo="colacao", formatura_id="x", local="Teatro", cidade="Joinville",
                          turmas_colacao=[("Eletrônica", "T106"), ("Eletrônica", "T107")])
    c = campos_cartela(pf, FICHA, "2026-12-10")
    assert c["Turmas"] == "Eletrônica — T106; Eletrônica — T107"
    assert (c["Local"], c["Cidade"], c["Data"]) == ("Teatro", "Joinville", "10/12/2026")
    assert "Turma" not in c
    assert linhas_cartela(c)[0] == "Escola X" and "Teatro — Joinville" in linhas_cartela(c)


def _probe(p):
    r = subprocess.run([ffprobe_bin(), "-v", "error", "-show_entries",
                        "stream=width,height,pix_fmt", "-of", "json", str(p)],
                       capture_output=True, text=True)
    return json.loads(r.stdout)["streams"][0]


def test_png_transparente(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    logo = tmp_path / "logo.png"
    subprocess.run([ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i", "color=red:size=200x100:d=1",
                    "-frames:v", "1", str(logo)], check=True)
    out = gerar_cartela_png({"Instituição": "Escola X: Técnica's", "Turma": "T106 100%"}, str(logo),
                            tmp_path / "cartela.png", s)
    st = _probe(out)
    assert (st["width"], st["height"]) == (1920, 1080) and st["pix_fmt"] in ("rgba", "rgba64be")
    sem_logo = gerar_cartela_png({"Instituição": "X"}, str(tmp_path / "sumiu.png"), tmp_path / "c2.png", s)
    assert sem_logo.is_file()


XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4"><project><name>P</name><children><bin><name>EP</name><children>
<sequence id="seq-EP01"><name>EP01</name><duration>300</duration><rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>
<media><video><format/><track><clipitem id="c1"><name>a</name></clipitem><enabled>TRUE</enabled></track></video><audio/></media></sequence>
<sequence id="seq-X"><name>OUTRA</name><duration>10</duration><rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>
<media><video><track/></video><audio/></media></sequence>
</children></bin></children></project></xmeml>
"""


def _seq(xml, nome):
    root = ET.fromstring(xml.split("\n", 2)[2])
    return next(s for s in root.iter("sequence") if s.findtext("name") == nome)


def test_colocar_cartela_png(tmp_path):
    png = tmp_path / "cartela.png"
    png.write_bytes(b"x")
    out = colocar_cartela(XML, ["EP01"], str(png), 5)
    seq = _seq(out, "EP01")
    tracks = seq.findall("media/video/track")
    assert len(tracks) == 2
    ci = tracks[-1].find("clipitem")
    assert ci.findtext("name") == "cartela.png" and ci.findtext("start") == "0"
    assert int(ci.findtext("end")) == 150 and ci.find("file/pathurl") is not None
    assert [m.findtext("name") for m in seq.findall("marker")] == ["CARTELA"]
    assert len(_seq(out, "OUTRA").findall("media/video/track")) == 1


def test_colocar_faixa_reservada_para_mogrt():
    out = colocar_cartela(XML, ["EP01"], None, 5)
    seq = _seq(out, "EP01")
    assert len(seq.findall("media/video/track")) == 2
    assert seq.findall("media/video/track")[-1].find("clipitem") is None
    assert [m.findtext("name") for m in seq.findall("marker")] == ["CARTELA (MOGRT)"]


def test_job_cartela(tmp_path):
    s = Settings(system_dir=str(tmp_path / "s"), protected_roots=[])
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"evento": "E"}), encoding="utf-8")
    job_cartela(job, s, "C:\\cartela.mogrt", ["EP01"], {"Instituição": "Escola X"})
    j = json.loads(job.read_text(encoding="utf-8"))
    assert j["cartela"] == {"mogrt": "C:\\cartela.mogrt", "sequencias": ["EP01"],
                            "campos": {"Instituição": "Escola X"}}
    assert json.loads((Path(s.system_dir) / "ultimo_job.json").read_text(encoding="utf-8"))["cartela"]


def test_painel_preenche_mogrt():
    jsx = (PANEL / "host" / "montar.jsx").read_text(encoding="ascii")
    corpo = jsx[jsx.index("function montarProjeto"):]
    assert "_ri_cartela(job, msgs)" in corpo
    for termo in ("function _ri_cartela", "importMGT", "getMGTComponent", "getParamForDisplayName"):
        assert termo in jsx
