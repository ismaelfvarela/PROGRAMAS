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


def test_main_js_chama_o_host():
    js = (PANEL / "main.js").read_text(encoding="utf-8")
    assert "__adobe_cep__.evalScript" in js and "montarProjeto(" in js
