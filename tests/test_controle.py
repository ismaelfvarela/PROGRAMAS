import threading
import time

import pytest

from roteiro_ia import controle
from roteiro_ia.controle import Controle, Interrompido


def _em_thread(fn):
    out = {}

    def alvo():
        try:
            out["r"] = fn()
        except BaseException as e:  # noqa: BLE001
            out["e"] = e
    t = threading.Thread(target=alvo, daemon=True)
    t.start()
    return t, out


def test_pausar_bloqueia_no_checkpoint_e_continuar_libera():
    c = Controle()
    estados = []
    c.ao_mudar = estados.append
    c.pausar()
    assert c.estado == "pausando" and c.aguardando_pausa
    t, out = _em_thread(c.checkpoint)
    time.sleep(0.4)
    assert t.is_alive() and c.estado == "pausado" and not c.aguardando_pausa
    c.continuar()
    t.join(2)
    assert not t.is_alive() and "e" not in out
    assert c.estado == "rodando"
    assert estados == ["pausando", "pausado", "rodando"]


def test_parar_durante_pausa_levanta_interrompido():
    c = Controle()
    c.pausar()
    t, out = _em_thread(c.checkpoint)
    time.sleep(0.3)
    c.parar()
    t.join(2)
    assert isinstance(out.get("e"), Interrompido)
    assert c.estado == "parado"


def test_parar_levanta_no_proximo_checkpoint():
    c = Controle()
    c.checkpoint()  # rodando: passa direto
    c.parar()
    assert c.estado == "parando"
    with pytest.raises(Interrompido):
        c.checkpoint()
    assert c.estado == "parado"
    c.continuar()  # parado não volta a rodar: um novo processo usa um controle novo
    assert c.estado == "parado"


def test_controle_nulo_nunca_bloqueia():
    nulo = controle.atual()
    nulo.pausar()
    nulo.parar()
    nulo.checkpoint()
    assert nulo.estado == "rodando"


def test_usar_define_o_controle_atual_por_contexto():
    c = Controle()
    with controle.usar(c):
        assert controle.atual() is c
        vistos = []
        t = threading.Thread(target=lambda: vistos.append(controle.atual()))
        t.start()
        t.join()
        assert vistos[0] is not c  # outra thread não herda o controle
    assert controle.atual() is not c


def test_interrompido_atravessa_except_exception():
    c = Controle()
    c.parar()
    falhas = []
    with pytest.raises(Interrompido):
        for _ in range(3):
            try:
                c.checkpoint()
            except Exception as e:  # noqa: BLE001 - como os laços por arquivo das etapas
                falhas.append(e)
    assert falhas == []
    assert not issubclass(Interrompido, Exception)


def test_esperar_acorda_no_parar():
    c = Controle()
    t, out = _em_thread(lambda: c.esperar(30))
    time.sleep(0.2)
    t0 = time.monotonic()
    c.parar()
    t.join(3)
    assert isinstance(out.get("e"), Interrompido)
    assert time.monotonic() - t0 < 2


def test_parar_encerra_subprocessos_registrados():
    class P:
        def __init__(self):
            self.terminado = False

        def poll(self):
            return 0 if self.terminado else None

        def terminate(self):
            self.terminado = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    c = Controle()
    a, b = P(), P()
    c.registrar(a)
    c.registrar(b)
    c.liberar(b)
    c.parar()
    assert a.terminado and not b.terminado
    late = P()
    c.registrar(late)  # registrado depois do Parar: encerrado na hora
    assert late.terminado
