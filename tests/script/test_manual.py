import pytest

from roteiro_ia.script.manual import (CHATS, RespostaInvalida, SessaoManual, instrucao_json,
                                      ler_resposta, texto_para_o_chat)
from tests.script.test_generate import env, piece, ref, rot  # noqa: F401 - fixture e ajudantes


def test_pedido_leva_o_formato_json():
    t = texto_para_o_chat("PEDIDO X")
    assert t.startswith("PEDIDO X") and "SOMENTE com um único JSON" in t and '"pecas"' in t
    assert "termos_musicbed" in instrucao_json()


def test_le_resposta_crua_com_cerca_e_com_texto_em_volta():
    j = rot(piece()).model_dump_json()
    assert ler_resposta(j).pecas[0].numero == 1
    assert ler_resposta(f"Claro! Aqui está:\n```json\n{j}\n```\nBom trabalho.").arco == "arco"
    assert ler_resposta(f"Segue o roteiro: {j} — qualquer coisa me avise").arco == "arco"


@pytest.mark.parametrize("texto,trecho", [
    ("", "Cole a resposta"),
    ("não sei fazer isso", "não tem um JSON"),
    ('{"arco": "a", "pecas": [', "o chat cortou"),
    ('{"arco": "a", "pecas": [}', "incompleto ou quebrado"),
    ('{"arco": "a"}', "formato do roteiro"),
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
    assert c1.startswith("BASE") and "NAO_EXISTE" in c1 and "SOMENTE com um único JSON" in c1
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
