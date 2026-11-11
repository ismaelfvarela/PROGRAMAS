import numpy as np

from roteiro_ia.areas.formatura.acabamento import (_janela, acabar_peca, batidas_permitidas,
                                                   custo_janela, limpa, melhor_janela,
                                                   trecho_da_fala)
from roteiro_ia.areas.formatura.movimento import Medidas
from roteiro_ia.models import TrackInfo, Word
from roteiro_ia.script.generate import Piece, SceneRef

FPS = 10.0


def _med(seg, tremido=(), mexe=(), escuro=()):
    """`seg` segundos de câmera parada; faixas (a, b) em segundos com tremor, panorâmica
    rápida ou escuro."""
    n = int(seg * FPS)
    b, nt = np.full(n, 120.0), np.full(n, 20.0)
    d, tr = np.full(n, 0.1), np.full(n, 0.1)
    for a, z in tremido:
        d[int(a * FPS):int(z * FPS)] = 2.0
        tr[int(a * FPS):int(z * FPS)] = 2.0
    for a, z in mexe:
        d[int(a * FPS):int(z * FPS)] = 9.0
    for a, z in escuro:
        b[int(a * FPS):int(z * FPS)] = 10.0
    return Medidas(FPS, b, nt, d, tr)


def _track(n=400, passo=0.5):
    beats = [i * passo for i in range(n)]
    return TrackInfo(path="m.mp3", bpm=60 / passo, beats_s=beats, downbeats_s=beats[::4],
                     energy=[], duration_s=n * passo, has_vocals=False, perfil="intensa", mtime=1.0)


def _ref(rel, a, b, fala=None):
    return SceneRef(rel_path=rel, start_s=a, end_s=b, descricao="d", fala=fala, motivo=None,
                    lembranca=True)


def _peca(cenas):
    return Piece(tipo="episodio", numero=1, titulo="O", tema="t", abertura=cenas[0],
                 desenvolvimento=cenas[1:], gancho=None, gancho_resolve_em=None, curva_emocao=[5],
                 duracao_estimada_s=20, misturas=[], trilhas=[], termos_musicbed=[])


def _cortes(p):
    out, acum = [], 0.0
    for c in [p.abertura, *p.desenvolvimento]:
        acum += c.end_s - c.start_s
        out.append(acum)
    return out


def test_custo_maior_com_tremor_e_movimento_na_borda():
    m = _med(20, tremido=[(5, 8)], mexe=[(12, 12.4)])
    assert custo_janela(m, 5.0, 2.0) > custo_janela(m, 1.0, 2.0)
    assert custo_janela(m, 12.0, 2.0) > custo_janela(m, 15.0, 2.0)
    assert limpa(m, 1.0, 2.0) and not limpa(m, 5.0, 2.0) and not limpa(m, 12.0, 2.0)


def test_melhor_janela_foge_do_tremor_e_do_escuro():
    m = _med(30, tremido=[(4.5, 6.5)], escuro=[(10, 12)])
    ini = melhor_janela(m, ref_ini=5.0, dur=2.0, lim0=0.0, lim1=30.0)
    assert limpa(m, ini, 2.0)
    assert abs(ini - 5.0) <= 3.0


def test_procura_mais_longe_quando_perto_esta_ruim():
    m = _med(40, tremido=[(0, 12.5)])
    longe = _janela(m, 5.0, 2.0, 40.0)
    assert longe >= 12.5 and limpa(m, longe, 2.0)


def test_batidas_so_no_compasso():
    t = TrackInfo(path="m.mp3", bpm=120, beats_s=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
                  downbeats_s=[0.0, 2.0], energy=[], duration_s=10, has_vocals=False,
                  perfil="calma", mtime=1.0)
    assert batidas_permitidas(t, 0.0, "1-3") == [0.0, 1.0, 2.0, 3.0]
    assert batidas_permitidas(t, 0.0, "2-4") == [0.5, 1.5, 2.5, 3.5]
    assert batidas_permitidas(t, 0.0, "1") == [0.0, 2.0]
    assert batidas_permitidas(t, 0.0, "misto") == [0.0, 1.0, 2.0, 3.0]  # nunca toda batida
    assert batidas_permitidas(t, 1.0, "1-3") == [0.0, 1.0, 2.0]


def test_cenas_cortam_no_compasso_e_desligam_lembranca():
    t = _track()
    p = _peca([_ref("A\\a.mp4", 1.0, 3.3), _ref("A\\b.mp4", 0.0, 2.2), _ref("A\\c.mp4", 10.0, 11.4)])
    med = {"A\\a.mp4": _med(30, tremido=[(0.5, 3.5)]), "A\\b.mp4": _med(20), "A\\c.mp4": _med(30)}
    dur = {"A\\a.mp4": 30.0, "A\\b.mp4": 20.0, "A\\c.mp4": 30.0}
    alertas, vozes = acabar_peca(p, t, 0.0, "1-3", med.get, dur, rate=(30000, 1001))
    perm = batidas_permitidas(t, 0.0, "1-3")
    for x in _cortes(p):
        assert min(abs(x - b) for b in perm) < 1 / 29.97 + 1e-6
    cenas = [p.abertura, *p.desenvolvimento]
    assert all(not c.lembranca for c in cenas) and vozes == []
    assert limpa(med["A\\a.mp4"], p.abertura.start_s, p.abertura.end_s - p.abertura.start_s)
    assert all(0 <= c.start_s < c.end_s <= dur[c.rel_path] for c in cenas)


def test_video_todo_tremido_e_trocado_pelo_vizinho():
    t = _track()
    p = _peca([_ref("A\\C0010.mp4", 2.0, 4.0), _ref("A\\C0020.mp4", 0.0, 2.0)])
    med = {"A\\C0010.mp4": _med(10, tremido=[(0, 10)]), "A\\C0011.mp4": _med(10),
           "A\\C0020.mp4": _med(10)}
    dur = {k: 10.0 for k in med}
    alertas, _ = acabar_peca(p, t, 0.0, "1-3", med.get, dur, rate=(30, 1),
                             vizinhos=lambda r: ["A\\C0011.mp4"] if r == "A\\C0010.mp4" else [])
    assert p.abertura.rel_path == "A\\C0011.mp4"
    assert any("C0011" in a for a in alertas)


def test_plano_sem_fala_longo_e_encurtado():
    p = _peca([_ref("A\\a.mp4", 0.0, 15.0), _ref("A\\b.mp4", 0.0, 3.0)])
    acabar_peca(p, _track(), 0.0, "1-3", {}.get, {"A\\a.mp4": 60.0, "A\\b.mp4": 60.0}, rate=(30, 1))
    assert p.abertura.end_s - p.abertura.start_s <= 5.0 + 1e-6


def test_trecho_da_fala_pega_a_frase_inteira():
    ws = [Word(text=f"p{i}", start_s=10 + i * 0.4, end_s=10.3 + i * 0.4) for i in range(10)]
    ws += [Word(text="outra", start_s=20.0, end_s=20.5)]
    a0, a1 = trecho_da_fala(ws, 11.0, 12.0, 60.0)  # o roteiro cortou no meio da frase
    assert abs(a0 - (10 - 0.15)) < 1e-6 and abs(a1 - (13.9 + 0.3)) < 1e-6


def test_fala_longa_aluno_no_comeco_e_no_fim_e_voz_por_baixo():
    t = _track()
    ws = [Word(text=f"p{i}", start_s=20 + i * 0.4, end_s=20.3 + i * 0.4) for i in range(25)]  # ~10 s
    fala = _ref("A\\aluno.mp4", 20.0, 30.0, fala="eu aprendi muito aqui")
    p = _peca([_ref("A\\abre.mp4", 0, 2), fala, _ref("A\\b1.mp4", 0, 3), _ref("A\\b2.mp4", 0, 3),
               _ref("A\\b3.mp4", 0, 3), _ref("A\\fim.mp4", 0, 2)])
    dur = {r: 60.0 for r in ["A\\abre.mp4", "A\\aluno.mp4", "A\\b1.mp4", "A\\b2.mp4", "A\\b3.mp4",
                             "A\\fim.mp4"]}
    _, vozes = acabar_peca(p, t, 0.0, "1-3", {}.get, dur, rate=(30, 1),
                           palavras=lambda r: ws if r == "A\\aluno.mp4" else [])
    cenas = [p.abertura, *p.desenvolvimento]
    nomes = [c.rel_path for c in cenas]
    i = nomes.index("A\\aluno.mp4")
    j = len(nomes) - 1 - nomes[::-1].index("A\\aluno.mp4")
    assert j > i + 1 and all(n.startswith("A\\b") for n in nomes[i + 1:j])  # cobertura no meio
    assert len(vozes) == 1
    v = vozes[0]
    inicio_cena = sum(c.end_s - c.start_s for c in cenas[:i])
    assert abs(v.inicio_s - inicio_cena) < 1e-6 and abs(v.in_s - cenas[i].start_s) < 1e-6
    # o rabo do aluno continua sincronizado com a voz e termina depois da fala
    inicio_rabo = sum(c.end_s - c.start_s for c in cenas[:j])
    assert abs(cenas[j].start_s - (v.in_s + inicio_rabo - v.inicio_s)) < 1e-6
    assert inicio_rabo + (cenas[j].end_s - cenas[j].start_s) >= v.inicio_s + v.dur_s - 0.06
    perm = batidas_permitidas(t, 0.0, "1-3")
    for x in _cortes(p):
        assert min(abs(x - b) for b in perm) < 1 / 30 + 1e-6, _cortes(p)


def test_duas_falas_do_mesmo_video_nao_repetem_nem_voltam():
    ws = [Word(text=f"p{i}", start_s=10 + i * 0.4, end_s=10.3 + i * 0.4) for i in range(60)]  # 10–34 s
    a = _ref("A\\aluno.mp4", 12.0, 20.0, fala="parte 1")
    b = _ref("A\\aluno.mp4", 18.0, 26.0, fala="parte 2")  # o roteiro sobrepôs as falas
    p = _peca([_ref("A\\abre.mp4", 0, 2), a, b])
    _, vozes = acabar_peca(p, _track(), 0.0, "1-3", {}.get, {"A\\abre.mp4": 30, "A\\aluno.mp4": 60},
                           rate=(30, 1), palavras=lambda r: ws if r == "A\\aluno.mp4" else [])
    assert len(vozes) == 2
    v1, v2 = vozes
    assert v2.in_s >= v1.in_s + v1.dur_s - 1e-6  # a segunda fala começa depois da primeira
    aluno = [c for c in [p.abertura, *p.desenvolvimento] if c.rel_path == "A\\aluno.mp4"]
    for x, y in zip(aluno, aluno[1:]):
        assert y.start_s >= x.end_s - 1e-6  # a imagem do aluno nunca volta no tempo


def test_cobertura_extra_quando_o_roteiro_nao_tem():
    ws = [Word(text=f"p{i}", start_s=20 + i * 0.4, end_s=20.3 + i * 0.4) for i in range(25)]
    p = _peca([_ref("A\\abre.mp4", 0, 2), _ref("A\\C0050.mp4", 20.0, 30.0, fala="eu aprendi")])
    extras = [_ref("A\\C0010.mp4", 0, 4), _ref("A\\C0049.mp4", 0, 4), _ref("A\\C0051.mp4", 0, 4)]
    for e in extras:
        e.lembranca = False
    dur = {r: 60.0 for r in ["A\\abre.mp4", "A\\C0050.mp4", "A\\C0010.mp4", "A\\C0049.mp4",
                             "A\\C0051.mp4"]}
    acabar_peca(p, _track(), 0.0, "1-3", {}.get, dur, rate=(30, 1),
                palavras=lambda r: ws if r == "A\\C0050.mp4" else [], extras=extras)
    nomes = [c.rel_path for c in [p.abertura, *p.desenvolvimento]]
    assert nomes[1] == "A\\C0050.mp4" and nomes[-1] == "A\\C0050.mp4"
    meio = nomes[2:-1]
    assert meio and set(meio) <= {"A\\C0049.mp4", "A\\C0051.mp4"}  # vizinhos de gravação primeiro
