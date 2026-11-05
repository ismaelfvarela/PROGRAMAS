from pathlib import Path
from xml.etree import ElementTree as ET

PANEL = Path(__file__).resolve().parents[2] / "premiere_panel"


def test_manifest_bem_formado():
    root = ET.parse(PANEL / "CSXS" / "manifest.xml").getroot()
    assert root.get("ExtensionBundleId") == "com.fokuss.roteiroia"
    ids = {e.get("Id") for e in root.iter("Extension")}
    assert "com.fokuss.roteiroia.panel" in ids
    host = next(root.iter("Host"))
    assert host.get("Name") == "PPRO"
    assert host.get("Version") == "[24.0,99.9]"
    rt = next(root.iter("RequiredRuntime"))
    assert rt.get("Name") == "CSXS" and rt.get("Version") == "11.0"
    assert root.findtext(".//ScriptPath") == "./host/montar.jsx"
    assert root.findtext(".//MainPath") == "./index.html"
    params = [p.text for p in root.iter("Parameter")]
    assert "--enable-nodejs" in params and "--mixed-context" in params


def test_jsx_define_montar_projeto():
    jsx = (PANEL / "host" / "montar.jsx").read_text(encoding="utf-8")
    assert "function montarProjeto" in jsx
    for termo in ("attachProxy", "importFiles", "newProject", "canProxy"):
        assert termo in jsx


def test_jsx_ascii_e_es3():
    raw = (PANEL / "host" / "montar.jsx").read_bytes()
    assert all(b < 128 for b in raw), "montar.jsx deve ser ASCII puro (use escapes \\u)"
    jsx = raw.decode("ascii")
    for token in ("=>", "let ", "const ", ".trim(", "JSON.", ".forEach(", "`"):
        assert token not in jsx, token
    for prefixo in ("ok:", "aviso:", "erro:"):
        assert prefixo in jsx


def test_main_js_chama_o_host():
    js = (PANEL / "main.js").read_text(encoding="utf-8")
    assert "__adobe_cep__.evalScript" in js and "montarProjeto(" in js


def test_jsx_nunca_sobrescreve_prproj():
    jsx = (PANEL / "host" / "montar.jsx").read_text(encoding="utf-8")
    corpo = jsx[jsx.index("function montarProjeto"):]
    i_new = corpo.index("app.newProject(")
    # o caminho do projeto passa por uma checagem .exists antes do newProject
    assert "_ri_prprojLivre(" in corpo[:i_new]
    livre = jsx[jsx.index("function _ri_prprojLivre"):]
    livre = livre[:livre.index("\n}\n")]
    assert ".exists" in livre and "_v" in livre
    assert "app.newProject(job.prproj)" not in jsx
