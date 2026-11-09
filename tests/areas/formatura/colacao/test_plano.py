from roteiro_ia.areas.formatura.colacao.defeitos import Defeito
from roteiro_ia.areas.formatura.colacao.frias import BancoFrias, ItemFria
from roteiro_ia.areas.formatura.colacao.partes import ParteNomeada
from roteiro_ia.areas.formatura.colacao.plano import assunto, montar_plano

PARTES = [ParteNomeada(codigo="abertura", nome="Abertura", inicio_s=0),
          ParteNomeada(codigo="hino", nome="Hino Nacional", inicio_s=100)]


def _frias():
    return BancoFrias([ItemFria(midia_rel="FRIAS\\a.mp4", inicio_s=0, fim_s=30,
                                momento="decoração", qualidade=9)])


def _d(a, b, tipo="chicote"):
    return Defeito(inicio_s=a, fim_s=b, tipo=tipo)


def test_partes_e_cortes():
    pl = montar_plano(PARTES, 200, [], [(40, 50), (150, 152)], [], _frias())
    p1, p2 = pl.partes
    assert (p1.numero, p1.nome, p1.inicio_s, p1.fim_s) == (1, "Abertura", 0, 100)
    assert p1.cortes == [(40.5, 49.5)] and p1.trechos == [(0, 40.5), (49.5, 100)]
    assert (p2.inicio_s, p2.fim_s) == (100, 200)
    assert p2.cortes == [(150.5, 151.5)]


def test_troca_por_iso():
    pl = montar_plano(PARTES, 200, [_d(10, 12)], [], [("CAM A\\a.mp4", 0, 100)], _frias())
    t = pl.partes[0].trocas
    assert [(x.inicio_s, x.fim_s, x.motivo, x.fonte) for x in t] == [(10, 12, "chicote", "iso:CAM A\\a.mp4")]


def test_iso_cobre_metade_resto_fria():
    pl = montar_plano(PARTES, 200, [_d(110, 120, "escuro")], [], [("CAM A\\a.mp4", 100, 115)], _frias())
    t = pl.partes[1].trocas
    assert [(x.inicio_s, x.fim_s, x.fonte) for x in t] == [
        (110, 115, "iso:CAM A\\a.mp4"), (115, 120, "fria:FRIAS\\a.mp4@0.000-5.000")]


def test_maior_sobreposicao_ganha():
    isos = [("CAM A\\a.mp4", 0, 11), ("CAM B\\b.mp4", 9, 100)]
    pl = montar_plano(PARTES, 200, [_d(10, 14)], [], isos, _frias())
    assert [(x.inicio_s, x.fim_s, x.fonte) for x in pl.partes[0].trocas] == [(10, 14, "iso:CAM B\\b.mp4")]


def test_sem_cobertura():
    pl = montar_plano(PARTES, 200, [_d(10, 12, "desfocado")], [], [], BancoFrias([]))
    assert [(x.fonte, x.motivo) for x in pl.partes[0].trocas] == [("sem", "desfocado")]
    assert any("sem cobertura" in a for a in pl.alertas)


def test_defeitos_proximos_viram_uma_troca():
    pl = montar_plano(PARTES, 200, [_d(10, 12), _d(12.3, 13, "escuro")], [],
                      [("CAM A\\a.mp4", 0, 100)], _frias())
    t = pl.partes[0].trocas
    assert [(x.inicio_s, x.fim_s, x.motivo) for x in t] == [(10, 13, "chicote")]


def test_defeito_dentro_de_corte_some():
    pl = montar_plano(PARTES, 200, [_d(42, 45), _d(48, 52)], [(40, 50)],
                      [("CAM A\\a.mp4", 0, 100)], _frias())
    t = pl.partes[0].trocas
    assert [(x.inicio_s, x.fim_s) for x in t] == [(49.5, 52)]


def test_defeito_atravessa_partes():
    pl = montar_plano(PARTES, 200, [_d(98, 103)], [], [("CAM A\\a.mp4", 0, 200)], _frias())
    assert [(x.inicio_s, x.fim_s) for x in pl.partes[0].trocas] == [(98, 100)]
    assert [(x.inicio_s, x.fim_s) for x in pl.partes[1].trocas] == [(100, 103)]


def test_assunto():
    assert assunto("hino") == assunto("encerramento") == "hino"
    assert assunto("colacao") == "colacao" and assunto("oradores") == "outro"
