from pathlib import Path
from xml.etree import ElementTree as ET

PANEL = Path(__file__).resolve().parents[2] / "premiere_panel"


def test_manifest_bem_formado():
    root = ET.parse(PANEL / "CSXS" / "manifest.xml").getroot()
    assert root.get("ExtensionBundleId") == "com.fokuss.roteiroia"
    assert {e.get("Id") for e in root.iter("Extension")} == {"com.fokuss.roteiroia.panel",
                                                             "com.fokuss.roteiroia.servico"}
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


def test_jsx_define_abrir_e_puxar():
    jsx = (PANEL / "host" / "montar.jsx").read_text(encoding="utf-8")
    assert "function abrirProjeto" in jsx and "function puxarRoteiro" in jsx
    assert "function montarProjeto" not in jsx
    for termo in ("attachProxy", "importFiles", "newProject", "openDocument", "canProxy",
                  "createBin", "moveBin", "consolidateDuplicates"):
        assert termo in jsx


def test_jsx_ascii_e_es3():
    raw = (PANEL / "host" / "montar.jsx").read_bytes()
    assert all(b < 128 for b in raw), "montar.jsx deve ser ASCII puro (use escapes \\u)"
    jsx = raw.decode("ascii")
    for token in ("=>", "let ", "const ", ".trim(", "JSON.", ".forEach(", "`"):
        assert token not in jsx, token
    for prefixo in ("ok:", "aviso:", "erro:"):
        assert prefixo in jsx


def test_main_js_chama_o_host_e_le_os_pedidos():
    js = (PANEL / "main.js").read_text(encoding="utf-8")
    assert "__adobe_cep__.evalScript" in js
    assert '"abrirProjeto"' in js and '"puxarRoteiro"' in js and '"exportarEntregas"' in js
    assert 'RoteiroPedidos.pegar("painel")' in js and "setInterval" in js
    ped = (PANEL / "pedidos.js").read_text(encoding="utf-8")
    assert "pedido_premiere.json" in ped and "renameSync" in ped and "resultado_premiere.json" in ped
    assert '<script src="pedidos.js"></script>' in (PANEL / "index.html").read_text(encoding="utf-8")


def test_servico_invisivel_abre_com_o_premiere():
    # o painel visível só roda se estiver aberto na tela: o pedido do app ficava parado
    root = ET.parse(PANEL / "CSXS" / "manifest.xml").getroot()
    exts = {e.get("Id"): e for e in root.iter("Extension") if e.find("DispatchInfo") is not None}
    s = exts["com.fokuss.roteiroia.servico"]
    assert s.findtext(".//MainPath") == "./servico.html"
    assert s.findtext(".//ScriptPath") == "./host/montar.jsx"
    assert s.findtext(".//AutoVisible") == "false" and s.findtext(".//Type") == "Custom"
    assert "com.adobe.csxs.events.ApplicationActivate" in [e.text for e in s.iter("Event")]
    html = (PANEL / "servico.html").read_text(encoding="utf-8")
    assert html.index("pedidos.js") < html.index("servico.js")
    assert 'pegar("servico")' in (PANEL / "servico.js").read_text(encoding="utf-8")
    inst = (PANEL / "instalar_painel.ps1").read_text(encoding="utf-8")
    for f in ("pedidos.js", "servico.html", "servico.js"):
        assert f'"{f}"' in inst
    for f in ("main.js", "pedidos.js", "servico.js"):
        assert all(b < 128 for b in (PANEL / f).read_bytes()), f
    js = (PANEL / "main.js").read_text(encoding="utf-8")
    html = (PANEL / "index.html").read_text(encoding="utf-8")
    for b in ("btnAbrir", "btnPuxar", "btnExportar"):
        assert f'id="{b}"' in html and f'getElementById("{b}")' in js


def test_jsx_nunca_sobrescreve_prproj():
    # projeto que já existe é ABERTO (openDocument), nunca criado de novo por cima
    jsx = (PANEL / "host" / "montar.jsx").read_text(encoding="utf-8")
    corpo = jsx[jsx.index("function _ri_abrir"):]
    corpo = corpo[:corpo.index("\n}\n")]
    i_exists = corpo.index("new File(job.prproj).exists")
    assert i_exists < corpo.index("app.openDocument(") < corpo.index("app.newProject(")
