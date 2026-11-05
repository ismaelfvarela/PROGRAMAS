import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from roteiro_ia import cli, pipeline
from roteiro_ia.config import Settings, load_settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.models import FolderAssignment, MediaInfo, Role, TrackInfo
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.pipeline import STAGES, Pipeline, ProjectRequest, music_paths
from roteiro_ia.safety import ProtectedPathError
from roteiro_ia.script.generate import MusicSuggestion, Piece, Roteiro, SceneRef

EVENTO = "2023-01-01 TESTE"


def mk_settings(tmp_path, **kw):
    base = dict(protected_roots=[str(tmp_path / "R")], music_root=str(tmp_path / "M"),
                work_drive=str(tmp_path / "Y"), e_root=str(tmp_path / "E"),
                g_root=str(tmp_path / "G"), system_dir=str(tmp_path / "SIS"),
                gemini_model_analysis="flash", gemini_model_script="pro")
    base.update(kw)
    return Settings(**base)


class FakeGemini:
    def __init__(self):
        self.picks = 0

    def pick_default_models(self):
        self.picks += 1
        return "auto-flash", "auto-pro"


def mk_req(tmp_path, mode="gratis"):
    src = tmp_path / "R" / EVENTO
    (src / "A").mkdir(parents=True, exist_ok=True)
    return ProjectRequest(source_dir=src, work_drive=str(tmp_path / "Y"),
                          assignments=[FolderAssignment(folder="A", role=Role.camera)],
                          n_episodios=3, derivados={"trailer", "teaser"}, gemini_mode=mode)


@pytest.fixture
def sleeps(monkeypatch):
    out = []
    monkeypatch.setattr(pipeline, "_sleep", out.append)
    return out


def mk_pipe(tmp_path, mode="gratis", settings=None, gemini=None):
    s = settings or mk_settings(tmp_path)
    events = []
    pipe = Pipeline(mk_req(tmp_path, mode), s, gemini or FakeGemini(), None,
                    lambda *a: events.append(a), settings_path=tmp_path / "SIS" / "config.json")
    calls = []
    for n in STAGES:
        pipe.impl[n] = (lambda n=n: calls.append(n))
    return pipe, calls, events


def test_ordem_das_etapas(tmp_path, sleeps):
    assert STAGES == ["inventario", "proxies", "audio", "sync", "transcricao", "cenas", "estilo",
                      "analise", "trilhas", "roteiro", "pdf", "premiere"]
    pipe, calls, events = mk_pipe(tmp_path)
    assert pipe.run() == "concluido"
    assert calls == STAGES
    assert all(pipe.db.stage_status(n) == "feito" for n in STAGES)
    assert events[0][0] == "inventario" and events[0][1].startswith("Iniciando")
    assert pipe.run() == "concluido" and calls == STAGES  # tudo feito: nada repete
    assert sleeps == []
    pipe.close()


def test_retoma_apos_oserror(tmp_path, sleeps):
    pipe, calls, _ = mk_pipe(tmp_path)
    n = {"x": 0}

    def flaky():
        n["x"] += 1
        if n["x"] <= 2:
            raise OSError("rede caiu")
        calls.append("proxies")
    pipe.impl["proxies"] = flaky
    assert pipe.run() == "concluido"
    assert sleeps == [10, 20]
    assert calls == STAGES
    pipe.close()


def test_oserror_persistente_marca_erro(tmp_path, sleeps):
    pipe, calls, _ = mk_pipe(tmp_path)

    def boom():
        raise OSError("NAS fora do ar")
    pipe.impl["proxies"] = boom
    with pytest.raises(RuntimeError) as ei:
        pipe.run()
    assert "NAS fora do ar" in str(ei.value)
    assert sleeps == [10, 20, 40, 80, 160]
    assert pipe.db.stage_status("proxies") == "erro"
    assert "NAS fora do ar" in pipe.db.stage_detail("proxies")
    assert calls == ["inventario"]
    pipe.close()


def test_caminho_protegido_nao_repete(tmp_path, sleeps):
    pipe, calls, _ = mk_pipe(tmp_path)

    def prot():
        raise ProtectedPathError("Escrita bloqueada")
    pipe.impl["audio"] = prot
    with pytest.raises(ProtectedPathError):
        pipe.run()
    assert sleeps == [] and pipe.db.stage_status("audio") == "erro"
    pipe.close()


def test_quota_pausa_e_continua(tmp_path, sleeps):
    pipe, calls, _ = mk_pipe(tmp_path)
    resume = datetime(2026, 11, 6, 0, 0, tzinfo=timezone(timedelta(hours=-8)))
    n = {"x": 0}

    def analise():
        n["x"] += 1
        if n["x"] == 1:
            raise QuotaPaused(resume)
        calls.append("analise")
    pipe.impl["analise"] = analise
    assert pipe.run() == "pausado"
    assert pipe.db.stage_status("analise") == "pausado"
    assert pipe.db.stage_detail("analise") == resume.isoformat()
    assert pipe.resume_at == resume
    assert calls == STAGES[:STAGES.index("analise")]
    assert pipe.run() == "concluido"
    assert calls == STAGES  # etapas feitas não repetem
    pipe.close()


def test_pago_exige_aprovacao(tmp_path, sleeps):
    pipe, calls, _ = mk_pipe(tmp_path, mode="pago")
    with pytest.raises(RuntimeError) as ei:
        pipe.run()
    assert "custo" in str(ei.value).lower()
    assert calls == STAGES[:STAGES.index("estilo")]
    assert pipe.db.stage_status("estilo") == "pendente"
    assert pipe.run(aprovado_custo=True) == "concluido"
    pipe.close()


def test_prepare_grava_projeto_e_estima_custo(tmp_path):
    s = mk_settings(tmp_path, price_usd_per_mtok=2.0)
    pipe, calls, _ = mk_pipe(tmp_path, mode="pago", settings=s)

    def inv():
        calls.append("inventario")
        pipe.db.add_media(MediaInfo(rel_path="A\\C1.MP4", folder="A", role=Role.camera,
                                    day_label="principal", kind="video", duration_s=3600,
                                    fps_num=30, fps_den=1, width=1, height=1, rotation=0,
                                    audio_channels=2))
    pipe.impl["inventario"] = inv
    p, cost = pipe.prepare()
    assert calls == ["inventario"]
    assert cost == pytest.approx(3600 * 100 / 1e6 * 2.0)
    proj = p.analysis_dir / "projeto.json"
    data = json.loads(proj.read_text(encoding="utf-8"))
    assert data["derivados"] == ["teaser", "trailer"]
    assert ProjectRequest.load(proj) == pipe.req
    assert s.gemini_mode == "gratis"  # o modo do pedido não altera as Settings originais
    pipe.close()


def test_modelos_padrao_escolhidos_uma_vez(tmp_path):
    s = mk_settings(tmp_path, gemini_model_analysis="", gemini_model_script="")
    g = FakeGemini()
    pipe, _, _ = mk_pipe(tmp_path, settings=s, gemini=g)
    assert pipe._models() == ("auto-flash", "auto-pro")
    assert pipe._models() == ("auto-flash", "auto-pro")
    assert g.picks == 1
    saved = load_settings(tmp_path / "SIS" / "config.json")
    assert saved.gemini_model_analysis == "auto-flash" and saved.gemini_model_script == "auto-pro"
    pipe.close()


def tr(path):
    return TrackInfo(path=path, bpm=80, beats_s=[], downbeats_s=[], energy=[], duration_s=100,
                     has_vocals=False, perfil="calma", mtime=1.0)


def test_trilhas_m_inacessivel_com_indice_avisa(tmp_path, sleeps):
    s = mk_settings(tmp_path, music_root=str(tmp_path / "NAO_EXISTE"))
    with MusicIndex(tmp_path / "SIS" / "trilhas.db", s) as idx:
        idx.upsert(tr("M:\\a.mp3"))
    pipe, _, events = mk_pipe(tmp_path, settings=s)
    pipe.impl["trilhas"] = pipe._st_trilhas
    assert pipe.run() == "concluido"
    assert pipe.db.stage_status("trilhas") == "feito"
    assert any(e[0] == "trilhas" and "não está acessível" in e[1] for e in events)
    assert sleeps == []
    pipe.close()


def test_trilhas_m_inacessivel_sem_indice_erro(tmp_path, sleeps):
    s = mk_settings(tmp_path, music_root=str(tmp_path / "NAO_EXISTE"))
    pipe, _, _ = mk_pipe(tmp_path, settings=s)
    pipe.impl["trilhas"] = pipe._st_trilhas
    with pytest.raises(RuntimeError) as ei:
        pipe.run()
    assert "trilhas" in str(ei.value).lower()
    assert pipe.db.stage_status("trilhas") == "erro"
    assert sleeps == []
    pipe.close()


def ref(rel="A\\C1.MP4"):
    return SceneRef(rel_path=rel, start_s=0, end_s=1, descricao="d", fala=None, motivo=None)


def roteiro_com(trilhas):
    pc = Piece(tipo="episodio", numero=1, titulo="T", tema="t", abertura=ref(), desenvolvimento=[],
               gancho=None, gancho_resolve_em=None, curva_emocao=[5], duracao_estimada_s=60,
               misturas=[], trilhas=trilhas, termos_musicbed=[])
    return Roteiro(arco="a", pecas=[pc], alertas=[])


def test_revise_nao_reprocessa_midia(tmp_path, sleeps, monkeypatch):
    pipe, calls, _ = mk_pipe(tmp_path)
    assert pipe.run() == "concluido"
    calls.clear()
    seen = {}

    def fake_generate(db, c, idx, style, model, n_episodios, derivados, pedido_ajuste=None):
        seen.update(model=model, n=n_episodios, derivados=derivados, pedido=pedido_ajuste)
        return roteiro_com([])
    monkeypatch.setattr(pipeline, "generate_roteiro", fake_generate)
    pipe.impl["roteiro"] = pipe._st_roteiro
    pipe.revise("mais emoção no episódio 2")
    assert seen == {"model": "pro", "n": 3, "derivados": {"trailer", "teaser"},
                    "pedido": "mais emoção no episódio 2"}
    assert calls == ["pdf", "premiere"]
    pipe.close()


def test_music_paths_copia_quando_configurado(tmp_path):
    s = mk_settings(tmp_path, copy_music_to_work=True,
                    protected_roots=[str(tmp_path / "R"), str(tmp_path / "M")])
    orig = tmp_path / "M" / "Pasta" / "lenta.mp3"
    orig.parent.mkdir(parents=True)
    orig.write_bytes(b"ID3musica")
    ms = MusicSuggestion(origem="biblioteca", path=str(orig), titulo="lenta", bpm=80, clima="c",
                         motivo="m", padrao_corte="1-3", exige_licenca=False)
    mb = ms.model_copy(update={"origem": "musicbed", "path": None})
    pipe, _, _ = mk_pipe(tmp_path, settings=s)
    p = pipe.p
    m = music_paths(roteiro_com([ms, mb]), p, s)
    assert list(m) == [str(orig)]
    copia = Path(m[str(orig)])
    assert copia.parent == p.music_dir and copia.read_bytes() == b"ID3musica"
    assert orig.read_bytes() == b"ID3musica" and sorted(orig.parent.iterdir()) == [orig]
    s2 = mk_settings(tmp_path, copy_music_to_work=False)
    assert music_paths(roteiro_com([ms]), p, s2) == {str(orig): str(orig)}
    pipe.close()


# ------------------------------------------------------------------ CLI


class FakePipe:
    instances = []
    result = "concluido"

    def __init__(self, req, s, gemini, transcriber, events, settings_path=None):
        self.req, self.s, self.settings_path = req, s, settings_path
        self.resume_at = datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)
        self.revised = None
        FakePipe.instances.append(self)

    def prepare(self):
        return None, 0.0

    def run(self, aprovado_custo=False):
        return FakePipe.result

    def revise(self, pedido, aprovado_custo=False):
        self.revised = pedido

    def close(self):
        pass


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    s = mk_settings(tmp_path)
    cfg = tmp_path / "SIS" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(s.model_dump_json(), encoding="utf-8")
    src = tmp_path / "R" / EVENTO
    for d in ("A", "B", "E - H4"):
        (src / d).mkdir(parents=True)
    FakePipe.instances = []
    FakePipe.result = "concluido"
    monkeypatch.setattr(cli, "Pipeline", FakePipe)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("não deveria perguntar"))
    return cfg, src


def test_cli_novo_com_papeis(cli_env, capsys):
    cfg, src = cli_env
    rc = cli.main(["--config", str(cfg), "novo", str(src), "--episodios", "4", "--sem-teaser",
                   "--papel", "E - H4=mesa", "--papel", "B=drone"])
    assert rc == 0
    req = FakePipe.instances[0].req
    roles = {a.folder: a.role for a in req.assignments}
    assert roles == {"A": Role.camera, "B": Role.drone, "E - H4": Role.mesa}
    assert req.n_episodios == 4 and req.derivados == {"trailer", "stories"}
    assert FakePipe.instances[0].settings_path == cfg


def test_cli_pausado_codigo_2(cli_env, capsys):
    cfg, src = cli_env
    FakePipe.result = "pausado"
    rc = cli.main(["--config", str(cfg), "novo", str(src), "--papel", "A=camera"])
    assert rc == 2
    assert "continuar" in capsys.readouterr().out


def test_cli_novo_pergunta_papeis(cli_env, monkeypatch):
    cfg, src = cli_env
    answers = iter(["", "pocket", "xyz", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert cli.main(["--config", str(cfg), "novo", str(src)]) == 0
    roles = {a.folder: a.role for a in FakePipe.instances[0].req.assignments}
    assert roles == {"A": Role.camera, "B": Role.pocket, "E - H4": Role.audio_ambiente}


def test_cli_continuar_e_ajustar(cli_env, tmp_path):
    cfg, src = cli_env
    s = load_settings(cfg)
    req = ProjectRequest(source_dir=src, work_drive=s.work_drive,
                         assignments=[FolderAssignment(folder="A", role=Role.camera)],
                         n_episodios=None, derivados=set(), gemini_mode="gratis")
    p = pipeline.build_event_paths(src, s, s.work_drive)
    req.save(p.analysis_dir / "projeto.json", s)
    assert cli.main(["--config", str(cfg), "continuar", str(src)]) == 0
    assert FakePipe.instances[-1].req == req
    assert cli.main(["--config", str(cfg), "ajustar", str(src), "trocar a trilha"]) == 0
    assert FakePipe.instances[-1].revised == "trocar a trilha"


def test_cli_continuar_sem_projeto_erro(cli_env, capsys):
    cfg, src = cli_env
    assert cli.main(["--config", str(cfg), "continuar", str(src)]) == 1
    assert "novo" in capsys.readouterr().err
