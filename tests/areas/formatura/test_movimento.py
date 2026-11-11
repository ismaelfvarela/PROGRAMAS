import numpy as np

from roteiro_ia.areas.formatura.movimento import Medidas, de_quadros, deslocamentos


def _cena(seed=1, h=90, w=160):
    rng = np.random.default_rng(seed)
    base = rng.random((h + 40, w + 40)).astype(np.float32) * 255
    # borra um pouco para parecer imagem (correlação de fase com textura)
    k = np.ones(3) / 3
    base = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, base)
    return base


def _quadro(base, x, y, h=90, w=160):
    return base[20 + y:20 + y + h, 20 + x:20 + x + w].copy()


def test_deslocamento_mede_o_movimento_da_camera():
    base = _cena()
    qs = [_quadro(base, 0, 0), _quadro(base, 3, 0), _quadro(base, 3, 2)]
    dx, dy = deslocamentos(qs)
    assert abs(abs(dx[1]) - 3) < 0.6 and abs(dy[1]) < 0.6
    assert abs(dx[2]) < 0.6 and abs(abs(dy[2]) - 2) < 0.6


def test_tremor_alto_na_mao_e_baixo_na_panoramica():
    base = _cena(2)
    pan = [_quadro(base, i, 0) for i in range(15)]  # panorâmica lisa
    rng = np.random.default_rng(5)
    mao = [_quadro(base, 7 + int(rng.integers(-3, 4)), 5 + int(rng.integers(-3, 4))) for _ in range(15)]
    m_pan, m_mao = de_quadros(pan), de_quadros(mao)
    assert m_pan.tremor[2:-2].mean() < 0.5
    assert m_mao.tremor[2:-2].mean() > 1.0


def test_cache_por_versao():
    m = de_quadros([_quadro(_cena(), 0, 0)] * 3)
    d = m.para_dict()
    assert Medidas.de_dict(d).fps == m.fps
    assert Medidas.de_dict({"brilho": [1]}) is None  # cache antigo: mede de novo
