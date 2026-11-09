import pytest

from roteiro_ia.areas.formatura.cadastro import Curso, Formatura
from roteiro_ia.areas.formatura.projeto import ProjetoFormatura
from roteiro_ia.areas.formatura.roteiro import IndiceSem, contexto_clipe
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import MediaInfo, Role, SceneAnalysis, Segment, TrackInfo
from roteiro_ia.music_index import MusicIndex


@pytest.fixture
def env(tmp_path):
    s = Settings(system_dir=str(tmp_path / "sys"), protected_roots=[])
    db = ProjectDB(tmp_path / "p.db", s)
    a = db.add_media(MediaInfo(rel_path="2026-03-10\\CAM A\\C1.MP4", folder="2026-03-10\\CAM A",
                               role=Role.camera, day_label="2026-03-10", kind="video",
                               duration_s=60, fps_num=30, fps_den=1, width=1920, height=1080,
                               rotation=0, audio_channels=2))
    sid = db.add_segments([Segment(media_id=a, start_s=0, end_s=30)])[0]
    db.set_analysis(SceneAnalysis(segment_id=sid, momento="alunos trabalhando", descricao="solda",
                                  pessoas=["aluno"], emocao_intensidade=6, emocao_tipo="foco",
                                  qualidade=8, problemas=[], melhores_trechos=[], falas_chave=[],
                                  potencial_gancho=False, sugestao_lembranca=False))
    idx = MusicIndex(tmp_path / "t.db", s)
    for p in ("M:\\pop\\a.mp3", "M:\\pop\\b.mp3"):
        idx.upsert(TrackInfo(path=p, bpm=120, beats_s=[], downbeats_s=[], energy=[],
                             duration_s=200, has_vocals=True, perfil="intensa", mtime=1.0))
    yield db, idx
    db.close()
    idx.close()


FICHA = Formatura(id="x", instituicao="Escola X", ano=2026, semestre=2,
                  cursos=[Curso(nome="Eletrônica", turmas=["T106"])])
PF = ProjetoFormatura(tipo="oficina", formatura_id="x", curso="Eletrônica", turma="T106",
                      duracao_min=4)


def test_contexto_clipe_oficina(env):
    db, idx = env
    txt = contexto_clipe(PF, FICHA, None)(db, idx, None, 1, set())
    for trecho in ("UMA peça", "240 s", "Escola X", "Eletrônica", "T106", "2026/2", "cartela",
                   "chicote", "desfocad", "mal enquadrad", "comercial", 'origem "popular"',
                   'numero 1', "gancho null", "Oficina — Eletrônica T106", "solda",
                   "M:\\pop\\a.mp3", "depoimentos", "O assunto vale mais que a técnica"):
        assert trecho in txt, trecho
    assert "em série" not in txt and "IDEIA DA ORIGINAL" not in txt


def test_contexto_feira_guiado_pela_fala(env):
    db, idx = env
    pf = PF.model_copy(update={"tipo": "feira", "turma": None, "duracao_min": 8})
    txt = contexto_clipe(pf, FICHA, None)(db, idx, None, 1, set())
    assert "480 s" in txt and "documental" in txt and "Feira — Eletrônica" in txt


def test_contexto_com_ideia_da_original(env):
    db, idx = env
    txt = contexto_clipe(PF, FICHA, '{"arco": "ideia antiga"}')(db, idx, None, 1, set())
    assert "IDEIA DA ORIGINAL" in txt and "ideia antiga" in txt and "OUTRA música" in txt


def test_contexto_sem_ficha_e_sem_trilhas(tmp_path, env):
    db, _ = env
    s = Settings(system_dir=str(tmp_path / "sys2"), protected_roots=[])
    vazio = MusicIndex(tmp_path / "vazio.db", s)
    try:
        txt = contexto_clipe(PF, None, None)(db, vazio, None, 1, set())
    finally:
        vazio.close()
    assert "sugira só pelo nome" in txt and "T106" in txt


def test_indice_sem_exclui(env):
    _, idx = env
    vista = IndiceSem(idx, {"m:/POP/a.mp3"})  # grafia diferente também conta
    assert [t.path for t in vista.all()] == ["M:\\pop\\b.mp3"]
    assert vista.get("M:\\pop\\a.mp3") is not None  # o resto delega


def test_prompts_de_estilo_registrados():
    import roteiro_ia.areas.formatura  # noqa: F401
    from roteiro_ia.gemini import style
    pv, pa = style._PROMPTS["formatura"]
    assert "formatura" in pv and "casamento" not in pv and "formatura" in pa
