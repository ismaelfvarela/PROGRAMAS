import datetime
import os
import re
from pathlib import Path

import pytest

from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.models import AudioStats, MediaInfo, Role
from roteiro_ia.paths import EventPaths
from roteiro_ia.report.pdf import (collect_technical_alerts, emotion_svg, fmt_tc, html_to_pdf,
                                   render_html)
from roteiro_ia.script.generate import MusicSuggestion, Piece, Roteiro, SceneRef


def make_paths(tmp_path):
    w = tmp_path / "work"
    return EventPaths(
        event_name="2026-05-10 CASAMENTO ANA E BRUNO", event_date=datetime.date(2026, 5, 10),
        year=2026, source_dir=tmp_path / "src", work_dir=w, proxies_dir=w / "P",
        analysis_dir=w / "ANALISE", music_dir=w / "T", backup_dir=w / "B",
        pdf_path=w / "r.pdf", db_path=w / "ANALISE" / "p.db", premiere_dir=tmp_path / "pr",
        prproj_path=tmp_path / "pr" / "x.prproj", export_dir=tmp_path / "ex")


def sample_roteiro():
    ab = SceneRef(rel_path="A\\C0001.MP4", start_s=1, end_s=6, descricao="Noiva se arrumando",
                  fala=None, motivo=None)
    dev = [SceneRef(rel_path="C\\C0042.MP4", start_s=751.4, end_s=760.0, descricao="Votos <b>",
                    fala="Eu te escolho todos os dias", motivo="Fio condutor", lembranca=True)]
    g = SceneRef(rel_path="C\\C0050.MP4", start_s=10, end_s=20, descricao="Ela abre a porta",
                 fala=None, motivo=None)
    tr = [MusicSuggestion(origem="popular", path=None, titulo="Perfect", bpm=63, clima="romântico",
                          motivo="combina", padrao_corte="1-3", exige_licenca=True)]
    ep = Piece(tipo="episodio", numero=1, titulo="O Início", tema="Preparação", abertura=ab,
               desenvolvimento=dev, gancho=g, gancho_resolve_em="Abertura do episódio 2",
               curva_emocao=[2, 5, 7, 9, 4], duracao_estimada_s=360, misturas=["Puxei a despedida"],
               trilhas=tr, termos_musicbed=["romantic piano"])
    tz = ep.model_copy(update={"tipo": "trailer", "numero": None, "titulo": "Trailer",
                               "gancho": None, "gancho_resolve_em": None})
    return Roteiro(arco="Um arco <script>x</script>", pecas=[tz, ep], alertas=["Sem take bom"])


def test_fmt_tc():
    assert fmt_tc(751.4) == "00:12:31"
    assert fmt_tc(0) == "00:00:00"
    assert fmt_tc(3661) == "01:01:01"


def test_html_tem_gancho_e_licenca(tmp_path):
    html = render_html(sample_roteiro(), make_paths(tmp_path), ["Ruído detectado em A\\C0003.MP4"])
    for t in ("Gancho", "exige licença", "C\\C0042.MP4 · 00:12:31", "Resolve em: Abertura do episódio 2",
              "Ruído detectado", "Sem take bom", "lembrança", "romantic piano"):
        assert t in html
    assert "<script>x" not in html and "&lt;b&gt;" in html
    assert html.index("O Início") < html.index("Trailer")


def test_svg_pontos():
    svg = emotion_svg([1, 3, 5, 7, 9])
    m = re.search(r'<polyline[^>]*points="([^"]+)"', svg)
    assert len(m.group(1).split()) == 5
    assert svg.count("<circle") == 5
    assert emotion_svg([]) == ""
    assert emotion_svg([4]).count("<circle") == 1


def test_collect_alertas(tmp_path):
    s = Settings()
    with ProjectDB(tmp_path / "p.db", s) as db:
        mid = db.add_media(MediaInfo(rel_path="A\\C0003.MP4", folder="A", role=Role.camera,
                                     day_label="principal", kind="video", duration_s=10,
                                     fps_num=30, fps_den=1, width=1, height=1, rotation=0,
                                     audio_channels=2))
        db.set_audio_stats(AudioStats(media_id=mid, mean_db=-20, peak_db=-3, noise_floor_db=-30,
                                      noisy=True))
        db.add_falha("gemini", "A\\C0009.MP4", "falhou")
        al = collect_technical_alerts(db)
    assert "Ruído detectado em A\\C0003.MP4" in al
    assert "gemini: A\\C0009.MP4 — falhou" in al


@pytest.mark.windows
def test_pdf_gerado(tmp_path):
    s = Settings()
    html = render_html(sample_roteiro(), make_paths(tmp_path), [])
    out = tmp_path / "out" / "r.pdf"
    out.parent.mkdir()
    html_to_pdf(html, out, s)
    assert out.read_bytes().startswith(b"%PDF")
    if os.environ.get("SAMPLE_OUT"):
        Path(os.environ["SAMPLE_OUT"]).write_bytes(out.read_bytes())
        Path(os.environ["SAMPLE_OUT"]).with_suffix(".html").write_text(html, encoding="utf-8")


class _Res:
    returncode = 0
    stderr = b""


def _arg(cmd, prefix):
    return next(a for a in cmd if a.startswith(prefix))


def test_edge_usa_user_data_dir_temporario(tmp_path, monkeypatch):
    from roteiro_ia.report import pdf as mod
    monkeypatch.setattr(mod, "find_edge", lambda: Path("edge.exe"))
    visto = {}

    def fake_run(cmd, **kw):
        d = Path(_arg(cmd, "--user-data-dir=").split("=", 1)[1])
        visto["existe"] = d.is_dir()
        visto["dir"] = d
        assert "--no-first-run" in cmd and "--no-default-browser-check" in cmd
        Path(_arg(cmd, "--print-to-pdf=").split("=", 1)[1]).write_bytes(b"%PDF-x")
        return _Res()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    html_to_pdf("<p>x</p>", tmp_path / "r.pdf", Settings())
    assert visto["existe"] and not visto["dir"].exists()


def test_pdf_antigo_nao_mascara_falha(tmp_path, monkeypatch):
    from roteiro_ia.report import pdf as mod
    monkeypatch.setattr(mod, "find_edge", lambda: Path("edge.exe"))
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: _Res())
    out = tmp_path / "r.pdf"
    out.write_bytes(b"%PDF-antigo")
    with pytest.raises(RuntimeError):
        html_to_pdf("<p>x</p>", out, Settings())
    assert out.read_bytes() == b"%PDF-antigo"


def test_pdf_novo_substitui_antigo(tmp_path, monkeypatch):
    from roteiro_ia.report import pdf as mod
    monkeypatch.setattr(mod, "find_edge", lambda: Path("edge.exe"))

    def fake_run(cmd, **kw):
        Path(_arg(cmd, "--print-to-pdf=").split("=", 1)[1]).write_bytes(b"%PDF-novo")
        return _Res()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    out = tmp_path / "r.pdf"
    out.write_bytes(b"%PDF-antigo")
    html_to_pdf("<p>x</p>", out, Settings())
    assert out.read_bytes() == b"%PDF-novo"
    assert not out.with_suffix(".tmp.pdf").exists()


def test_pdf_aberto_grava_com_numero(tmp_path, monkeypatch):
    from roteiro_ia.report import pdf as mod
    monkeypatch.setattr(mod, "find_edge", lambda: Path("edge.exe"))

    def fake_run(cmd, **kw):
        Path(_arg(cmd, "--print-to-pdf=").split("=", 1)[1]).write_bytes(b"%PDF-novo")
        return _Res()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    out = tmp_path / "EV - ROTEIRO.pdf"
    out.write_bytes(b"%PDF-aberto")
    (tmp_path / "EV - ROTEIRO (2).pdf").write_bytes(b"%PDF-outro")
    real_replace = os.replace

    def travado(a, b):
        if Path(b) == out:
            raise PermissionError("arquivo em uso")
        return real_replace(a, b)
    monkeypatch.setattr(mod.os, "replace", travado)
    got = html_to_pdf("<p>x</p>", out, Settings())
    assert got == tmp_path / "EV - ROTEIRO (3).pdf"
    assert got.read_bytes() == b"%PDF-novo" and out.read_bytes() == b"%PDF-aberto"
    assert not out.with_suffix(".tmp.pdf").exists()
    monkeypatch.setattr(mod.os, "replace", real_replace)
    assert html_to_pdf("<p>x</p>", out, Settings()) == out
