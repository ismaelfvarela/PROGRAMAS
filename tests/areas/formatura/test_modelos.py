from pathlib import Path

from roteiro_ia.areas.formatura.ajustes import (AjustesFormatura, ModeloAno, carregar_ajustes,
                                                modelos_do_ano, salvar_ajustes)
from roteiro_ia.areas.formatura.modelos import estudar_modelos
from roteiro_ia.config import Settings
from roteiro_ia.gemini import style


def _s(tmp_path):
    return Settings(system_dir=str(tmp_path / "s"), protected_roots=[])


def test_modelos_por_ano(tmp_path):
    s = _s(tmp_path)
    assert modelos_do_ano(s, 2026) is None
    salvar_ajustes(s, AjustesFormatura(logo_produtora="x", modelos={
        "2025": ModeloAno(pasta="A"), "2027": ModeloAno(pasta="C", mogrt="c.mogrt")}))
    assert carregar_ajustes(s).logo_produtora == "x"
    assert modelos_do_ano(s, 2027).mogrt == "c.mogrt"
    assert modelos_do_ano(s, 2026).pasta == "A"  # o mais recente que não passa do ano
    assert modelos_do_ano(s, 2024) is None


class _C:
    def __init__(self, falhar=()):
        self.uploads, self.prompts, self.falhar = [], [], set(falhar)

    def pick_default_models(self):
        return ("m", "m")

    def upload(self, path):
        self.uploads.append(Path(path).name)
        if Path(path).name in self.falhar:
            raise RuntimeError("falhou")
        return f"file:{path}"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.prompts.append(prompt)
        if schema is style.VideoStyleNotes:
            return style.VideoStyleNotes(url="", tipo="episodio", duracao_s=200, ritmo_corte_s=2,
                                         abertura="cartela", gancho="logo", uso_falas="",
                                         trilha="pop", cor="", observacoes="")
        return style.StyleProfile(fontes=[], duracao_media_episodio_s=200, ritmo_corte_medio_s=2,
                                  padroes_abertura=["cartela"], padroes_gancho=[], uso_falas="",
                                  trilhas="pop", cor="", estrutura_teaser_trailer="", resumo="ok")


def test_estudo_dos_modelos(tmp_path):
    import roteiro_ia.areas.formatura  # noqa: F401 (registra os prompts)
    s = _s(tmp_path)
    pasta = tmp_path / "MODELOS 2026"
    pasta.mkdir()
    for n in ("abertura.mp4", "oficina.mov", "leia.txt"):
        (pasta / n).write_bytes(b"x")
    c = _C()
    prof = estudar_modelos(c, s, 2026, pasta)
    assert prof.resumo == "ok" and sorted(c.uploads) == ["abertura.mp4", "oficina.mov"]
    assert (Path(s.system_dir) / "perfil_estilo_formatura_2026.json").is_file()
    c2 = _C()
    assert estudar_modelos(c2, s, 2026, pasta).resumo == "ok" and c2.uploads == [] and c2.prompts == []
    (pasta / "oficina.mov").write_bytes(b"outro conteudo")
    c3 = _C()
    estudar_modelos(c3, s, 2026, pasta)
    assert c3.uploads == ["oficina.mov"] and len(c3.prompts) == 2  # 1 vídeo + o perfil


def test_estudo_com_falha_e_pasta_vazia(tmp_path):
    import roteiro_ia.areas.formatura  # noqa: F401
    s = _s(tmp_path)
    pasta = tmp_path / "M"
    pasta.mkdir()
    assert estudar_modelos(_C(), s, 2026, pasta) is None
    for n in ("a.mp4", "b.mp4"):
        (pasta / n).write_bytes(b"x")
    assert estudar_modelos(_C(falhar={"a.mp4"}), s, 2026, pasta).resumo == "ok"
    assert estudar_modelos(_C(falhar={"a.mp4", "b.mp4"}), s, 2027, tmp_path / "nada") is None


def test_secao_de_modelos_na_janela(qtbot, tmp_path):
    from roteiro_ia.areas.formatura.ui_cadastro import DialogoCadastro
    s = _s(tmp_path)
    d = DialogoCadastro(s)
    qtbot.addWidget(d)
    d.definir_modelo("2026", pasta="C:\\MODELOS 2026", mogrt="C:\\cartela 2026.mogrt")
    d.definir_modelo("2027", pasta="C:\\MODELOS 2027")
    assert d.tabela_modelos.rowCount() == 2
    assert modelos_do_ano(s, 2026).mogrt == "C:\\cartela 2026.mogrt"
    d.remover_modelo("2027")
    assert modelos_do_ano(s, 2027).pasta == "C:\\MODELOS 2026"
    assert carregar_ajustes(s).logo_produtora is None
