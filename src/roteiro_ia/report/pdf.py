"""PDF do pré-roteiro: HTML (Jinja2, autoescape) impresso pelo Microsoft Edge em modo headless."""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from roteiro_ia import controle, proc
from roteiro_ia.config import Settings
from roteiro_ia.db import ProjectDB
from roteiro_ia.downloads import link_artlist, link_musicbed, link_youtube
from roteiro_ia.models import TrackInfo
from roteiro_ia.music_index import MusicIndex
from roteiro_ia.paths import EventPaths
from roteiro_ia.safety import assert_writable, safe_write_text
from roteiro_ia.script.generate import MusicSuggestion, Roteiro

EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
PDF_TIMEOUT_S = 120
# O Edge 157 devolve o controle (rc=0) antes de gravar o PDF, que chega segundos depois por
# outro processo: espera o arquivo aparecer e o tamanho parar de mudar.
PDF_ESPERA_S = 60
_ORDEM_TIPO = {"episodio": 0, "trailer": 1, "teaser": 2, "stories": 3}
_ROTULO_TIPO = {"episodio": "Episódio", "trailer": "Trailer", "teaser": "Teaser",
                "stories": "Stories / Reels"}
_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro")

_env = Environment(loader=PackageLoader("roteiro_ia.report", "templates"),
                   autoescape=select_autoescape(["html"], default=True))


def fmt_tc(seconds: float) -> str:
    t = int(max(0, seconds))
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def fmt_ref(rel_path: str, start_s: float, end_s: float) -> str:
    return f"{rel_path} · {fmt_tc(start_s)}–{fmt_tc(end_s)}"


def fmt_dur(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m} min {s:02d} s"


def emotion_svg(curva: list[int], width: int = 480, height: int = 120) -> str:
    """Curva de emoção (escala 0–10) como SVG inline; vazia -> ''."""
    if not curva:
        return ""
    pad_x, pad_y = 12, 10
    w, h = width - 2 * pad_x, height - 2 * pad_y
    n = len(curva)

    def y(v: float) -> float:
        return pad_y + h - (min(10.0, max(0.0, float(v))) / 10.0) * h

    def x(i: int) -> float:
        return pad_x + (w / 2 if n == 1 else i * w / (n - 1))

    grid = "".join(
        f'<line x1="{pad_x}" y1="{y(v):.1f}" x2="{width - pad_x}" y2="{y(v):.1f}" '
        f'stroke="#e4e1dc" stroke-width="1"/>' for v in (0, 5, 10))
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(curva))
    line = (f'<polyline fill="none" stroke="#b4542d" stroke-width="2" '
            f'stroke-linejoin="round" points="{pts}"/>')
    dots = "".join(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" fill="#b4542d"/>'
                   for i, v in enumerate(curva))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="Curva de emoção">'
            f'{grid}{line}{dots}</svg>')


def collect_technical_alerts(db: ProjectDB) -> list[str]:
    alerts = []
    for m in db.list_media():
        st = db.get_audio_stats(m.id)
        if st is not None and st.noisy:
            alerts.append(f"Ruído detectado em {m.rel_path}")
    for f in db.list_falhas():
        alerts.append(f"{f.etapa}: {f.rel_path} — {f.msg}")
    return alerts


def fmt_ms(seconds: float) -> str:
    t = int(round(max(0.0, seconds)))
    return f"{t // 60}:{t % 60:02d}"


def clima_voz(ms: MusicSuggestion, info: TrackInfo | None) -> str:
    """"romântica · instrumental" / "épica · cantada (feminina)" a partir do índice; sem a
    trilha no índice (Musicbed, popular), só o clima sugerido pelo roteiro."""
    if info is None:
        return ms.clima
    clima = info.climas[0] if info.climas else ms.clima
    if not info.has_vocals:
        voz = "instrumental"
    elif info.tipo_voz and info.tipo_voz != "sem voz":
        voz = f"cantada ({info.tipo_voz})"
    else:
        voz = "cantada"
    return f"{clima} · {voz}"


_ONDE = {"biblioteca": "já na biblioteca (M:)", "popular": "da internet — precisa de licença",
         "musicbed": "Musicbed"}


def indice_musicas(r: Roteiro) -> list[dict]:
    """Índice das músicas do roteiro, por peça: as escolhidas (com onde estão) e os termos de
    busca, com links para Artlist, Musicbed e YouTube (as da internet, para ouvir e baixar)."""
    pecas = sorted(r.pecas, key=lambda x: (_ORDEM_TIPO.get(x.tipo, 9), x.numero or 0))
    out = []
    for pc in pecas:
        rotulo = _ROTULO_TIPO.get(pc.tipo, pc.tipo)
        if pc.tipo == "episodio" and pc.numero is not None:
            rotulo = f"{rotulo} {pc.numero}"
        musicas = []
        for ms in pc.trilhas:
            nome = (Path(ms.path.replace("\\", "/")).name if ms.origem == "biblioteca" and ms.path
                    else ms.titulo)
            links = []
            if ms.origem != "biblioteca":
                links = [("YouTube", link_youtube(ms.titulo)), ("Artlist", link_artlist(ms.titulo)),
                         ("Musicbed", link_musicbed(ms.titulo))]
            musicas.append({"nome": nome, "onde": _ONDE.get(ms.origem, ms.origem),
                            "clima": ms.clima, "links": links})
        termos = [{"t": t, "links": [("Artlist", link_artlist(t)), ("Musicbed", link_musicbed(t))]}
                  for t in pc.termos_musicbed]
        out.append({"rotulo": rotulo, "titulo": pc.titulo, "musicas": musicas, "termos": termos})
    return out


def render_html(r: Roteiro, p: EventPaths, alertas_tecnicos: list[str],
                idx: MusicIndex | None = None, observacoes=None) -> str:
    pecas = sorted(r.pecas, key=lambda x: (_ORDEM_TIPO.get(x.tipo, 9), x.numero or 0))
    d = p.event_date
    tracks = {t.path.replace("/", "\\").lower(): t for t in idx.all()} if idx is not None else {}
    view = []
    for pc in pecas:
        rotulo = _ROTULO_TIPO.get(pc.tipo, pc.tipo)
        if pc.tipo == "episodio" and pc.numero is not None:
            rotulo = f"{rotulo} {pc.numero}"
        trilhas = []
        for ms in pc.trilhas:
            info = (tracks.get((ms.path or "").replace("/", "\\").lower())
                    if ms.origem == "biblioteca" else None)
            trilhas.append({"t": ms, "clima_voz": clima_voz(ms, info),
                            "inicio": (f"começar em {fmt_ms(ms.trecho_inicio_s)}"
                                       if ms.trecho_inicio_s is not None else "")})
        view.append({"peca": pc, "rotulo": rotulo, "svg": Markup(emotion_svg(pc.curva_emocao)),
                     "duracao": fmt_dur(pc.duracao_estimada_s), "trilhas": trilhas})
    tpl = _env.get_template("roteiro.html")
    return tpl.render(
        evento=p.event_name, data=f"{d.day} de {_MESES[d.month - 1]} de {d.year}", arco=r.arco,
        itens=view, alertas=list(alertas_tecnicos) + list(r.alertas), ref=fmt_ref,
        observacoes=observacoes.itens_pdf() if observacoes is not None else [],
        artlist=link_artlist, musicbed=link_musicbed, indice=indice_musicas(r))


def find_edge() -> Path:
    for e in EDGE_PATHS:
        if e.exists():
            return e
    raise RuntimeError("Não encontrei o Microsoft Edge neste computador. "
                       "Instale o Edge para gerar o PDF do roteiro.")


def _next_numbered(out: Path) -> Path:
    n = 2
    while True:
        cand = out.with_name(f"{out.stem} ({n}){out.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _esperar_pdf(pdf: Path, prazo_s: float) -> bool:
    fim = time.monotonic() + prazo_s
    anterior = -1
    while time.monotonic() < fim:
        controle.atual().checkpoint()  # Parar não fica preso esperando o Edge
        try:
            tam = pdf.stat().st_size
        except OSError:
            tam = -1
        if tam > 0 and tam == anterior:
            return True
        anterior = tam
        time.sleep(0.5)
    return False


def html_to_pdf(html: str, out: Path, s: Settings, html_path: Path | None = None) -> Path:
    """Grava o HTML (por padrão ao lado do PDF; o pipeline passa ANALISE/roteiro.html) e
    imprime em PDF com o Edge. Se o PDF anterior estiver aberto (travado no visualizador),
    grava como "<nome> (2).pdf" (próximo número livre). Devolve o caminho efetivo."""
    edge = find_edge()
    out = Path(out)
    assert_writable(out, s)
    html_path = Path(html_path) if html_path else out.with_suffix(".html")
    safe_write_text(html_path, html, s)
    tmp_pdf = out.with_suffix(".tmp.pdf")
    assert_writable(tmp_pdf, s)
    if tmp_pdf.exists():
        tmp_pdf.unlink()
    try:
        with tempfile.TemporaryDirectory(prefix="roteiro-edge-", ignore_cleanup_errors=True) as prof:
            cmd = [str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                   "--no-first-run", "--no-default-browser-check", f"--user-data-dir={prof}",
                   f"--print-to-pdf={tmp_pdf}", html_path.resolve().as_uri()]
            try:
                res = proc.run(cmd, timeout=PDF_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                raise RuntimeError("O Edge demorou demais para gerar o PDF do roteiro.") from None
            if res.returncode == 0:
                _esperar_pdf(tmp_pdf, PDF_ESPERA_S)
        if res.returncode != 0 or not tmp_pdf.exists():
            detalhe = res.stderr.decode("utf-8", "replace").strip()[-300:]
            raise RuntimeError(f"Não consegui gerar o PDF do roteiro com o Edge. {detalhe}")
        try:
            os.replace(tmp_pdf, out)
        except PermissionError:
            out = _next_numbered(out)
            assert_writable(out, s)
            os.replace(tmp_pdf, out)
    finally:
        tmp_pdf.unlink(missing_ok=True)
    return out
