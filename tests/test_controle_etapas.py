"""Parar/Pausar nas etapas: o Parar não vira falha, o que foi gravado fica e o próximo run retoma."""
import os
from pathlib import Path

import pytest

from roteiro_ia import controle
from roteiro_ia.config import Settings
from roteiro_ia.controle import Controle, Interrompido
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import MediaInfo, Role, TrackInfo
from roteiro_ia.paths import build_event_paths


def _m(rel, kind="video", ch=2):
    return MediaInfo(rel_path=rel, folder=rel.split("\\")[0], role=Role.camera, day_label="D1",
                     kind=kind, duration_s=2.0, fps_num=30, fps_den=1, width=320, height=180,
                     rotation=0, audio_channels=ch)


@pytest.fixture
def env(tmp_path):
    s = Settings(work_drive=str(tmp_path / "work"), e_root=str(tmp_path / "E"),
                 g_root=str(tmp_path / "G"), system_dir=str(tmp_path / "sys"),
                 music_root=str(tmp_path / "music"), protected_roots=[str(tmp_path / "src")])
    src = tmp_path / "src" / "2026-05-10 Teste"
    src.mkdir(parents=True)
    p = build_event_paths(src, s)
    with ProjectDB(tmp_path / "p.db", s) as db:
        yield s, p, db, src


def _para_no_primeiro(c):
    """on_progress que pede Parar logo depois do 1º item começar."""
    def cb(i, total, *rest):
        if i == 1:
            c.parar()
    return cb


def test_make_proxies_parado_no_segundo_item_nao_registra_falha(env, monkeypatch):
    from roteiro_ia.media import proxies as px
    s, p, db, src = env
    for n in (1, 2, 3):
        db.add_media(_m(f"A\\C000{n}.MP4"))
    feitos = []

    def fake_run(cmd, timeout):
        Path(cmd[-1]).write_bytes(b"x")
        feitos.append(cmd[-1])
        return True, ""
    monkeypatch.setattr(px, "_run", fake_run)
    c = Controle()
    with controle.usar(c), pytest.raises(Interrompido):
        px.make_proxies(db, p, s, src, on_progress=_para_no_primeiro(c))
    assert len(feitos) == 1
    assert sum(1 for m in db.list_media() if db.proxy_for(m.id)) == 1
    assert db.list_falhas() == []
    assert c.estado == "parado"
    # retoma: só os que faltam
    px.make_proxies(db, p, s, src)
    assert len(feitos) == 3 and db.list_falhas() == []


def test_make_proxies_parar_no_meio_do_ffmpeg_descarta_part(env, monkeypatch):
    from roteiro_ia.media import proxies as px
    s, p, db, src = env
    db.add_media(_m("A\\C0001.MP4"))
    c = Controle()
    partes = []

    def fake_run(cmd, timeout):
        Path(cmd[-1]).write_bytes(b"meio")
        partes.append(Path(cmd[-1]))
        c.parar()
        raise Interrompido()
    monkeypatch.setattr(px, "_run", fake_run)
    with controle.usar(c), pytest.raises(Interrompido):
        px.make_proxies(db, p, s, src)
    assert partes and not partes[0].exists()
    assert db.list_falhas() == []


def test_update_index_parado_devolve_o_que_fez(tmp_path, monkeypatch):
    from roteiro_ia import music_index as mi
    s = Settings(work_drive=str(tmp_path / "Y"), system_dir=str(tmp_path / "sis"),
                 music_root=str(tmp_path / "musicas"), protected_roots=[str(tmp_path / "musicas")])
    root = tmp_path / "musicas"
    root.mkdir()
    for n in ("a", "b", "c"):
        (root / f"{n}.wav").write_bytes(b"RIFF")

    def fake_analyze(f, *a, **k):
        return TrackInfo(path=os.path.abspath(f), bpm=120, beats_s=[0.5], downbeats_s=[0.5],
                         energy=[0.1], duration_s=1, has_vocals=False, perfil="calma",
                         mtime=Path(f).stat().st_mtime)
    monkeypatch.setattr(mi, "analyze_track", fake_analyze)
    idx = mi.MusicIndex(tmp_path / "sis" / "trilhas.db", s)
    idx.upsert(fake_analyze(root / "a.wav").model_copy(update={"path": str(root / "sumiu.wav")}))
    c = Controle()
    with controle.usar(c):
        n = mi.update_index(s, idx, on_progress=_para_no_primeiro(c), tracker=object())
    assert n == 1
    paths = {Path(t.path).name for t in idx.all()}
    assert "a.wav" in paths and "sumiu.wav" in paths  # parado: nada é removido do índice
    assert len(paths) == 2
    assert mi.update_index(s, idx, tracker=object(), atualizar_versao=False) == 2  # só b e c
    idx.close()


def test_transcricao_parada_nao_registra_falha(env):
    from roteiro_ia.transcribe import transcribe_event
    from roteiro_ia.models import Word
    s, p, db, src = env
    for n in (1, 2):
        db.add_media(_m(f"A\\C000{n}.MP4"))
    c = Controle()

    class T:
        n = 0

        def transcribe(self, path):
            T.n += 1
            c.parar()
            return [Word(text="oi", start_s=0.0, end_s=0.5)]
    with controle.usar(c), pytest.raises(Interrompido):
        transcribe_event(db, src, T())
    assert T.n == 1 and db.list_falhas() == []


def test_audio_inventario_e_cenas_param_no_checkpoint(env, monkeypatch):
    from roteiro_ia import inventory, scenes
    from roteiro_ia.media import audio
    from roteiro_ia.models import FolderAssignment
    s, p, db, src = env
    c = Controle()
    c.parar()
    db.add_media(_m("A\\C0001.MP4"))
    monkeypatch.setattr(audio, "measure", lambda path: pytest.fail("não deveria medir"))
    with controle.usar(c):
        with pytest.raises(Interrompido):
            audio.analyze_audio(db, s, src)
        with pytest.raises(Interrompido):
            scenes.detect_segments(db, p)
        (src / "A").mkdir()
        (src / "A" / "x.mp4").write_bytes(b"x")
        monkeypatch.setattr(inventory, "ffprobe_bin", lambda: "ffprobe")
        with pytest.raises(Interrompido):
            inventory.scan(src, [FolderAssignment(folder="A", role=Role.camera)], db)
    assert db.list_falhas() == []


def test_estilo_parado_guarda_os_videos_ja_analisados(tmp_path):
    from roteiro_ia.gemini import style as st
    u1 = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    u2 = "https://www.youtube.com/watch?v=BBBBBBBBBBB"
    s = Settings(system_dir=str(tmp_path / "sys"), style_urls=[u1, u2], protected_roots=[])
    c = Controle()
    chamadas = []

    class Cli:
        def pick_default_models(self):
            return "flash", "pro"

        def generate_json(self, model, parts, schema, prompt, max_retries=3):
            chamadas.append(schema)
            c.parar()  # o editor clica em Parar durante a análise do 1º vídeo
            return st.VideoStyleNotes(url="x", tipo="episodio", duracao_s=600, ritmo_corte_s=3.0,
                                      abertura="a", gancho="g", uso_falas="f", trilha="t",
                                      cor="c", observacoes="o")
    with controle.usar(c), pytest.raises(Interrompido):
        st.build_style_profile(Cli(), s)
    assert chamadas == [st.VideoStyleNotes]  # nem o 2º vídeo nem o perfil agregado
    assert st.video_em_cache(s, u1) and not st.video_em_cache(s, u2)
    assert st.load_style_profile(s) is None


# ------------------------------------------------------------------ pipeline

def _pipe(tmp_path):
    from roteiro_ia.pipeline import STAGES, Pipeline
    from test_pipeline import FakeGemini, mk_req, mk_settings
    pipe = Pipeline(mk_req(tmp_path), mk_settings(tmp_path), FakeGemini(), None, None,
                    settings_path=tmp_path / "SIS" / "config.json")
    calls = []
    for n in STAGES:
        pipe.impl[n] = (lambda n=n: calls.append(n))
    return pipe, calls


def test_pipeline_parado_volta_etapa_para_pendente_e_retoma(tmp_path, monkeypatch):
    from roteiro_ia import pipeline
    from roteiro_ia.pipeline import STAGES
    monkeypatch.setattr(pipeline, "_sleep", lambda s: None)
    pipe, calls = _pipe(tmp_path)
    c = Controle()

    def audio_interrompido():
        c.parar()
        c.checkpoint()
    pipe.impl["audio"] = audio_interrompido
    with controle.usar(c):
        assert pipe.run() == "parado"
    assert pipe.db.stage_status("audio") == "pendente"
    assert pipe.db.stage_status("proxies") == "feito"
    assert pipe.db.stage_status("sync") == "pendente"
    assert pipe.db.list_falhas() == []
    pipe.impl["audio"] = lambda: calls.append("audio")
    assert pipe.run() == "concluido"
    assert calls == STAGES
    pipe.close()


def test_pipeline_etapa_que_volta_normal_apos_parar_nao_fica_feita(tmp_path):
    """update_index devolve normalmente quando parado: a etapa não pode ficar 'feito'."""
    pipe, calls = _pipe(tmp_path)
    c = Controle()
    pipe.impl["trilhas"] = c.parar
    with controle.usar(c):
        assert pipe.run() == "parado"
    assert pipe.db.stage_status("trilhas") == "pendente"
    assert "estilo" not in calls
    pipe.close()


def test_pipeline_pausa_entre_etapas(tmp_path):
    import threading
    import time
    pipe, calls = _pipe(tmp_path)
    c = Controle()
    def proxies():
        calls.append("proxies")
        c.pausar()
    pipe.impl["proxies"] = proxies
    out = {}

    def alvo():
        with controle.usar(c):
            out["r"] = pipe.run()
    t = threading.Thread(target=alvo, daemon=True)
    t.start()
    time.sleep(0.6)
    assert c.estado == "pausado" and calls == ["inventario", "proxies"]
    c.continuar()
    t.join(5)
    assert out["r"] == "concluido"
    pipe.close()


def test_revise_parado_mantem_roteiro_anterior(tmp_path):
    pipe, calls = _pipe(tmp_path)
    assert pipe.run() == "concluido"
    c = Controle()

    def roteiro_interrompido():
        c.parar()
        c.checkpoint()
    pipe.impl["roteiro"] = roteiro_interrompido
    with controle.usar(c), pytest.raises(Interrompido):
        pipe.revise("mais votos")
    assert pipe.db.stage_status("roteiro") == "feito"  # o roteiro anterior continua valendo
    assert pipe.db.stage_status("pdf") == "feito"
    pipe.close()


# ------------------------------------------------------------------ revisão 1

def _oserror_apos_parar(c):
    def impl():
        c.parar()
        raise OSError("NAS caiu")
    return impl


def test_parar_na_espera_de_nova_tentativa_volta_a_pendente(tmp_path):
    from roteiro_ia import pipeline
    pipe, calls = _pipe(tmp_path)
    c = Controle()
    pipe.impl["audio"] = _oserror_apos_parar(c)
    old = pipeline._sleep
    pipeline._sleep = controle.dormir  # a espera real, que acorda no Parar
    try:
        with controle.usar(c):
            assert pipe.run() == "parado"
    finally:
        pipeline._sleep = old
    assert pipe.db.stage_status("audio") == "pendente"
    pipe.close()


def test_revise_parado_na_espera_de_nova_tentativa_mantem_feito(tmp_path):
    from roteiro_ia import pipeline
    pipe, calls = _pipe(tmp_path)
    assert pipe.run() == "concluido"
    c = Controle()
    pipe.impl["roteiro"] = _oserror_apos_parar(c)
    old = pipeline._sleep
    pipeline._sleep = controle.dormir
    try:
        with controle.usar(c), pytest.raises(Interrompido):
            pipe.revise("mais votos")
    finally:
        pipeline._sleep = old
    assert pipe.db.stage_status("roteiro") == "feito"
    pipe.close()


def test_update_index_parado_dentro_da_trilha_devolve_o_feito(tmp_path, monkeypatch):
    """Interrompido vindo de dentro da análise (ex.: ffmpeg via proc.run) também devolve o feito."""
    from roteiro_ia import music_index as mi
    s = Settings(work_drive=str(tmp_path / "Y"), system_dir=str(tmp_path / "sis"),
                 music_root=str(tmp_path / "musicas"), protected_roots=[str(tmp_path / "musicas")])
    root = tmp_path / "musicas"
    root.mkdir()
    for n in ("a", "b", "c"):
        (root / f"{n}.wav").write_bytes(b"RIFF")
    c = Controle()
    vistos = []

    def fake_analyze(f, *a, **k):
        vistos.append(f.name)
        if len(vistos) == 2:
            c.parar()
            raise Interrompido()
        return TrackInfo(path=os.path.abspath(f), bpm=120, beats_s=[0.5], downbeats_s=[0.5],
                         energy=[0.1], duration_s=1, has_vocals=False, perfil="calma",
                         mtime=Path(f).stat().st_mtime)
    monkeypatch.setattr(mi, "analyze_track", fake_analyze)
    idx = mi.MusicIndex(tmp_path / "sis" / "trilhas.db", s)
    with controle.usar(c):
        assert mi.update_index(s, idx, tracker=object()) == 1
    assert len(idx.all()) == 1
    idx.close()
