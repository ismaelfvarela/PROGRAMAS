from pathlib import Path

import pytest

from roteiro_ia.models import TrackInfo
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.pipeline import Pipeline
from roteiro_ia.safety import ProtectedPathError, assert_writable
from test_pipeline import FakeGemini, mk_req, mk_settings


def _pipe(tmp_path, pasta):
    req = mk_req(tmp_path)
    req.pasta_musicas = str(pasta)
    return Pipeline(req, mk_settings(tmp_path), FakeGemini(), None, None,
                    settings_path=tmp_path / "SIS" / "config.json")


def test_pipeline_protege_a_pasta_de_musicas(tmp_path):
    pasta = tmp_path / "MinhasMusicas"
    p = _pipe(tmp_path, pasta)
    with pytest.raises(ProtectedPathError):
        assert_writable(pasta / "x.txt", p.s)
    p.close()


def test_pipeline_sem_pasta_nao_altera_protecao(tmp_path):
    req = mk_req(tmp_path)
    s = mk_settings(tmp_path)
    p = Pipeline(req, s, FakeGemini(), None, None, settings_path=tmp_path / "SIS" / "config.json")
    assert p.s.protected_roots == s.protected_roots
    p.close()


def test_pipeline_pasta_sumiu_usa_indice_existente(tmp_path):
    p = _pipe(tmp_path, tmp_path / "naoexiste")
    p._index().upsert(TrackInfo(path=str(tmp_path / "naoexiste" / "a.wav"), bpm=120,
                                beats_s=[0.5], downbeats_s=[0.5], energy=[0.1], duration_s=10,
                                has_vocals=False, perfil="calma", mtime=0))
    assert p._st_trilhas() == "índice existente (pasta de músicas inacessível)"
    p.close()
