import pytest

from roteiro_ia.script.manual import (CHATS, RespostaInvalida, SessaoManual, instrucao_json,
                                      ler_resposta, texto_para_o_chat)
from tests.script.test_generate import env, piece, ref, rot  # noqa: F401 - fixture e ajudantes


def test_pedido_leva_o_formato_json():
    t = texto_para_o_chat("PEDIDO X")
    # o formato no começo e no fim (o chat lê mal o fim de anexos grandes)
    assert t.startswith("ATENÇÃO — FORMATO DA RESPOSTA") and "PEDIDO X" in t
    assert "SOMENTE com um único JSON" in t and '"pecas"' in t
    assert "termos_musicbed" in instrucao_json()


def test_le_resposta_crua_com_cerca_e_com_texto_em_volta():
    j = rot(piece()).model_dump_json()
    assert ler_resposta(j).pecas[0].numero == 1
    assert ler_resposta(f"Claro! Aqui está:\n```json\n{j}\n```\nBom trabalho.").arco == "arco"
    assert ler_resposta(f"Segue o roteiro: {j} — qualquer coisa me avise").arco == "arco"


@pytest.mark.parametrize("texto,trecho", [
    ("", "Cole a resposta"),
    ("não sei fazer isso", "texto corrido"),
    ('{"arco": "a", "pecas": [', "o chat cortou"),
    ('{"arco": "a", "pecas": [}', "incompleto ou quebrado"),
    ('{"arco": "a", "pecas": [{"tipo": "episodio"}]}', "formato do roteiro"),
])
def test_resposta_invalida_explica(texto, trecho):
    with pytest.raises(RespostaInvalida) as e:
        ler_resposta(texto)
    assert trecho in str(e.value)


def test_sessao_corrige_ate_duas_vezes_e_grava(env):  # noqa: F811
    db, idx = env
    s = SessaoManual(db, idx, base="BASE", pedido="BASE")
    ruim = rot(piece(abertura=ref("A\\\\NAO_EXISTE.MP4")))
    assert s.conferir(ruim.model_dump_json())
    assert s.pode_corrigir()
    c1 = s.texto_correcao()
    assert "BASE" in c1 and "NAO_EXISTE" in c1 and "SOMENTE com um único JSON" in c1
    s.conferir(ruim.model_dump_json())
    s.texto_correcao()
    s.conferir(ruim.model_dump_json())
    assert not s.pode_corrigir() and s.correcoes == 2
    r = s.aceitar(["pelo chat"])
    assert "pelo chat" in r.alertas and db.latest_roteiro() is not None


def test_sessao_sem_problemas_grava_direto(env):  # noqa: F811
    db, idx = env
    s = SessaoManual(db, idx, base="B", pedido="B")
    assert s.conferir(rot(piece()).model_dump_json()) == []
    s.aceitar()
    assert db.latest_roteiro() is not None


def test_chats_disponiveis():
    assert CHATS["gemini"][1].startswith("https://gemini.google.com")
    assert CHATS["claude"][1].startswith("https://claude.ai")
    assert CHATS["chatgpt"][1].startswith("https://chatgpt.com")
    assert CHATS["interna"][1] is None  # entra quando a IA interna for instalada


def test_formato_inventado_pelo_chat_do_gemini_e_aproveitado():
    # resposta real do chat do Gemini (Nicole e Osny), resumida: arco_da_serie, cenas sem
    # descricao, trilhas incompletas/inventadas e a busca do Musicbed dentro da trilha
    import json
    cena = {"rel_path": "D\\D - (44).MP4", "start_s": 0.0, "end_s": 7.0, "lembranca": False,
            "usar_som_camera": True, "fala": "Para se tornar um só", "motivo": "Abertura imponente"}
    dados = {"arco_da_serie": "A Âncora e a Aventura", "pecas": [{
        "tipo": "episodio", "numero": 1, "titulo": "O Inesperado", "tema": "t",
        "abertura": cena, "desenvolvimento": [dict(cena, start_s=1, end_s=2, fala=None)],
        "gancho": dict(cena, motivo="Noivo respira fundo"), "gancho_resolve_em": "Ep 2",
        "curva_emocao": [4, 8], "duracao_estimada_s": 360, "misturas": ["flashback"],
        "trilhas": [{"origem": "biblioteca", "path": "biblioteca/piano.wav", "padrao_corte": "1-3"},
                    {"origem": "musicbed", "termos_musicbed": "ambient piano fog"},
                    {"origem": "popular", "path": "popular/marry_you.wav", "exige_licenca": True,
                     "trecho_inicio_s": 45}]}],
        "alertas": ["Atenção ao som ambiente"]}
    r = ler_resposta("```json\n" + json.dumps(dados) + "\n```")
    assert r.arco == "A Âncora e a Aventura" and r.alertas == ["Atenção ao som ambiente"]
    p = r.pecas[0]
    assert p.abertura.descricao == "Abertura imponente" and p.gancho.descricao == "Noivo respira fundo"
    assert p.termos_musicbed == ["ambient piano fog"]
    assert [(t.origem, t.titulo, t.padrao_corte) for t in p.trilhas] == [
        ("biblioteca", "piano", "1-3"), ("popular", "marry_you", "misto")]
    assert p.trilhas[1].exige_licenca and p.trilhas[1].trecho_inicio_s == 45


def test_trilha_inventada_e_barrada_na_conferencia(env):  # noqa: F811
    # a normalização não inventa nada: a trilha que não existe na biblioteca vira problema
    import json
    db, idx = env
    pc = json.loads(rot(piece()).model_dump_json())["pecas"][0]
    pc["trilhas"] = [{"origem": "biblioteca", "path": "biblioteca/piano.wav"}]
    s = SessaoManual(db, idx, base="B", pedido="B")
    probs = s.conferir(json.dumps({"arco": "a", "pecas": [pc], "alertas": []}))
    assert any("piano.wav" in p for p in probs)
