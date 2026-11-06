import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roteiro_ia.config import Settings
from roteiro_ia.gemini import style as st
from roteiro_ia.gemini.client import QuotaPaused
from roteiro_ia.gemini.style import (StyleProfile, VideoStyleNotes, build_style_profile,
                                     expand_playlists, load_style_profile)

U1 = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
U2 = "https://www.youtube.com/watch?v=BBBBBBBBBBB"


def notes(url="x", tipo="episodio"):
    return VideoStyleNotes(url=url, tipo=tipo, duracao_s=600, ritmo_corte_s=3.0, abertura="a",
                           gancho="g", uso_falas="f", trilha="t", cor="c", observacoes="o")


def profile(fontes):
    return StyleProfile(fontes=fontes, duracao_media_episodio_s=600, ritmo_corte_medio_s=3.0,
                        padroes_abertura=["a"], padroes_gancho=["g"], uso_falas="f", trilhas="t",
                        cor="c", estrutura_teaser_trailer="e", resumo="r")


class FakeClient:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}

    def pick_default_models(self):
        return "flash-x", "pro-x"

    def generate_json(self, model, parts, schema, prompt, max_retries=3):
        self.calls.append((model, parts, schema, prompt))
        if schema is VideoStyleNotes:
            uri = parts[0].file_data.file_uri
            if uri in self.fail:
                raise self.fail[uri]
            return notes(uri)
        return profile([])


def settings(tmp_path, urls):
    return Settings(system_dir=str(tmp_path / "sys"), style_urls=urls, protected_roots=[])


def test_expand_playlists_pega_v():
    vids, ign = expand_playlists([
        "https://www.youtube.com/watch?v=AAAAAAAAAAA&list=PLx&index=3",
        "https://youtu.be/BBBBBBBBBBB?si=z",
        "https://www.youtube.com/shorts/CCCCCCCCCCC",
        "https://www.youtube.com/watch?v=AAAAAAAAAAA",
        "https://www.youtube.com/playlist?list=PLx",
    ])
    assert vids == [U1, U2, "https://www.youtube.com/watch?v=CCCCCCCCCCC"]
    assert ign == ["https://www.youtube.com/playlist?list=PLx"]


def test_build_usa_cache(tmp_path):
    s = settings(tmp_path, [U1, U2])
    c = FakeClient()
    build_style_profile(c, s)
    n1 = len([x for x in c.calls if x[2] is VideoStyleNotes])
    assert n1 == 2
    assert c.calls[0][0] == "flash-x"
    c2 = FakeClient()
    p = build_style_profile(c2, s)
    assert [x for x in c2.calls if x[2] is VideoStyleNotes] == []
    assert len(c2.calls) == 1
    assert p.fontes == [U1, U2]
    assert (tmp_path / "sys" / "estilo_cache" / "AAAAAAAAAAA.json").exists()


def test_profile_salvo_em_system_dir(tmp_path):
    s = settings(tmp_path, [U1])
    assert load_style_profile(s) is None
    p = build_style_profile(FakeClient(), s)
    f = tmp_path / "sys" / "perfil_estilo.json"
    assert json.loads(f.read_text(encoding="utf-8"))["fontes"] == [U1]
    assert load_style_profile(s) == p
    f.write_text("{ruim", encoding="utf-8")
    assert load_style_profile(s) is None


def test_video_com_erro_e_pulado_e_quota_propaga(tmp_path, caplog):
    s = settings(tmp_path, [U1, U2])
    c = FakeClient(fail={U1: RuntimeError("privado")})
    p = build_style_profile(c, s)
    assert p.fontes == [U2]
    assert "pulado" in caplog.text.lower() or "pulando" in caplog.text.lower()
    s2 = settings(tmp_path / "o", [U1])
    with pytest.raises(RuntimeError, match="Nenhum"):
        build_style_profile(FakeClient(fail={U1: RuntimeError("x")}), s2)
    s3 = settings(tmp_path / "q", [U1])
    with pytest.raises(QuotaPaused):
        build_style_profile(FakeClient(fail={U1: QuotaPaused(__import__("datetime").datetime.now())}), s3)


# ------------------------------------------------------------------ progresso por vídeo

U3 = "https://www.youtube.com/watch?v=CCCCCCCCCCC"
PL = "https://www.youtube.com/playlist?list=PLx"


def _cache(s, url):
    d = Path(s.system_dir) / "estilo_cache"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{url.rsplit('=', 1)[1]}.json").write_text(notes(url).model_dump_json(), encoding="utf-8")


def test_progresso_por_video_na_ordem(tmp_path):
    s = settings(tmp_path, [U1, U2, U3, PL])
    _cache(s, U1)
    assert st.video_em_cache(s, U1) and not st.video_em_cache(s, U2)
    ev = []
    build_style_profile(FakeClient(fail={U3: RuntimeError("privado")}), s,
                        on_progress=lambda *a: ev.append(a))
    assert ev == [
        (PL, "ignorado", 0, 3),
        (U1, "feito", 1, 3),       # cache: feito na hora
        (U2, "aguardando", 1, 3),
        (U3, "aguardando", 1, 3),
        (U2, "analisando", 1, 3),
        (U2, "feito", 2, 3),
        (U3, "analisando", 2, 3),
        (U3, "erro", 2, 3),
    ]


def test_progresso_para_na_cota(tmp_path):
    from datetime import datetime
    s = settings(tmp_path, [U1, U2])
    ev = []
    with pytest.raises(QuotaPaused):
        build_style_profile(FakeClient(fail={U1: QuotaPaused(datetime.now())}), s,
                            on_progress=lambda *a: ev.append(a))
    assert ev[-1] == (U1, "analisando", 0, 2)
