from pathlib import Path
from types import SimpleNamespace

from roteiro_ia.observacoes import (IndiceComPreferidas, Observacoes, nomes_pedidos, texto_prompt,
                                    trilhas_preferidas)
from roteiro_ia.pipeline import ProjectRequest

OBS = Observacoes(perfil="casal discreto, sem piadas", obrigatorio="discurso do pai da noiva",
                  evitar="tio de camisa vermelha", musicas="pop acústico\nPerfect - Ed Sheeran; Trem-Bala",
                  musicas_pasta="M:\\CASAIS\\NICOLE", musicas_link="https://open.spotify.com/playlist/x")


def test_vazia_e_preenchidas():
    assert Observacoes().vazia() and Observacoes().preenchidas() == 0
    assert not OBS.vazia() and OBS.preenchidas() == 6
    assert texto_prompt(Observacoes()) == "" and texto_prompt(None) == ""


def test_texto_do_prompt_com_prioridade():
    t = texto_prompt(OBS, preferidas=3)
    assert t.startswith("OBSERVAÇÕES DO EDITOR PARA ESTE EVENTO — PRIORIDADE MÁXIMA")
    assert "casal discreto, sem piadas" in t and "NÃO PODE FALTAR" in t and "discurso do pai" in t
    assert "EVITAR" in t and "tio de camisa vermelha" in t
    assert "As 3 trilha(s) marcadas com ★" in t and "popular" in t
    assert "spotify" not in t  # a IA não abre links: a playlist vai só para o PDF


def test_nomes_pedidos_e_trilhas_preferidas():
    assert nomes_pedidos(OBS.musicas) == ["pop acustico", "perfect ed sheeran", "trem bala"]
    caminhos = ["M:\\CASAIS\\NICOLE\\qualquer.mp3", "M:\\TRILHAS\\Trem-Bala (ao vivo).mp3",
                "M:\\TRILHAS\\Perfect - Ed Sheeran.mp3", "M:\\TRILHAS\\Outra.mp3",
                "M:\\CASAIS\\NICOLE 2\\nao.mp3"]
    assert trilhas_preferidas(caminhos, OBS) == set(caminhos[:3])
    assert trilhas_preferidas(caminhos, None) == set()


def test_indice_com_preferidas_soma_a_pasta_do_casal():
    t = lambda p: SimpleNamespace(path=p)  # noqa: E731
    base = SimpleNamespace(all=lambda: [t("M:\\TRILHAS\\Outra.mp3")], get=lambda p: "x")
    v = IndiceComPreferidas(base, [t("M:\\CASAIS\\NICOLE\\a.mp3")], OBS)
    assert [x.path for x in v.all()] == ["M:\\TRILHAS\\Outra.mp3", "M:\\CASAIS\\NICOLE\\a.mp3"]
    assert v.preferidas == {"M:\\CASAIS\\NICOLE\\a.mp3"} and v.get("q") == "x"


def test_projeto_guarda_as_observacoes_e_le_projeto_antigo(tmp_path):
    from roteiro_ia.config import Settings
    s = Settings(system_dir=str(tmp_path / "SIS"), protected_roots=[])
    req = ProjectRequest(source_dir=Path("R:/2023/2023-09-09 X"), work_drive="Y:", assignments=[],
                         n_episodios=3, derivados=set(), gemini_mode="gratis", observacoes=OBS)
    f = tmp_path / "projeto.json"
    req.save(f, s)
    assert ProjectRequest.load(f).observacoes == OBS
    d = req.to_dict()
    del d["observacoes"]  # projeto.json de antes desta versão
    assert ProjectRequest.from_dict(d).observacoes == Observacoes()


def test_links_de_musica_do_artlist_viram_nomes():
    texto = ("https://artlist.io/royalty-free-music/song/send-it-instrumental-version/6001704 // "
             "https://artlist.io/royalty-free-music/song/unbreakable-spirit/6001538 /// "
             "https://artlist.io/royalty-free-music/search?includedIds=40 // "
             "https://artlist.io/royalty-free-music/song/im-right-here-piano-version/6001683")
    assert nomes_pedidos(texto) == ["send it instrumental version", "unbreakable spirit",
                                    "im right here piano version"]
    o = Observacoes(musicas=texto)
    caminhos = ["M:\\2026\\11- NOVEMBRO\\04 - Unbreakable Spirit.mp3", "M:\\x\\Outra.mp3"]
    assert trilhas_preferidas(caminhos, o) == {caminhos[0]}


def test_baixadas_sao_preferidas_e_aparecem_no_pdf():
    o = Observacoes(baixadas=["M:\\2026\\11- NOVEMBRO\\05 - Song.mp3"])
    assert not o.vazia() and o.preenchidas() == 0
    assert trilhas_preferidas(["m:\\2026\\11- novembro\\05 - Song.mp3"], o)
    assert ("Músicas baixadas para o evento", "05 - Song.mp3") in o.itens_pdf()
