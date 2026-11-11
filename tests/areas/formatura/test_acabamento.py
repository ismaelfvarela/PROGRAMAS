import numpy as np

from roteiro_ia.areas.formatura.acabamento import (acabar_peca, batidas_permitidas, custo_janela,
                                                   melhor_janela)
from roteiro_ia.areas.formatura.colacao.defeitos import Amostras
from roteiro_ia.models import TrackInfo
from roteiro_ia.script.generate import Piece, SceneRef

FPS = 4.0


def _am(n, mexe=(), ruim=()):
    """n amostras estáveis; `mexe` = faixas (a, b) em amostras com câmera se mexendo;
    `ruim` = faixas escuras."""
    b, nit, d = np.full(n, 120.0), np.full(n, 20.0), np.full(n, 2.0)
    for a, z in mexe:
        d[a:z] = 25.0
    for a, z in ruim:
        b[a:z] = 10.0
    return Amostras(b, nit, d)


def test_custo_maior_com_movimento_na_borda():
    a = _am(80, mexe=[(20, 24)])
    assert custo_janela(a, FPS, 5.0, 2.0) > custo_janela(a, FPS, 10.0, 2.0)


def test_melhor_janela_foge_do_movimento_e_do_escuro():
    a = _am(120, mexe=[(18, 26)], ruim=[(40, 48)])
    ini = melhor_janela(a, FPS, ref_ini=5.0, dur=2.0, lim0=0.0, lim1=30.0)
    assert not (4.0 < ini + 2.0 and ini < 6.5)      # não pega o movimento (4,5–6,5 s)
    assert not (9.75 < ini + 2.0 and ini < 12.25)   # nem o escuro (10–12 s)
    assert abs(ini - 5.0) <= 3.0                    # e fica perto do que o roteiro pediu


def test_batidas_1_3_e_2_4():
    t = TrackInfo(path="m.mp3", bpm=120, beats_s=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
                  downbeats_s=[0.0, 2.0], energy=[], duration_s=10, has_vocals=False,
                  perfil="calma", mtime=1.0)
    assert batidas_permitidas(t, 0.0, "1-3") == [0.0, 1.0, 2.0, 3.0]
    assert batidas_permitidas(t, 0.0, "2-4") == [0.5, 1.5, 2.5, 3.5]
    assert batidas_permitidas(t, 0.5, "misto") == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]


def _ref(rel, a, b):
    return SceneRef(rel_path=rel, start_s=a, end_s=b, descricao="d", fala=None, motivo=None,
                    lembranca=True)


def test_acabar_peca_corta_na_batida_e_desliga_lembranca():
    beats = [i * 0.5 for i in range(200)]
    t = TrackInfo(path="m.mp3", bpm=120, beats_s=beats, downbeats_s=beats[::4], energy=[],
                  duration_s=100, has_vocals=False, perfil="intensa", mtime=1.0)
    p = Piece(tipo="episodio", numero=1, titulo="O", tema="t", abertura=_ref("A\\a.mp4", 1.0, 3.3),
              desenvolvimento=[_ref("A\\b.mp4", 0.0, 2.2), _ref("A\\a.mp4", 10.0, 11.4)],
              gancho=None, gancho_resolve_em=None, curva_emocao=[5], duracao_estimada_s=7,
              misturas=[], trilhas=[], termos_musicbed=[])
    medidas = {"A\\a.mp4": _am(120, mexe=[(4, 14)]), "A\\b.mp4": _am(80)}
    duracoes = {"A\\a.mp4": 30.0, "A\\b.mp4": 20.0}
    alertas = acabar_peca(p, t, 0.0, "misto", medidas, duracoes, rate=(30000, 1001))
    cenas = [p.abertura, *p.desenvolvimento]
    cortes, acum = [], 0.0
    for c in cenas:
        acum += c.end_s - c.start_s
        cortes.append(acum)
    for x in cortes:  # cada corte cai numa batida (até 1 quadro)
        assert min(abs(x - b) for b in beats) < 1 / 29.97 + 1e-6, cortes
    assert all(not c.lembranca for c in cenas)
    assert not (1.0 < p.abertura.end_s and p.abertura.start_s < 3.5)  # fugiu do movimento
    assert all(0 <= c.start_s < c.end_s <= duracoes[c.rel_path] for c in cenas)
    assert isinstance(alertas, list)
