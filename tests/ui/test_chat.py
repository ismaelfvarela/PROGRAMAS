import json
from pathlib import Path

from PySide6.QtWidgets import QDialog

from roteiro_ia.script.generate import Piece, Roteiro, SceneRef


class _Sessao:
    def __init__(self):
        self.correcoes = 0
        self.ultimo = None
        self.problemas = []
        self.aceito = None

    def texto_inicial(self):
        return "PEDIDO COMPLETO"

    def conferir(self, resposta):
        from roteiro_ia.script.manual import ler_resposta
        self.ultimo = ler_resposta(resposta)
        self.problemas = ["episódio 1: cena inexistente"] if "RUIM" in resposta else []
        return self.problemas

    def pode_corrigir(self):
        return bool(self.problemas) and self.correcoes < 2

    def texto_correcao(self):
        self.correcoes += 1
        return "CORRIJA"

    def aceitar(self, avisos=None):
        self.aceito = avisos
        return self.ultimo


class _Pipe:
    def __init__(self):
        self.sessao = _Sessao()
        self.pedidos = []

    def sessao_roteiro_manual(self, ajuste=None, compact=False):
        self.pedidos.append((ajuste, compact))
        return self.sessao


def _json(arco="a"):
    cena = SceneRef(rel_path="A\\a.MP4", start_s=0, end_s=5, descricao="d", fala=None, motivo=None)
    pc = Piece(tipo="episodio", numero=1, titulo="T", tema="t", abertura=cena, desenvolvimento=[],
               gancho=None, gancho_resolve_em=None, curva_emocao=[5], duracao_estimada_s=5,
               misturas=[], trilhas=[], termos_musicbed=[])
    return Roteiro(arco=arco, pecas=[pc], alertas=[]).model_dump_json()


def test_janela_do_chat_do_pedido_ao_uso(qtbot, tmp_path, monkeypatch):
    from roteiro_ia.ui import chat as mod
    abertos, mostrados = [], []
    monkeypatch.setattr(mod, "_abrir_url", abertos.append)
    monkeypatch.setattr(mod, "_mostrar_no_explorador", mostrados.append)
    pipe = _Pipe()
    dlg = mod.RoteiroChatDialog(pipe, tmp_path / "ANALISE", roteiro_existe=True)
    qtbot.addWidget(dlg)
    assert not dlg.btn_conferir.isEnabled() and not dlg.btn_usar.isEnabled()

    assert not dlg.chk_compacto.isChecked()  # Gemini aguenta o pedido inteiro
    dlg.btn_pedido.click()
    arq = tmp_path / "ANALISE" / "PEDIDO DO ROTEIRO.txt"
    assert arq.read_text(encoding="utf-8") == "PEDIDO COMPLETO"
    assert abertos == ["https://gemini.google.com/app"] and mostrados == [arq]
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == "PEDIDO COMPLETO"

    dlg.resposta.setPlainText("não é json")
    dlg.btn_conferir.click()
    assert "não tem um JSON" in dlg.banner_erro.text() and not dlg.btn_usar.isEnabled()

    dlg.resposta.setPlainText(_json("RUIM"))
    dlg.btn_conferir.click()
    assert "1 problema" in dlg.banner_erro.text() and dlg.btn_correcao.isEnabled()
    dlg.btn_correcao.click()
    assert (tmp_path / "ANALISE" / "CORREÇÃO DO ROTEIRO 1.txt").read_text(encoding="utf-8") == "CORRIJA"
    assert dlg.resposta.toPlainText() == ""

    dlg.resposta.setPlainText("```json\n" + _json() + "\n```")
    dlg.btn_conferir.click()
    assert "tudo certo" in dlg.banner_ok.text()
    dlg.btn_usar.click()
    assert dlg.result() == QDialog.Accepted and pipe.sessao.aceito == ["Roteiro feito pelo chat (Gemini)."]


def test_outro_chat_e_ajuste(qtbot, tmp_path, monkeypatch):
    from roteiro_ia.ui import chat as mod
    abertos = []
    monkeypatch.setattr(mod, "_abrir_url", abertos.append)
    monkeypatch.setattr(mod, "_mostrar_no_explorador", lambda a: None)
    pipe = _Pipe()
    dlg = mod.RoteiroChatDialog(pipe, tmp_path, roteiro_existe=True)
    qtbot.addWidget(dlg)
    dlg.combo.setCurrentIndex(dlg.combo.findData("claude"))
    dlg.ajuste.setText("mais votos no episódio 2")
    dlg.btn_pedido.click()
    assert abertos == ["https://claude.ai/new"]
    assert pipe.pedidos == [("mais votos no episódio 2", True)]  # Claude: versão compacta
    interna = dlg.combo.findData("interna")
    assert not dlg.combo.model().item(interna).isEnabled()
