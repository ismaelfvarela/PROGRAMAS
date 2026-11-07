import subprocess
import sys
import threading
import time

import pytest

from roteiro_ia import controle, proc
from roteiro_ia.controle import Controle, Interrompido

WIN = sys.platform == "win32"


def test_run_devolve_saida_e_codigo():
    r = proc.run([sys.executable, "-c", "import sys; sys.stdout.reconfigure(encoding='utf-8'); print('olá'); sys.exit(3)"],
                 text=True, encoding="utf-8")
    assert r.returncode == 3 and r.stdout.strip() == "olá"
    rb = proc.run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ab')"])
    assert rb.stdout == b"ab"


def test_run_respeita_timeout():
    with pytest.raises(subprocess.TimeoutExpired):
        proc.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)


@pytest.mark.skipif(not WIN, reason="só no Windows")
def test_run_sem_janela_de_console(monkeypatch):
    visto = {}
    real = subprocess.Popen

    def fake(cmd, **kw):
        visto.update(kw)
        return real(cmd, **kw)
    monkeypatch.setattr(proc.subprocess, "Popen", fake)
    proc.run([sys.executable, "-c", "pass"])
    assert visto["creationflags"] & subprocess.CREATE_NO_WINDOW
    si = visto["startupinfo"]
    assert si.dwFlags & subprocess.STARTF_USESHOWWINDOW and si.wShowWindow == subprocess.SW_HIDE


def test_parar_mata_subprocesso_longo():
    c = Controle()
    out = {}

    def alvo():
        with controle.usar(c):
            try:
                proc.run([sys.executable, "-c", "import time; time.sleep(30)"])
            except BaseException as e:  # noqa: BLE001
                out["e"] = e
    t = threading.Thread(target=alvo, daemon=True)
    t.start()
    time.sleep(1.0)
    t0 = time.monotonic()
    c.parar()
    t.join(10)
    assert not t.is_alive()
    assert time.monotonic() - t0 < 7
    assert isinstance(out.get("e"), Interrompido)


def test_run_parado_nem_comeca():
    c = Controle()
    c.parar()
    with controle.usar(c), pytest.raises(Interrompido):
        proc.run([sys.executable, "-c", "pass"])


@pytest.mark.skipif(not WIN, reason="só no Windows")
def test_esconder_consoles_idempotente_e_preserva_flags():
    vistos = []

    class P(subprocess.Popen):
        def __init__(self, args, **kw):  # não cria processo: só registra os argumentos
            vistos.append(kw)

    proc.esconder_consoles(P)
    w1 = P.__init__
    proc.esconder_consoles(P)
    assert P.__init__ is w1
    P(["x"])
    assert vistos[-1]["creationflags"] == subprocess.CREATE_NO_WINDOW
    P(["x"], creationflags=subprocess.CREATE_NEW_CONSOLE)
    assert vistos[-1]["creationflags"] == subprocess.CREATE_NEW_CONSOLE


def test_pacote_nao_usa_subprocess_run_direto():
    """Toda chamada externa passa por proc.run (sem console e com Parar)."""
    import re
    from pathlib import Path
    raiz = Path(proc.__file__).parent
    achados = [f"{f.relative_to(raiz)}:{i}" for f in raiz.rglob("*.py") if f.name != "proc.py"
               for i, linha in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
               if re.search(r"subprocess\.(run|call|check_output|check_call)\(", linha)]
    assert achados == []
