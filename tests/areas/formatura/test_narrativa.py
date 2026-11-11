from roteiro_ia.areas.formatura.costura import montar_narrativa
from roteiro_ia.areas.formatura.acabamento import batidas_permitidas
from roteiro_ia.areas.formatura.narrativa import (BlocoEscolhido, Frase, Pedaco, RespostaNarrativa,
                                                  TrechoEscolhido, alinhar, corrigir_tempos,
                                                  escolher_narrativa, frases_do_video, montar_blocos,
                                                  pedacos, tirar_tropecos)
from roteiro_ia.models import TrackInfo, Word
from roteiro_ia.script.generate import Piece, SceneRef


def _ws(txt, t0=10.0, passo=0.4, pausas=None):
    out, t = [], t0
    for i, w in enumerate(txt.split()):
        t += (pausas or {}).get(i, 0.0)
        out.append(Word(text=w, start_s=t, end_s=t + passo - 0.1))
        t += passo
    return out


def test_frases_pela_pontuacao_e_tempo_esticado_corrigido():
    ws = _ws("Oi, eu sou a Sabrina. Eu faço costura aqui.")
    ws[6] = ws[6].model_copy(update={"start_s": ws[5].end_s, "end_s": ws[5].end_s + 9.0})
    fr = frases_do_video("A/v.mp4", ws, 1)
    assert [f.texto for f in fr][0] == "Oi, eu sou a Sabrina."
    assert fr[1].id == 2 and fr[-1].texto.endswith("aqui.")  # o silêncio longo também separa
    assert corrigir_tempos(ws)[6].end_s - corrigir_tempos(ws)[6].start_s <= 0.5 + 1e-6


def test_tira_repeticao_gaguejo_muleta_e_respiro():
    ws = _ws("eu eu apren aprendi hã muito aqui", pausas={6: 0.8})  # pausa antes de "aqui"
    f = Frase(1, "A/v.mp4", ws, 0.0, None)
    kept, faltou = alinhar(f, "eu eu apren aprendi hã muito aqui")
    assert faltou == 0
    kept = tirar_tropecos(f, kept)
    assert [ws[i].text for i in kept] == ["eu", "aprendi", "muito", "aqui"]
    pcs = pedacos(f, kept)
    # "eu" | "aprendi" | "muito" | "aqui": cada pulo vira um pedaço; o respiro antes de "aqui" sai
    assert len(pcs) == 4
    assert pcs[-1].in_s > ws[5].end_s + 0.3 and all(p.dur > 0 for p in pcs)
    assert all(b.in_s >= a.out_s - 1e-6 for a, b in zip(pcs, pcs[1:]))


def test_resumo_do_gemini_vira_pedacos_e_ignora_frase_repetida():
    f1 = Frase(1, "A/a.mp4", _ws("o curso foi muito bom mesmo"), 0.0, None)
    f2 = Frase(2, "A/b.mp4", _ws("e eu aprendi a costurar", t0=40), 0.0, None)
    r = RespostaNarrativa(blocos=[BlocoEscolhido(trechos=[
        TrechoEscolhido(frase=1, texto="o curso foi muito bom"),
        TrechoEscolhido(frase=2, texto="eu aprendi a costurar"),
        TrechoEscolhido(frase=1, texto="o curso"),  # repetida: sai
        TrechoEscolhido(frase=99, texto="nada")])])
    blocos, alertas = montar_blocos(r, [f1, f2])
    assert len(blocos) == 1 and len(blocos[0]) == 2
    assert blocos[0][0][-1].out_s < f1.palavras[5].start_s  # "mesmo" ficou de fora
    assert blocos[0][1][0].in_s > f2.palavras[0].end_s - 0.05  # "e" ficou de fora


class _Cliente:
    def __init__(self, resp=None, erro=None):
        self.resp, self.erro, self.prompt = resp, erro, None

    def generate_json(self, model, parts, schema, prompt):
        self.prompt = prompt
        if self.erro:
            raise self.erro
        return self.resp


def test_sem_gemini_volta_vazio_com_aviso():
    f = Frase(1, "A/a.mp4", _ws("o curso foi bom"), 0.0, None)
    blocos, alertas = escolher_narrativa(_Cliente(erro=RuntimeError("x")), "m", [f], {}, "Oficina",
                                         240)
    assert blocos == [] and alertas
    c = _Cliente(RespostaNarrativa(blocos=[]))
    escolher_narrativa(c, "m", [f], {"A/a.mp4": "aluna de óculos"}, "Oficina", 240, "mais curto")
    assert "[1] a.mp4" in c.prompt and "aluna de óculos" in c.prompt and "mais curto" in c.prompt


def _track(n=600, passo=0.5):
    beats = [i * passo for i in range(n)]
    return TrackInfo(path="m.mp3", bpm=60 / passo, beats_s=beats, downbeats_s=beats[::4],
                     energy=[], duration_s=n * passo, has_vocals=False, perfil="intensa", mtime=1.0)


def _ref(rel, a, b, fala=None):
    return SceneRef(rel_path=rel, start_s=a, end_s=b, descricao="d", fala=fala, motivo=None,
                    lembranca=True)


def test_montagem_com_voz_costurada_broll_e_rosto_em_sincronia():
    cenas = [_ref(f"A/b{i}.mp4", 0, 3) for i in range(12)]
    cenas.insert(2, _ref("A/aluno1.mp4", 5, 9, fala="x"))
    p = Piece(tipo="episodio", numero=1, titulo="O", tema="t", abertura=cenas[0],
              desenvolvimento=cenas[1:], gancho=None, gancho_resolve_em=None, curva_emocao=[5],
              duracao_estimada_s=40, misturas=[], trilhas=[], termos_musicbed=[])
    blocos = [[[Pedaco("A/aluno1.mp4", 10.0, 13.0), Pedaco("A/aluno1.mp4", 14.0, 16.5)],
               [Pedaco("A/aluno2.mp4", 3.0, 7.0)]],
              [[Pedaco("A/aluno1.mp4", 30.0, 34.0)]]]
    dur = {**{f"A/b{i}.mp4": 30.0 for i in range(12)}, "A/aluno1.mp4": 60.0, "A/aluno2.mp4": 60.0}
    t = _track()
    alertas, vozes = montar_narrativa(p, t, 0.0, "1-3", {}.get, dur, (30, 1), blocos, alvo_s=40)
    cenas = [p.abertura, *p.desenvolvimento]
    assert len(vozes) == 4 and vozes[0].inicio_s >= 4.0 - 1e-6
    # a voz não se sobrepõe e segue a ordem da narrativa
    for a, b in zip(vozes, vozes[1:]):
        assert b.inicio_s >= a.inicio_s + a.dur_s - 1e-6
    total = sum(c.end_s - c.start_s for c in cenas)
    assert total >= 40 - 1.0 and total >= vozes[-1].inicio_s + vozes[-1].dur_s + 4 - 1.0
    # cortes no compasso
    perm = batidas_permitidas(t, 0.0, "1-3")
    acum = 0.0
    for c in cenas[:-1]:
        acum += c.end_s - c.start_s
        assert min(abs(acum - b) for b in perm) < 1 / 30 + 1e-6
    # rostos em sincronia com a voz; o resto é cobertura (nenhuma cena de fala do roteiro)
    acum = 0.0
    rostos = 0
    for c in cenas:
        if c.rel_path.startswith("A/aluno"):
            rostos += 1
            v = next(v for v in vozes if v.rel_path == c.rel_path
                     and v.in_s - 0.25 <= c.start_s <= v.in_s + v.dur_s)
            assert abs((c.start_s - v.in_s) - (acum - v.inicio_s)) < 1 / 30 + 1e-6
        acum += c.end_s - c.start_s
    assert 2 <= rostos <= 3
    assert not any(c.rel_path == "A/aluno1.mp4" and c.start_s == 5 for c in cenas)
