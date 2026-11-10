"""Roda o host/montar.jsx num Premiere falso (Node): pastas do padrão Fokuss, puxar o roteiro,
puxar de novo (ANTERIORES) e nada duplicado. Pulado se o Node não estiver instalado."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "premiere_panel"
FALSO = Path(__file__).parent / "js" / "premiere_falso.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node não instalado")

PRPROJ = r"E:\VÍDEOS 2023\01 - FOKUSS\EV\EV.prproj"
XML = r"Y:\EDIÇÃO 2023\EV\ANALISE\EV - PREMIERE.xml"
A1, A2, B1 = r"R:\EV\A\A1.MP4", r"R:\EV\A\A2.MP4", r"R:\EV\B\B1.MP4"
H4 = r"R:\EV\E - H4\4CH001M.wav"
MUSICA = r"M:\TRILHAS\musica.mp3"
LOGO = r"Y:\SISTEMA ROTEIRO\logo.png"


def _job(**kw):
    job = {"evento": "EV", "prproj": PRPROJ, "xml": XML, "backup_dir": r"Y:\EV\BACKUP PROJETO",
           "export_dir": r"G:\2023\EV",
           "pastas": {"fixas": ["COISAS", "CREDITOS"], "pecas": "EPS", "sequencia": "SEQUENCIA",
                      "trilha": "TRILHA", "videos": "VÍDEOS"},
           "midias": [{"original": A1, "pasta": "A"}, {"original": A2, "pasta": "A"},
                      {"original": B1, "pasta": "B"}, {"original": H4, "pasta": "E - H4"}],
           "proxies": [{"original": A1, "proxy": r"Y:\EV\PROXIES\A1_Proxy.mp4"}]}
    job.update(kw)
    return job


def rodar(tmp_path, passos, job=None, **cen):
    cenario = {"job": job or _job(), "passos": passos,
               "arquivos": [XML, A1, A2, B1, H4],
               "xml": {"sequencias": ["EP 01", "EP 02", "TEASER"], "midias": [A1, B1, MUSICA, LOGO]}}
    cenario.update(cen)
    f = tmp_path / "cenario.json"
    f.write_text(json.dumps(cenario, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([NODE, str(FALSO), str(PANEL / "host" / "montar.jsx"), str(f)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_abrir_cria_as_pastas_do_padrao_fokuss(tmp_path):
    out = rodar(tmp_path, ["abrirProjeto"])
    assert out["saidas"][0].startswith("ok|") and "Projeto criado" in out["saidas"][0]
    assert out["arvore"] == {"COISAS/": {}, "CREDITOS/": {}, "EPS/": {}, "SEQUENCIA/": {},
                             "TRILHA/": {}, "VÍDEOS/": {"A/": {}, "B/": {}, "E - H4/": {}}}
    assert out["salvo"] == 1


def test_abrir_de_novo_nao_duplica_pastas(tmp_path):
    out = rodar(tmp_path, ["abrirProjeto", "abrirProjeto"])
    assert out["projetos"] == 1  # o segundo clique usa o projeto já aberto
    assert list(out["arvore"]) == ["COISAS/", "CREDITOS/", "EPS/", "SEQUENCIA/", "TRILHA/", "VÍDEOS/"]


def test_projeto_existente_e_aberto_nao_recriado(tmp_path):
    out = rodar(tmp_path, ["abrirProjeto"], projeto_existente=PRPROJ)
    assert "Projeto aberto" in out["saidas"][0] and "Projeto criado" not in out["saidas"][0]


def test_puxar_roteiro_organiza_tudo_no_padrao(tmp_path):
    out = rodar(tmp_path, ["abrirProjeto", "puxarRoteiro"])
    saida = out["saidas"][1]
    assert saida.startswith("ok|"), saida
    arv = out["arvore"]
    assert "_IMPORTANDO ROTEIRO IA/" not in arv
    assert arv["EPS/"] == {"EP 01": "SEQ", "EP 02": "SEQ", "TEASER": "SEQ"}
    # usados (vindos do XML) e não usados (importados do disco) na pasta da sua câmera
    assert arv["VÍDEOS/"] == {"A/": {"A1.MP4": "proxy", "A2.MP4": "clip"}, "B/": {"B1.MP4": "clip"},
                              "E - H4/": {"4CH001M.wav": "clip"}}
    assert arv["TRILHA/"] == {"musica.mp3": "clip"}
    assert arv["COISAS/"] == {"logo.png": "clip"}
    assert "Proxies anexados: 1" in saida


def test_puxar_de_novo_guarda_anteriores_e_nao_duplica(tmp_path):
    out = rodar(tmp_path, ["puxarRoteiro", "puxarRoteiro"])
    assert out["saidas"][1].startswith("ok|"), out["saidas"][1]
    arv = out["arvore"]
    eps = arv["EPS/"]
    assert {k for k in eps if not k.endswith("/")} == {"EP 01", "EP 02", "TEASER"}
    anteriores = eps["ANTERIORES/"]
    assert len(anteriores) == 3 and all(n.startswith(("EP 01 (anterior", "EP 02 (anterior",
                                                      "TEASER (anterior")) for n in anteriores)
    assert arv["VÍDEOS/"]["A/"] == {"A1.MP4": "proxy", "A2.MP4": "clip"}  # sem repetidos
    assert arv["TRILHA/"] == {"musica.mp3": "clip"}


def test_puxar_sem_xml_avisa(tmp_path):
    out = rodar(tmp_path, ["puxarRoteiro"], job=_job(xml=""))
    assert out["saidas"][0].startswith("erro|") and "ainda n" in out["saidas"][0]


def test_formatura_usa_partes_da_colacao(tmp_path):
    job = _job()
    job["pastas"]["pecas"] = "PARTES DA COLAÇÃO"
    out = rodar(tmp_path, ["puxarRoteiro"], job=job)
    assert "PARTES DA COLAÇÃO/" in out["arvore"] and "EPS/" not in out["arvore"]
    assert out["arvore"]["PARTES DA COLAÇÃO/"] == {"EP 01": "SEQ", "EP 02": "SEQ", "TEASER": "SEQ"}


def test_pedidos_um_so_pega_e_grava_o_resultado(tmp_path):
    r = subprocess.run([NODE, str(Path(__file__).parent / "js" / "pedidos_teste.js"),
                        str(PANEL / "pedidos.js"), str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["so_um_pega"] and out["acao"] == "puxar" and not out["sobrou_pedido"]
    assert out["chamadas"] == ["puxarRoteiro"]
    assert out["resultado"]["estado"] == "ok" and out["resultado"]["por"] == "servico"
    assert out["velho_ignorado"] and out["desconhecido_ignorado"] and out["lendo_sobrando"] == 0
