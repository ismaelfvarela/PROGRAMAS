from datetime import datetime, timezone

from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.safety import ProtectedPathError
from roteiro_ia.ui.worker import PipelineWorker, Runner, TarefaWorker

RETOMADA = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)


class FakePipeline:
    def __init__(self, events, resultado="concluido", falha=None):
        self.events = events
        self.resultado = resultado
        self.falha = falha
        self.resume_at = None
        self.fechado = False
        self.chamadas = []

    def prepare(self):
        self.chamadas.append("prepare")
        self.events("inventario", "Concluído: inventário das mídias", 1.0)
        return None, 1.25

    def run(self, aprovado_custo=False, refazer_falhas=True):
        self.chamadas.append(("run", aprovado_custo))
        if self.falha:
            raise self.falha
        self.events("inventario", "Iniciando: inventário das mídias", 0.0)
        self.events("inventario", "Concluído: inventário das mídias", 1.0)
        if self.resultado == "pausado":
            self.resume_at = RETOMADA
        return self.resultado

    def revise(self, pedido, aprovado_custo=False):
        self.chamadas.append(("revise", pedido, aprovado_custo))
        raise QuotaPaused(RETOMADA)

    def close(self):
        self.fechado = True


def _rodar(qtbot, worker):
    runner = Runner()
    with qtbot.waitSignal(worker.terminou, timeout=5000) as b:
        runner.start(worker)
    qtbot.waitUntil(lambda: not runner.ativo(), timeout=5000)
    return b.args[0]


def test_worker_emite_progresso_e_terminou(qtbot):
    criados = []

    def factory(events):
        criados.append(FakePipeline(events))
        return criados[-1]

    w = PipelineWorker(factory)
    eventos = []
    w.progresso.connect(lambda *a: eventos.append(a))
    assert _rodar(qtbot, w) == "concluido"
    assert eventos == [("inventario", "Iniciando: inventário das mídias", 0.0),
                       ("inventario", "Concluído: inventário das mídias", 1.0)]
    assert criados[0].chamadas == [("run", False)]
    assert criados[0].fechado


def test_worker_pausado_informa_retomada(qtbot):
    w = PipelineWorker(lambda ev: FakePipeline(ev, resultado="pausado"), aprovado_custo=True)
    quando = []
    w.retomar_em.connect(quando.append)
    assert _rodar(qtbot, w) == "pausado"
    assert quando == [RETOMADA]


def test_worker_prepare_emite_custo(qtbot):
    w = PipelineWorker(lambda ev: FakePipeline(ev), acao="prepare")
    custos = []
    w.custo.connect(custos.append)
    assert _rodar(qtbot, w) == "preparado"
    assert custos == [1.25]


def test_worker_ajuste_pausado_pela_cota(qtbot):
    p = []

    def factory(ev):
        p.append(FakePipeline(ev))
        return p[-1]

    w = PipelineWorker(factory, acao="revise", pedido="mais votos", aprovado_custo=True)
    quando = []
    w.retomar_em.connect(quando.append)
    assert _rodar(qtbot, w) == "pausado"
    assert p[0].chamadas == [("revise", "mais votos", True)]
    assert quando == [RETOMADA]


def test_worker_erro_caminho_protegido(qtbot):
    w = PipelineWorker(lambda ev: FakePipeline(
        ev, falha=ProtectedPathError("Escrita bloqueada em R:\\x")))
    erros = []
    w.erro.connect(erros.append)
    assert _rodar(qtbot, w) == "erro"
    assert erros == ["Bloqueado por segurança: Escrita bloqueada em R:\\x"]


def test_worker_erro_generico(qtbot):
    w = PipelineWorker(lambda ev: FakePipeline(ev, falha=RuntimeError("A etapa 'x' falhou: y")))
    erros = []
    w.erro.connect(erros.append)
    assert _rodar(qtbot, w) == "erro"
    assert erros == ["A etapa 'x' falhou: y"]


def test_tarefa_worker_resultado_e_progresso(qtbot):
    def fn(progress):
        progress(1, 2, "a.mp3")
        progress(2, 2, "b.mp3")
        return 42

    w = TarefaWorker(fn)
    prog, res = [], []
    w.progresso.connect(lambda *a: prog.append(a))
    w.resultado.connect(res.append)
    runner = Runner()
    with qtbot.waitSignal(w.terminou, timeout=5000):
        runner.start(w)
    qtbot.waitUntil(lambda: not runner.ativo(), timeout=5000)
    assert prog == [(1, 2, "a.mp3"), (2, 2, "b.mp3")]
    assert res == [42]


def test_worker_repassa_refazer_falhas(qtbot):
    criados = []

    class P(FakePipeline):
        def run(self, aprovado_custo=False, refazer_falhas=True):
            self.refazer = refazer_falhas
            return super().run(aprovado_custo)

    def factory(events):
        criados.append(P(events))
        return criados[-1]

    assert _rodar(qtbot, PipelineWorker(factory, refazer_falhas=False)) == "concluido"
    assert criados[-1].refazer is False
    assert _rodar(qtbot, PipelineWorker(factory)) == "concluido"
    assert criados[-1].refazer is True
